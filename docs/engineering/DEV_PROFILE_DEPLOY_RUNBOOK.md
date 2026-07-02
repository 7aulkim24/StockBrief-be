# Dev Profile Deploy Runbook

`dev` 또는 `dev-*` GitHub Actions 배포를 안전하게 다시 실행하기 위한 복사/붙여넣기용 절차입니다.
개인별 dev profile은 `TARGET_ENV`만 다르게 두고 같은 흐름을 사용합니다.

목표:

- GitHub OIDC deploy role 권한 최신화
- `TFVARS_JSON`이 기존 RDS/VPC 리소스를 삭제하지 않도록 복구
- AgentCore Runtime preflight 통과
- `apply=false` plan 확인 후 `apply=true` 실행

## 0. 기본값

```bash
cd /path/to/StockBrief-be

export TARGET_ENV="dev-<name>"
export AWS_REGION="${AWS_REGION:-ap-northeast-2}"
export REPO="${REPO:-80-hours-a-week/StockBrief-be}"
export PREFIX="stockbrief-${TARGET_ENV}"
export ROLE_NAME="${PREFIX}-github-actions-deploy"
export POLICY_NAME="${PREFIX}-deploy-access"
export AWS_ACCOUNT_ID="$(
  aws sts get-caller-identity \
    --query Account \
    --output text
)"
```

```bash
gh auth status
aws sts get-caller-identity
```

`TARGET_ENV`는 `dev` 또는 `dev-*`만 사용합니다. 다른 사람이 같은 절차를 실행할 때는 자기 profile 이름으로 `TARGET_ENV`만 바꾸고, 아래 조회 명령으로 AWS 리소스 값을 다시 채웁니다.

## 1. Bootstrap 재실행

deploy role policy, OIDC trust policy, GitHub Environment 변수를 최신화합니다.

```bash
scripts/bootstrap_github_oidc.sh \
  --environment "$TARGET_ENV" \
  --region "$AWS_REGION" \
  --github-owner 80-hours-a-week \
  --github-repo StockBrief-be \
  --alarm-emails-json '["REPLACE_WITH_ALERT_EMAIL"]'
```

`TF_BACKEND_CONFIG_HCL`/`TFVARS_JSON`를 새로 생성해야 하는 초기 profile 세팅 때만 `--write-deploy-profile-vars`를 붙입니다. 이미 운영 중인 profile에서는 기존 tfvars를 빈 네트워크 값으로 덮을 수 있으므로, 먼저 3~6장을 따라 현재 리소스 값을 확인합니다.

## 2. 권한 확인

```bash
aws iam get-role --role-name "$ROLE_NAME" \
  --query 'Role.Arn' \
  --output text
```

```bash
aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query 'PolicyDocument.Statement[].Action' \
  --output json | jq .
```

아래 권한이 보여야 합니다.

```text
cloudformation:DescribeType
ecr:DescribeImages
ec2:CreateSubnet
ec2:ModifySubnetAttribute
ec2:CreateNatGateway
ec2:CreateRoute
bedrock-agentcore:CreateAgentRuntime
bedrock-agentcore:CreateAgentRuntimeEndpoint
bedrock-agentcore:GetAgentRuntime
bedrock-agentcore:GetAgentRuntimeEndpoint
bedrock-agentcore:UpdateAgentRuntime
bedrock-agentcore:DeleteAgentRuntime
```

OIDC subject도 확인합니다.

```bash
aws iam get-role \
  --role-name "$ROLE_NAME" \
  --query 'Role.AssumeRolePolicyDocument' \
  --output json | jq .
```

아래 값이 trust policy에 있어야 합니다.

```text
repo:80-hours-a-week/StockBrief-be:environment:<TARGET_ENV>
```

## 3. GitHub Environment 변수 확인

```bash
gh variable list --repo "$REPO" --env "$TARGET_ENV"
```

필수 변수:

```text
AWS_<TARGET_ENV_WITH_DASHES_REPLACED_BY_UNDERSCORES>_DEPLOY_ROLE_ARN
OPERATIONAL_ALARM_EMAILS_JSON
TF_BACKEND_CONFIG_HCL
TFVARS_JSON
```

