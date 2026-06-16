terraform {
  backend "s3" {
    bucket         = "stockbrief-terraform-state-420615923610-ap-northeast-2"
    key            = "stockbrief/dev/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "stockbrief-terraform-locks"
    encrypt        = true
  }
}
