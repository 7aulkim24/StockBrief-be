resource "aws_amplify_app" "web" {
  name         = "${var.name_prefix}-web"
  repository   = var.repository_url
  access_token = var.access_token == "" ? null : var.access_token

  platform = "WEB_COMPUTE"

  environment_variables = {
    NEXT_PUBLIC_API_BASE_URL             = "${var.next_public_api_base}/v1"
    NEXT_PUBLIC_APP_NAME                 = "StockBrief"
    NEXT_PUBLIC_COGNITO_REGION           = var.cognito_region
    NEXT_PUBLIC_COGNITO_USER_POOL_ID     = var.cognito_user_pool_id
    NEXT_PUBLIC_COGNITO_APP_CLIENT_ID    = var.cognito_app_client_id
    NEXT_PUBLIC_COGNITO_HOSTED_UI_DOMAIN = var.cognito_hosted_ui_domain
    NEXT_PUBLIC_COGNITO_REDIRECT_URI     = var.cognito_redirect_uri
    _NODE_VERSION                        = "24"
  }

  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: .
        frontend:
          phases:
            preBuild:
              commands:
                - npm ci
            build:
              commands:
                - npm run build
          artifacts:
            baseDirectory: .next
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
  YAML
}

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.web.id
  branch_name = var.branch_name
  framework   = "Next.js - SSR"
  stage       = "DEVELOPMENT"
}