```bash
gh variable get TF_BACKEND_CONFIG_HCL --repo "$REPO" --env "$TARGET_ENV"
gh variable get TFVARS_JSON --repo "$REPO" --env "$TARGET_ENV" | jq .
```

## 4. 기존 AWS 리소스 조회

현재 profile에 이미 배포된 리소스가 있으면 AWS에서 다시 조회합니다.

```bash
export VPC_ID="$(
  aws rds describe-db-subnet-groups \
    --db-subnet-group-name "${PREFIX}-postgres" \
    --region "$AWS_REGION" \
    --query 'DBSubnetGroups[0].VpcId' \
    --output text
)"

export DB_SUBNET_IDS_JSON="$(
  aws rds describe-db-subnet-groups \
    --db-subnet-group-name "${PREFIX}-postgres" \
    --region "$AWS_REGION" \
    --query 'DBSubnetGroups[0].Subnets[].SubnetIdentifier' \
    --output json
)"

export LAMBDA_SUBNET_IDS_JSON="$(
  aws lambda get-function-configuration \
    --function-name "${PREFIX}-api" \
    --region "$AWS_REGION" \
    --query 'VpcConfig.SubnetIds' \
    --output json
)"

export S3_VPCE_ROUTE_TABLE_IDS_JSON="$(
  aws ec2 describe-vpc-endpoints \
    --region "$AWS_REGION" \
    --filters \
      "Name=vpc-id,Values=${VPC_ID}" \
      "Name=service-name,Values=com.amazonaws.${AWS_REGION}.s3" \
      "Name=vpc-endpoint-type,Values=Gateway" \
    --query 'VpcEndpoints[0].RouteTableIds' \
    --output json
)"
```

초기 profile이라 RDS/Lambda가 아직 없으면 위 조회가 실패할 수 있습니다. 그 경우에는 사용할 VPC/subnet/route table을 직접 정해 같은 변수에 JSON으로 넣습니다.

```bash
export VPC_ID="<existing-vpc-id>"
export DB_SUBNET_IDS_JSON='["<db-subnet-a>","<db-subnet-b>"]'
export LAMBDA_SUBNET_IDS_JSON='["<lambda-subnet-a>","<lambda-subnet-b>"]'
export S3_VPCE_ROUTE_TABLE_IDS_JSON='["<route-table-id>"]'
```

값 확인:

```bash
printf 'VPC_ID=%s\n' "$VPC_ID"
printf 'DB_SUBNET_IDS=%s\n' "$DB_SUBNET_IDS_JSON"
printf 'LAMBDA_SUBNET_IDS=%s\n' "$LAMBDA_SUBNET_IDS_JSON"
printf 'S3_VPCE_ROUTE_TABLE_IDS=%s\n' "$S3_VPCE_ROUTE_TABLE_IDS_JSON"
```

## 5. NAT 선택

선택 기준:

- 현재 목적이 `destroy` 방지와 AgentCore PUBLIC 배포 확인이면 NAT 없이 진행해도 됩니다.
- VPC Lambda가 외부 HTTPS, Cognito JWKS, 외부 API, Bedrock, AgentCore 호출을 안정적으로 해야 하면 NAT를 생성합니다.
- NAT Gateway는 시간당 비용과 데이터 처리 비용이 발생합니다.

## 6A. NAT 없이 TFVARS_JSON 복구

기존 RDS/VPC 리소스 삭제를 막는 최소 복구입니다.

