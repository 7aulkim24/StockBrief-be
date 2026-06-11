variable "name_prefix" {
  type = string
}

variable "repository_url" {
  type = string
}

variable "access_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "branch_name" {
  type = string
}

variable "next_public_api_base" {
  type = string
}

variable "cognito_region" {
  type = string
}

variable "cognito_user_pool_id" {
  type = string
}

variable "cognito_app_client_id" {
  type = string
}

variable "cognito_hosted_ui_domain" {
  type = string
}

variable "cognito_redirect_uri" {
  type = string
}
