variable "project" {
  description = "Project name used for resource naming."
  type        = string
  default     = "stockbrief"
}

variable "environment" {
  description = "Deployment environment. MVP prioritizes dev."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of dev, staging, or prod."
  }
}

variable "aws_region" {
  description = "AWS region for StockBrief MVP resources."
  type        = string
  default     = "ap-northeast-2"
}

variable "api_lambda_package_path" {
  description = "Path to the packaged FastAPI/Mangum Lambda zip."
  type        = string
  default     = "../../dist/stockbrief-api-lambda.zip"
}

variable "api_lambda_runtime" {
  description = "Python runtime for Lambda."
  type        = string
  default     = "python3.13"
}

variable "api_lambda_timeout_seconds" {
  description = "Lambda timeout for API handler."
  type        = number
  default     = 30
}

variable "api_lambda_memory_mb" {
  description = "Lambda memory size for API handler."
  type        = number
  default     = 512
}

variable "cors_allowed_origins" {
  description = "Comma-separated CORS origins passed to the backend."
  type        = string
  default     = "http://localhost:3000,http://127.0.0.1:3000"
}

variable "amplify_repository_url" {
  description = "Repository URL for Amplify app connection. Placeholder for MVP."
  type        = string
  default     = "https://github.com/example/stockbrief"
}

variable "amplify_branch_name" {
  description = "Amplify branch to deploy."
  type        = string
  default     = "main"
}

variable "cognito_callback_urls" {
  description = "Allowed Cognito Hosted UI callback URLs. The first value is passed to Amplify as NEXT_PUBLIC_COGNITO_REDIRECT_URI."
  type        = list(string)
  default     = ["http://localhost:3000/auth/callback"]
}

variable "cognito_logout_urls" {
  description = "Allowed Cognito Hosted UI logout URLs."
  type        = list(string)
  default     = ["http://localhost:3000/account"]
}

variable "cognito_hosted_ui_domain_prefix" {
  description = "Optional globally unique Cognito Hosted UI domain prefix. Leave empty to skip domain creation in early skeleton planning."
  type        = string
  default     = ""
}

variable "db_name" {
  description = "RDS database name."
  type        = string
  default     = "stockbrief"
}

variable "db_instance_class" {
  description = "RDS instance class for MVP dev."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "RDS allocated storage in GB."
  type        = number
  default     = 20
}

variable "db_subnet_ids" {
  description = "Private subnet IDs for RDS. Placeholder until VPC module is added."
  type        = list(string)
  default     = []
}

variable "db_security_group_ids" {
  description = "Security group IDs allowed to reach RDS. Placeholder until VPC module is added."
  type        = list(string)
  default     = []
}

variable "lambda_subnet_ids" {
  description = "Private subnet IDs for Lambda VPC access. Placeholder until VPC module is added."
  type        = list(string)
  default     = []
}

variable "lambda_security_group_ids" {
  description = "Security group IDs for Lambda. Placeholder until VPC module is added."
  type        = list(string)
  default     = []
}

variable "agentcore_runtime_enabled" {
  description = "Whether to create the AgentCore Runtime CloudFormation stack. Requires agentcore_runtime_container_uri."
  type        = bool
  default     = false
}

variable "agentcore_runtime_container_uri" {
  description = "ECR image URI for the StockBrief AgentCore Runtime container."
  type        = string
  default     = ""
}

variable "agentcore_network_mode" {
  description = "AgentCore Runtime network mode. Use PUBLIC for the first PoC, VPC when private data access is required."
  type        = string
  default     = "PUBLIC"

  validation {
    condition     = contains(["PUBLIC", "VPC"], var.agentcore_network_mode)
    error_message = "agentcore_network_mode must be PUBLIC or VPC."
  }
}