```bash
gh variable get TFVARS_JSON \
  --repo "$REPO" \
  --env "$TARGET_ENV" > "/tmp/${TARGET_ENV}.tfvars.before.json"

jq \
  --arg vpc_id "$VPC_ID" \
  --argjson db_subnet_ids "$DB_SUBNET_IDS_JSON" \
  --argjson lambda_subnet_ids "$LAMBDA_SUBNET_IDS_JSON" \
  --argjson vpce_route_table_ids "$S3_VPCE_ROUTE_TABLE_IDS_JSON" \
  '
  .environment = env.TARGET_ENV
  | .vpc_id = $vpc_id
  | .db_subnet_ids = $db_subnet_ids
  | .lambda_subnet_ids = $lambda_subnet_ids
  | .vpc_endpoint_route_table_ids = $vpce_route_table_ids
  | .enable_lambda_nat_egress = false
  | .lambda_nat_create_public_subnet = false
  | .lambda_nat_public_subnet_id = ""
  | .lambda_nat_public_subnet_cidr_block = ""
  | .lambda_nat_public_subnet_availability_zone = ""
  | .lambda_nat_internet_gateway_id = ""
  | .lambda_nat_create_internet_gateway = false
  | .lambda_nat_route_subnet_ids = []
  ' "/tmp/${TARGET_ENV}.tfvars.before.json" > "/tmp/${TARGET_ENV}.tfvars.after.json"

jq . "/tmp/${TARGET_ENV}.tfvars.after.json"
```

업데이트:

```bash
gh variable set TFVARS_JSON \
  --repo "$REPO" \
  --env "$TARGET_ENV" \
  --body "$(cat "/tmp/${TARGET_ENV}.tfvars.after.json")"
```

## 6B. NAT 생성 포함 TFVARS_JSON 복구

VPC Lambda의 외부 egress가 필요할 때 사용합니다.

먼저 VPC CIDR와 기존 subnet CIDR를 확인합니다.

```bash
aws ec2 describe-vpcs \
  --vpc-ids "$VPC_ID" \
  --region "$AWS_REGION" \
  --query 'Vpcs[0].CidrBlock' \
  --output text

aws ec2 describe-subnets \
  --region "$AWS_REGION" \
  --filters "Name=vpc-id,Values=${VPC_ID}" \
  --query 'Subnets[].{SubnetId:SubnetId,AZ:AvailabilityZone,Cidr:CidrBlock,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table
```

Public subnet CIDR는 VPC CIDR 안에 있어야 하며, 기존 subnet CIDR와 겹치지 않아야 합니다. 예를 들어 VPC CIDR가 `172.31.0.0/16`이고 기존 subnet이 `172.31.0.0/20`, `172.31.16.0/20`처럼 앞쪽 대역을 쓰고 있다면 근처의 미사용 대역인 `172.31.100.0/24`를 후보로 둘 수 있습니다. 실제 적용 전에는 위 subnet 목록과 겹치지 않는지 확인합니다.

```bash
export NAT_PUBLIC_SUBNET_CIDR="172.31.100.0/24"
export NAT_PUBLIC_SUBNET_AZ="${AWS_REGION}a"
```

기존 VPC에 연결된 Internet Gateway ID도 함께 조회합니다. `lambda_nat_create_public_subnet=true`일 때는 `lambda_nat_create_internet_gateway=true` 또는 `lambda_nat_internet_gateway_id`가 필요합니다.

```bash
export NAT_INTERNET_GATEWAY_ID="$(
  aws ec2 describe-internet-gateways \
    --region "$AWS_REGION" \
    --filters "Name=attachment.vpc-id,Values=${VPC_ID}" \
    --query 'InternetGateways[0].InternetGatewayId' \
    --output text
)"

printf 'NAT_INTERNET_GATEWAY_ID=%s\n' "$NAT_INTERNET_GATEWAY_ID"
```

```bash
gh variable get TFVARS_JSON \
  --repo "$REPO" \
  --env "$TARGET_ENV" > "/tmp/${TARGET_ENV}.tfvars.before.json"

jq \
  --arg vpc_id "$VPC_ID" \
  --argjson db_subnet_ids "$DB_SUBNET_IDS_JSON" \
  --argjson lambda_subnet_ids "$LAMBDA_SUBNET_IDS_JSON" \
  --argjson vpce_route_table_ids "$S3_VPCE_ROUTE_TABLE_IDS_JSON" \
  --arg nat_public_cidr "$NAT_PUBLIC_SUBNET_CIDR" \
  --arg nat_public_az "$NAT_PUBLIC_SUBNET_AZ" \
  --arg nat_internet_gateway_id "$NAT_INTERNET_GATEWAY_ID" \
  '
  .environment = env.TARGET_ENV
  | .vpc_id = $vpc_id
  | .db_subnet_ids = $db_subnet_ids
  | .lambda_subnet_ids = $lambda_subnet_ids
  | .vpc_endpoint_route_table_ids = $vpce_route_table_ids
  | .enable_lambda_nat_egress = true
  | .lambda_nat_create_public_subnet = true
  | .lambda_nat_public_subnet_id = ""
  | .lambda_nat_public_subnet_cidr_block = $nat_public_cidr
  | .lambda_nat_public_subnet_availability_zone = $nat_public_az
  | .lambda_nat_internet_gateway_id = $nat_internet_gateway_id
  | .lambda_nat_create_internet_gateway = false
  | .lambda_nat_route_subnet_ids = $lambda_subnet_ids
  ' "/tmp/${TARGET_ENV}.tfvars.before.json" > "/tmp/${TARGET_ENV}.tfvars.after.json"

jq . "/tmp/${TARGET_ENV}.tfvars.after.json"
```

