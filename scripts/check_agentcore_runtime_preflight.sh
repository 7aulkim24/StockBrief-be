#!/usr/bin/env bash
set -euo pipefail

terraform_dir="infra/terraform"
var_file=""
region="${AWS_REGION:-ap-northeast-2}"

usage() {
  cat <<'USAGE'
Usage: scripts/check_agentcore_runtime_preflight.sh --var-file PATH [--terraform-dir DIR] [--region REGION]

Checks AgentCore Runtime direct deploy prerequisites before Terraform apply.
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
import re
from pathlib import Path

tfvars = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
enabled = bool(tfvars.get("agentcore_runtime_enabled", False))
container_uri = str(tfvars.get("agentcore_runtime_container_uri", "")).strip()

if not enabled:
    print("disabled")
elif not container_uri:
    print("missing-container-uri")
else:
    match = re.fullmatch(
        r"(?P<registry>[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com)/"
        r"(?P<repository>[^:@]+)(?::(?P<tag>[^:@]+))?(?:@(?P<digest>sha256:[0-9a-f]+))?",
        container_uri,
    )
    if not match or not (match.group("tag") or match.group("digest")):
        print("invalid-container-uri")
    else:
        print(
            "enabled\t"
            + match.group("repository")
            + "\t"
            + (match.group("tag") or "")
            + "\t"
            + (match.group("digest") or "")
        )
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
  invalid-container-uri)
    echo "AgentCore Runtime preflight failed: agentcore_runtime_container_uri must be an ECR image URI." >&2
    exit 1
    ;;
  enabled$'\t'*)
    repository="$(printf '%s' "$agentcore_state" | cut -f2)"
    tag="$(printf '%s' "$agentcore_state" | cut -f3)"
    digest="$(printf '%s' "$agentcore_state" | cut -f4)"
    image_id_args=()
    if [ -n "$digest" ]; then
      image_id_args=(imageDigest="$digest")
    else
      image_id_args=(imageTag="$tag")
    fi
    if ! output="$(
      aws ecr describe-images \
        --repository-name "$repository" \
        --image-ids "${image_id_args[@]}" \
        --region "$region" 2>&1
    )"; then
      cat >&2 <<ERROR
AgentCore Runtime preflight failed for ${repository}.

The deploy role could not read the configured ECR image in ${region}.
Push the AgentCore image first and confirm the repository/tag in TFVARS_JSON.

AWS CLI output:
${output}
ERROR
      exit 1
    fi
    echo "AgentCore Runtime preflight passed: ECR image is readable in ${region}."
    exit 0
    ;;
  *)
    echo "Unexpected AgentCore Runtime preflight state: ${agentcore_state}" >&2
    exit 1
    ;;
esac
