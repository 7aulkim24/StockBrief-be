#!/usr/bin/env python3
"""Resolve backend-dev-deploy profile files and GitHub Actions outputs."""

from __future__ import annotations

import json
import os
import re
import sys

from validate_tfvars import TfvarsValidationError, load_validated_tfvars_json


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _validate_target_env(target_env: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", target_env))


def main() -> int:
    target_env = os.environ["TARGET_ENV"]
    if not _validate_target_env(target_env):
        return _fail(f"Invalid target_env: {target_env}")
    if target_env != "dev" and not target_env.startswith("dev-"):
        return _fail(
            "backend-dev-deploy only accepts dev or dev-* target_env values. "
            f"Use a dedicated workflow for {target_env}."
        )

    variables = json.loads(os.environ["GITHUB_VARIABLES_JSON"])
    env_key = f"AWS_{target_env.upper().replace('-', '_')}_DEPLOY_ROLE_ARN"
    role_arn = variables.get(env_key)
    if not role_arn and target_env == "dev":
        role_arn = variables.get("AWS_DEV_DEPLOY_ROLE_ARN")
    if not role_arn:
        return _fail(f"Missing GitHub variable {env_key}.")

    tf_var_file = f"envs/{target_env}/deploy.auto.tfvars.json"
    tf_backend_config = f"backends/{target_env}.hcl"
    tf_var_path = os.path.join(os.environ["TF_DIR"], tf_var_file)
    tf_backend_path = os.path.join(os.environ["TF_DIR"], tf_backend_config)

    if not os.path.isfile(tf_backend_path) or not os.path.isfile(tf_var_path):
        backend_config_hcl = variables.get("TF_BACKEND_CONFIG_HCL")
        tfvars_json = variables.get("TFVARS_JSON")
        if not backend_config_hcl or not tfvars_json:
            return _fail(
                "Missing deploy profile file(s), and GitHub Environment variables "
                "TF_BACKEND_CONFIG_HCL/TFVARS_JSON are not both set."
            )

        if "bucket" not in backend_config_hcl or "key" not in backend_config_hcl:
            return _fail("TF_BACKEND_CONFIG_HCL must include Terraform backend bucket and key.")

        try:
            parsed_tfvars = load_validated_tfvars_json(tfvars_json, target_env)
        except TfvarsValidationError as exc:
            return _fail(str(exc))

        os.makedirs(os.path.dirname(tf_backend_path), exist_ok=True)
        os.makedirs(os.path.dirname(tf_var_path), exist_ok=True)
        with open(tf_backend_path, "w", encoding="utf-8") as backend_file:
            backend_file.write(backend_config_hcl.rstrip() + "\n")
        with open(tf_var_path, "w", encoding="utf-8") as tfvars_file:
            json.dump(parsed_tfvars, tfvars_file, ensure_ascii=False, indent=2)
            tfvars_file.write("\n")

    required_files = [
        tf_var_path,
        tf_backend_path,
    ]
    missing_files = [path for path in required_files if not os.path.isfile(path)]
    if missing_files:
        print("Missing deploy profile file(s):", file=sys.stderr)
        for path in missing_files:
            print(f"- {path}", file=sys.stderr)
        return 1

    print(f"target_env={target_env}")
    print(f"tf_var_file={tf_var_file}")
    print(f"tf_backend_config={tf_backend_config}")
    print(f"deploy_role_arn={role_arn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
