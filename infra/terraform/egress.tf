locals {
  lambda_nat_egress_inputs_valid = (
    local.managed_networking_enabled &&
    var.lambda_nat_public_subnet_id != "" &&
    length(var.lambda_nat_route_subnet_ids) > 0 &&
    !contains(var.lambda_nat_route_subnet_ids, var.lambda_nat_public_subnet_id)
  )
  lambda_nat_egress_enabled = var.enable_lambda_nat_egress
}

resource "aws_eip" "lambda_nat" {
  count = local.lambda_nat_egress_enabled ? 1 : 0

  domain = "vpc"

  lifecycle {
    precondition {
      condition     = local.lambda_nat_egress_inputs_valid
      error_message = "enable_lambda_nat_egress requires vpc_id, db_subnet_ids, lambda_subnet_ids, lambda_nat_public_subnet_id, at least one lambda_nat_route_subnet_ids value, and a NAT public subnet that is not also routed through the NAT route table."
    }
  }

  tags = {
    Name        = "${local.name_prefix}-lambda-nat-eip"
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_nat_gateway" "lambda_egress" {
  count = local.lambda_nat_egress_enabled ? 1 : 0

  allocation_id = aws_eip.lambda_nat[0].id
  subnet_id     = var.lambda_nat_public_subnet_id

  lifecycle {
    precondition {
      condition     = local.lambda_nat_egress_inputs_valid
      error_message = "enable_lambda_nat_egress requires a public NAT subnet that is not included in lambda_nat_route_subnet_ids."
    }
  }

  tags = {
    Name        = "${local.name_prefix}-lambda-egress-nat"
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_route_table" "lambda_nat_egress" {
  count = local.lambda_nat_egress_enabled ? 1 : 0

  vpc_id = var.vpc_id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.lambda_egress[0].id
  }

  tags = {
    Name        = "${local.name_prefix}-lambda-nat-egress-rt"
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_route_table_association" "lambda_nat_egress" {
  for_each = local.lambda_nat_egress_enabled ? toset(var.lambda_nat_route_subnet_ids) : toset([])

  subnet_id      = each.value
  route_table_id = aws_route_table.lambda_nat_egress[0].id
}
