output "runtime_arn" {
  value = local.effective_runtime_arn
}

output "runtime_id" {
  value = local.effective_runtime_id
}

output "runtime_endpoint_name" {
  value = local.effective_endpoint_name
}

output "runtime_role_arn" {
  value = try(aws_iam_role.runtime[0].arn, "")
}
