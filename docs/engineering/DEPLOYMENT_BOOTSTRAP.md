# Deployment Bootstrap

This document explains how to prepare a new AWS account or environment so the
backend can deploy from GitHub Actions without long-lived AWS access keys.

The current dev account is already bootstrapped:

- AWS account: `420615923610`
- Region: `ap-northeast-2`
- Terraform state bucket: `stockbrief-terraform-state-420615923610-ap-northeast-2`
- Terraform lock table: `stockbrief-terraform-locks`
- GitHub Actions deploy role: `stockbrief-dev-github-actions-deploy`
- Frontend Amplify app: console-managed, not Terraform-managed

## Why Bootstrap Is One-Time

GitHub Actions can deploy after it can assume an AWS IAM role through OIDC. The
first OIDC provider, IAM role, Terraform state bucket, and lock table cannot be
created by that role because it does not exist yet.

For a new AWS account, run the bootstrap script once with an administrator or
platform-admin AWS identity. After that, pushes to `main` can deploy through
GitHub Actions.

AWS recommends using an IAM OIDC provider and short-term role credentials for
GitHub Actions instead of storing long-lived IAM user keys. The provider URL must
be lowercase: `https://token.actions.githubusercontent.com`, and the audience is
`sts.amazonaws.com`.

## Prerequisites

- AWS CLI authenticated to the target AWS account.
- GitHub CLI authenticated with permission to write repository variables.
- Permission to create or update IAM OIDC providers, IAM roles, S3 buckets, and
  DynamoDB tables in the target AWS account.
- Permission to set variables on `80-hours-a-week/StockBrief-be`.

Check the active AWS account before running:

```bash
aws sts get-caller-identity
```

Check GitHub CLI authentication:

```bash
gh auth status -h github.com
```

## Bootstrap Command

Run from the backend repository root:

```bash
scripts/bootstrap_github_oidc.sh \
  --environment dev \
  --region ap-northeast-2 \
  --github-owner 80-hours-a-week \
  --github-repo StockBrief-be \
  --alarm-emails-json '["ops@example.com"]'
```

The script creates or updates:

- S3 remote Terraform state bucket.
- DynamoDB Terraform lock table.
- IAM OIDC provider for GitHub Actions.
- IAM deploy role scoped to `80-hours-a-week/StockBrief-be` `main`.
- GitHub repository variables:
  - `AWS_DEV_DEPLOY_ROLE_ARN`
  - `OPERATIONAL_ALARM_EMAILS_JSON`

The deploy role policy is intentionally broad enough for the current dev
Terraform deployment. Tighten it after the deployment surface stabilizes.

## After Bootstrap

Make sure Terraform uses the state backend printed by the script:

```hcl
terraform {
  backend "s3" {
    bucket         = "stockbrief-terraform-state-<account-id>-<region>"
    key            = "stockbrief/dev/terraform.tfstate"
    region         = "<region>"
    dynamodb_table = "stockbrief-terraform-locks"
    encrypt        = true
  }
}
```

Then check the dev deploy variable file:

```text
infra/terraform/envs/dev/deploy.auto.tfvars.json
```

Confirm these values match the target AWS account:

- `aws_region`
- `vpc_id`
- `db_subnet_ids`
- `lambda_subnet_ids`
- `cors_allowed_origins`
- `cognito_callback_urls`
- `cognito_logout_urls`
- `cognito_hosted_ui_domain_prefix`

For the current approach, keep this value:

```json
"enable_amplify": false
```

Amplify Hosting is managed from the AWS console. Backend resources, RDS, Lambda,
API Gateway, Cognito, Secrets Manager, and alarms are managed by Terraform.

## Deployment Flow After Bootstrap

1. Merge backend changes into `main`.
2. GitHub Actions runs `backend-dev-deploy`.
3. The workflow assumes `AWS_DEV_DEPLOY_ROLE_ARN` through OIDC.
4. The workflow packages Lambda, runs Terraform plan, and applies the dev stack.
5. Update Secrets Manager values outside git when keys or DB connection values
   change.

## New Environment Checklist

- Run the bootstrap script once in the target AWS account.
- Update `infra/terraform/backend.tf` for that account and region.
- Update `infra/terraform/envs/dev/deploy.auto.tfvars.json` for that network and
  frontend URL.
- Confirm SNS alert email subscriptions after Terraform creates them.
- Fill secret values in AWS Secrets Manager. Do not commit secret values.
- Keep FE Amplify app setup in the console unless the team decides to manage
  Amplify with Terraform later.
