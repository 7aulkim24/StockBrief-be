#!/usr/bin/env bash
set -euo pipefail

terraform_dir="infra/terraform"
var_file=""
region="${AWS_REGION:-ap-northeast-2}"

usage() {
  cat <<'USAGE'
Usage: scripts/check_agentcore_runtime_preflight.sh --var-file PATH [--terraform-dir DIR] [--region REGION]

Checks AgentCore Runtime CloudFormation type readiness before Terraform apply.
The check is a no-op when agentcore_runtime_enabled is false.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --terraform-dir)
      terraform_dir="${2:?--terraform-dir requires a value}"
      shift 2
      ;;
    --var-file)
      var_file="${2:?--var-file requires a value}"
      shift 2
      ;;
    --region)
      region="${2:?--region requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "$var_file" ]; then
  echo "--var-file is required." >&2
  usage >&2
  exit 2
fi

tfvars_path="${terraform_dir}/${var_file}"
if [ ! -f "$tfvars_path" ]; then
  echo "Terraform var file not found: ${tfvars_path}" >&2
  exit 1
fi

agentcore_state="$(
  python3 - "$tfvars_path" <<'PY'
import json
import sys
from pathlib import Path

tfvars = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
enabled = bool(tfvars.get("agentcore_runtime_enabled", False))
container_uri = str(tfvars.get("agentcore_runtime_container_uri", "")).strip()

if not enabled:
    print("disabled")
elif not container_uri:
    print("missing-container-uri")
else:
    print("enabled")
PY
)"

case "$agentcore_state" in
  disabled)
    echo "AgentCore Runtime preflight skipped: agentcore_runtime_enabled=false."
    exit 0
    ;;
  missing-container-uri)
    echo "AgentCore Runtime preflight failed: agentcore_runtime_enabled=true requires agentcore_runtime_container_uri." >&2
    exit 1
    ;;
  enabled)
    ;;
  *)
    echo "Unexpected AgentCore Runtime preflight state: ${agentcore_state}" >&2
    exit 1
    ;;
esac

for type_name in AWS::BedrockAgentCore::Runtime AWS::BedrockAgentCore::RuntimeEndpoint; do
  if ! output="$(
    aws cloudformation describe-type \
      --region "$region" \
      --type RESOURCE \
      --type-name "$type_name" 2>&1
  )"; then
    cat >&2 <<ERROR
AgentCore Runtime preflight failed for ${type_name}.

The deploy role could not read the CloudFormation resource type in ${region}.
Confirm that the target account/region supports AgentCore Runtime and that the
deploy role can access the CloudFormation type before running Terraform apply.

AWS CLI output:
${output}
ERROR
    exit 1
  fi
done

echo "AgentCore Runtime preflight passed: CloudFormation AgentCore resource types are readable in ${region}."