업데이트:

```bash
gh variable set TFVARS_JSON \
  --repo "$REPO" \
  --env "$TARGET_ENV" \
  --body "$(cat "/tmp/${TARGET_ENV}.tfvars.after.json")"
```

## 7. AgentCore ECR 확인

profile별로 사용할 ECR 이미지 태그를 명시합니다.

```bash
export AGENTCORE_ECR_REPOSITORY="${AGENTCORE_ECR_REPOSITORY:-stockbrief-agent}"
export AGENTCORE_IMAGE_TAG="<image-tag>"
export AGENTCORE_CONTAINER_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${AGENTCORE_ECR_REPOSITORY}:${AGENTCORE_IMAGE_TAG}"
```

ECR 이미지 확인:

```bash
aws ecr describe-images \
  --repository-name "$AGENTCORE_ECR_REPOSITORY" \
  --image-ids imageTag="$AGENTCORE_IMAGE_TAG" \
  --region "$AWS_REGION"
```

repository가 없으면:

```bash
aws ecr create-repository \
  --repository-name "$AGENTCORE_ECR_REPOSITORY" \
  --region "$AWS_REGION"
```

런타임을 켤 profile만 `TFVARS_JSON`에 반영합니다.

```bash
jq \
  --arg container_uri "$AGENTCORE_CONTAINER_URI" \
  '
  .agentcore_runtime_enabled = true
  | .agentcore_runtime_container_uri = $container_uri
  | .agentcore_network_mode = "PUBLIC"
  ' "/tmp/${TARGET_ENV}.tfvars.after.json" > "/tmp/${TARGET_ENV}.tfvars.agentcore.json"

mv "/tmp/${TARGET_ENV}.tfvars.agentcore.json" "/tmp/${TARGET_ENV}.tfvars.after.json"
jq . "/tmp/${TARGET_ENV}.tfvars.after.json"
```

## 8. Preflight

GitHub Actions에서는 runner가 `TFVARS_JSON`를 파일로 생성합니다. 로컬에서 확인하려면 같은 파일을 임시로 만듭니다.

```bash
mkdir -p "infra/terraform/envs/${TARGET_ENV}"
cp "/tmp/${TARGET_ENV}.tfvars.after.json" "infra/terraform/envs/${TARGET_ENV}/deploy.auto.tfvars.json"

scripts/check_agentcore_runtime_preflight.sh \
  --terraform-dir infra/terraform \
  --var-file "envs/${TARGET_ENV}/deploy.auto.tfvars.json" \
  --region "$AWS_REGION"
```

## 9. Runtime 실행 역할 정책 확인

Terraform이 만드는 runtime role trust policy에는 AWS 문서 예시처럼 `aws:SourceAccount`와 `aws:SourceArn` 조건이 들어가야 합니다.

```bash
aws iam get-role \
  --role-name "${PREFIX}-agentcore-runtime-role" \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition' \
  --output json | jq .
```

기대 형태:

```json
{
  "StringEquals": {
    "aws:SourceAccount": "<aws-account-id>"
  },
  "ArnLike": {
    "aws:SourceArn": "arn:aws:bedrock-agentcore:<region>:<aws-account-id>:*"
  }
}
```

실행 역할 inline policy에는 logs, X-Ray, CloudWatch metric, workload token, Bedrock invoke 권한이 있어야 합니다.

