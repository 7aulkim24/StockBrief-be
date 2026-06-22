#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Update the Terraform-managed external API Secrets Manager value.

Required environment variables:
  OPENDART_API_KEY
  NAVER_CLIENT_ID
  NAVER_CLIENT_SECRET

Optional environment variables:
  KRX_DATA_PATH

Examples:
  scripts/update_external_api_secret.sh --prompt --dry-run
  scripts/update_external_api_secret.sh --prompt

  scripts/update_external_api_secret.sh \
    --secret-id arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:stockbrief-dev/external-api

Options:
  --secret-id VALUE      Secrets Manager secret id or ARN. Default: terraform output external_api_secret_arn
  --terraform-dir VALUE  Terraform directory used to resolve the secret ARN. Default: infra/terraform
  --profile VALUE        AWS CLI profile. Default: stockbrief-dev
  --region VALUE         AWS region. Default: ap-northeast-2
  --prompt               Prompt for missing required credentials without echoing input.
  --dry-run              Validate inputs and build the temporary payload without calling AWS.
  -h, --help             Show this help.
USAGE
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

secret_id=""
terraform_dir="infra/terraform"
profile="stockbrief-dev"
region="ap-northeast-2"
dry_run="false"
prompt_for_missing="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --secret-id)
      secret_id="$2"
      shift 2
      ;;
    --terraform-dir)
      terraform_dir="$2"
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
    --prompt)
      prompt_for_missing="true"
      shift
      ;;
    --dry-run)
      dry_run="true"
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

require_command aws
require_command python3

if [ -z "$secret_id" ]; then
  require_command terraform
  secret_id="$(terraform -chdir="$terraform_dir" output -raw external_api_secret_arn)"
fi

if [ -z "$secret_id" ]; then
  echo "Unable to resolve external API secret id." >&2
  exit 1
fi

prompt_secret() {
  local key="$1"
  local value="${!key:-}"
  if [ -n "$value" ]; then
    return
  fi
  read -r -s -p "${key}: " value
  echo
  export "${key}=${value}"
}

if [ "$prompt_for_missing" = "true" ]; then
  prompt_secret OPENDART_API_KEY
  prompt_secret NAVER_CLIENT_ID
  prompt_secret NAVER_CLIENT_SECRET
fi

tmp_payload="$(mktemp "${TMPDIR:-/tmp}/stockbrief-external-api-secret.XXXXXX.json")"
cleanup() {
  rm -f "$tmp_payload"
}
trap cleanup EXIT

python3 - "$tmp_payload" <<'PY'
import json
import os
import sys

required_keys = ("OPENDART_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
missing = [key for key in required_keys if not os.environ.get(key)]
if missing:
    print(
        "Missing required environment variables: " + ", ".join(missing),
        file=sys.stderr,
    )
    sys.exit(1)

payload = {
    "OPENDART_API_KEY": os.environ["OPENDART_API_KEY"],
    "NAVER_CLIENT_ID": os.environ["NAVER_CLIENT_ID"],
    "NAVER_CLIENT_SECRET": os.environ["NAVER_CLIENT_SECRET"],
    "KRX_DATA_PATH": os.environ.get("KRX_DATA_PATH", ""),
}

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
PY

echo "External API secret payload validated for required keys."

if [ "$dry_run" = "true" ]; then
  echo "Dry run complete. AWS Secrets Manager was not updated."
  exit 0
fi

aws secretsmanager update-secret \
  --secret-id "$secret_id" \
  --secret-string "file://${tmp_payload}" \
  --profile "$profile" \
  --region "$region" >/dev/null

echo "External API secret updated. Metadata only:"
aws secretsmanager describe-secret \
  --secret-id "$secret_id" \
  --profile "$profile" \
  --region "$region" \
  --query '{ARN:ARN,Name:Name,LastChangedDate:LastChangedDate,VersionIdsToStages:VersionIdsToStages}' \
  --output json
