terraform {
  backend "s3" {
    bucket         = "stockbrief-terraform-state-560271561793-ap-northeast-2"
    key            = "stockbrief/dev/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "stockbrief-terraform-locks"
    encrypt        = true
  }
}