```bash
aws iam get-role-policy \
  --role-name "${PREFIX}-agentcore-runtime-role" \
  --policy-name "${PREFIX}-agentcore-runtime" \
  --query 'PolicyDocument.Statement[].Action' \
  --output json | jq .
```

## 10. Plan-only 실행

```bash
gh workflow run backend-dev-deploy.yml \
  --repo "$REPO" \
  -f target_env="$TARGET_ENV" \
  -f apply=false
```

최근 run 확인:

```bash
gh run list \
  --repo "$REPO" \
  --workflow backend-dev-deploy.yml \
  --limit 5
```

로그에서 destroy 확인:

```bash
gh run view <RUN_ID> \
  --repo "$REPO" \
  --log | rg "Plan:|will be destroyed|to destroy|tainted|replaced|lambda_nat|nat|agentcore|AgentCore"
```

안전 기준:

```text
0 to destroy
```

`will be destroyed` 또는 `N to destroy`가 보이면 `apply=true`를 실행하지 않습니다.

`module.agentcore_runtime.aws_cloudformation_stack.runtime[0] is tainted, so must be replaced`가 보이면 AgentCore CloudFormation stack이 Terraform state에서 tainted 처리된 상태입니다. stack이 실제로 정상인지 먼저 확인합니다.

```bash
aws cloudformation describe-stacks \
  --stack-name "${PREFIX}-agentcore-runtime" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].{Status:StackStatus,StackId:StackId,Outputs:Outputs}' \
  --output json
```

`StackStatus`가 `CREATE_COMPLETE` 또는 `UPDATE_COMPLETE`이고 강제 재생성이 목적이 아니면 taint만 해제한 뒤 plan-only를 다시 실행합니다.

```bash
cd infra/terraform

terraform init \
  -backend-config="backends/${TARGET_ENV}.hcl" \
  -input=false

terraform state show 'module.agentcore_runtime.aws_cloudformation_stack.runtime[0]'
terraform untaint 'module.agentcore_runtime.aws_cloudformation_stack.runtime[0]'
```

다시 `apply=false`를 실행해 `0 to destroy`가 확인될 때만 다음 단계로 진행합니다. stack 상태가 `ROLLBACK_*`, `*_FAILED`, `DELETE_*`이면 untaint하지 말고 CloudFormation 이벤트와 AgentCore Runtime 상태를 먼저 확인합니다.

## 11. Apply

plan-only에서 삭제가 없고 생성/수정 내역을 검토한 뒤 실행합니다.

```bash
gh workflow run backend-dev-deploy.yml \
  --repo "$REPO" \
  -f target_env="$TARGET_ENV" \
  -f apply=true
```

## 12. 배포 후 확인

Terraform output 확인:

```bash
cd infra/terraform

terraform init \
  -backend-config="backends/${TARGET_ENV}.hcl" \
  -input=false

terraform output
```

AgentCore stack 확인:

```bash
aws cloudformation describe-stacks \
  --stack-name "${PREFIX}-agentcore-runtime" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}'
```

API health 확인:

```bash
export API_BASE_URL="<terraform-output-api-base-url>"

curl -i "${API_BASE_URL}/v1/health"
```

## 13. 실패 시 빠른 판별

권한 문제:

```bash
aws iam get-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --query 'PolicyDocument' \
  --output json | jq .
```

Terraform이 기존 RDS/VPC를 삭제하려는 경우:

```bash
gh variable get TFVARS_JSON \
  --repo "$REPO" \
  --env "$TARGET_ENV" | jq '.vpc_id,.db_subnet_ids,.lambda_subnet_ids,.vpc_endpoint_route_table_ids'
```

AgentCore type 접근 문제:

```bash
aws cloudformation describe-type \
  --type RESOURCE \
  --type-name AWS::BedrockAgentCore::Runtime \
  --region "$AWS_REGION"
```

ECR 이미지 문제:

```bash
aws ecr describe-images \
  --repository-name "$AGENTCORE_ECR_REPOSITORY" \
  --image-ids imageTag="$AGENTCORE_IMAGE_TAG" \
  --region "$AWS_REGION"
```
