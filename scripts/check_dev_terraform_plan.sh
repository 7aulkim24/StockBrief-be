#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run a safe dev Terraform plan with the same operational alarm input shape used by deploy.

Examples:
  OPERATIONAL_ALARM_EMAILS_JSON='["ops@example.com"]' \
    scripts/check_dev_terraform_plan.sh

  scripts/check_dev_terraform_plan.sh \
    --alarm-emails-json '["ops@example.com"]'

Options:
  --terraform-dir VALUE        Terraform directory. Default: infra/terraform
  --backend-config VALUE       Backend config path relative to terraform dir. Default: backends/dev.hcl
  --var-file VALUE             tfvars path relative to terraform dir. Default: envs/dev/deploy.auto.tfvars.json
  --profile VALUE              AWS CLI profile. Default: stockbrief-dev
  --region VALUE               AWS region. Default: ap-northeast-2
  --alarm-emails-json VALUE    JSON array of operational alarm email recipients.
  --allow-empty-alarm-emails   Allow an empty alarm recipient list. Use only when notification removal is intentional.
  --skip-package               Skip Lambda package build before plan.
  -h, --help                   Show this help.
USAGE
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

terraform_dir="infra/terraform"
backend_config="backends/dev.hcl"
var_file="envs/dev/deploy.auto.tfvars.json"
profile="stockbrief-dev"
region="ap-northeast-2"
alarm_emails_json="${OPERATIONAL_ALARM_EMAILS_JSON:-}"
allow_empty_alarm_emails="false"
skip_package="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --terraform-dir)
      terraform_dir="$2"
      shift 2
      ;;
    --backend-config)
      backend_config="$2"
      shift 2
      ;;
    --var-file)
      var_file="$2"
      shift 2
      ;;
    --profile)
      profile="$2"
      shift 2
      ;;
    --region)
      region="$2"
      shift 2
      ;;
    --alarm-emails-json)
      alarm_emails_json="$2"
      shift 2
      ;;
    --allow-empty-alarm-emails)
      allow_empty_alarm_emails="true"
      shift
      ;;
    --skip-package)
      skip_package="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_command python3

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$terraform_dir" in
  /*)
    terraform_path="$terraform_dir"
    ;;
  *)
    terraform_path="${repo_root}/${terraform_dir}"
    ;;
esac

if [ ! -d "$terraform_path" ]; then
  echo "Terraform directory not found: ${terraform_path}" >&2
  exit 1
fi

if [ -z "$alarm_emails_json" ] && [ "$allow_empty_alarm_emails" != "true" ]; then
  cat >&2 <<'ERROR'
Missing OPERATIONAL_ALARM_EMAILS_JSON.

This guard refuses to run a dev plan without the operational alarm recipient
input because that can plan removal of the SNS topic, subscriptions, and alarm
actions that were created by deploy.

Set OPERATIONAL_ALARM_EMAILS_JSON='["ops@example.com"]' or pass
--alarm-emails-json. If notification removal is intentional, pass
--allow-empty-alarm-emails and document that choice in the PR.
ERROR
  exit 1
fi

require_command terraform

validated_alarm_emails="$(
  python3 - "$alarm_emails_json" "$allow_empty_alarm_emails" <<'PY'
import json
import sys

raw = sys.argv[1]
allow_empty = sys.argv[2] == "true"

if not raw:
    values = []
else:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid OPERATIONAL_ALARM_EMAILS_JSON: {exc}", file=sys.stderr)
        sys.exit(1)

if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
    print("OPERATIONAL_ALARM_EMAILS_JSON must be a JSON array of strings.", file=sys.stderr)
    sys.exit(1)

if not values and not allow_empty:
    print("At least one alarm email is required unless --allow-empty-alarm-emails is used.", file=sys.stderr)
    sys.exit(1)

print(json.dumps(values, ensure_ascii=False, separators=(",", ":")))
PY
)"

export AWS_PROFILE="$profile"
export AWS_REGION="$region"
export AWS_DEFAULT_REGION="$region"
export TF_VAR_operational_alarm_email_addresses="$validated_alarm_emails"

recipient_count="$(
  python3 - "$validated_alarm_emails" <<'PY'
import json
import sys

print(len(json.loads(sys.argv[1])))
PY
)"

echo "Using ${recipient_count} operational alarm email recipient(s)."

if [ "$skip_package" != "true" ]; then
  "${repo_root}/scripts/package_api_lambda.sh"
fi

terraform -chdir="$terraform_path" init \
  -reconfigure \
  -backend-config="$backend_config" \
  -input=false

set +e
terraform -chdir="$terraform_path" plan \
  -var-file="$var_file" \
  -detailed-exitcode \
  -no-color
plan_status="$?"
set -e

case "$plan_status" in
  0)
    echo "Terraform dev plan has no changes."
    exit 0
    ;;
  2)
    echo "Terraform dev plan has changes. Review and classify every item before apply." >&2
    exit 2
    ;;
  *)
    echo "Terraform dev plan failed with exit code ${plan_status}." >&2
    exit "$plan_status"
    ;;
esac
