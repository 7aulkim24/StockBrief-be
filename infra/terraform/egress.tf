locals {
  lambda_nat_managed_public_subnet_enabled = var.enable_lambda_nat_egress && var.lambda_nat_create_public_subnet
  lambda_nat_discover_internet_gateway = (
    local.lambda_nat_managed_public_subnet_enabled &&
    !var.lambda_nat_create_internet_gateway &&
    var.lambda_nat_internet_gateway_id == ""
  )
  effective_lambda_nat_internet_gateway_id = local.lambda_nat_managed_public_subnet_enabled ? (
    var.lambda_nat_create_internet_gateway ? aws_internet_gateway.lambda_nat[0].id : (
      var.lambda_nat_internet_gateway_id != "" ? var.lambda_nat_internet_gateway_id : data.aws_internet_gateway.lambda_nat[0].id
    )
  ) : ""
  effective_lambda_nat_public_subnet_id = local.lambda_nat_managed_public_subnet_enabled ? aws_subnet.lambda_nat_public[0].id : var.lambda_nat_public_subnet_id
  lambda_nat_egress_inputs_valid = (
    local.managed_networking_enabled &&
    local.effective_lambda_nat_public_subnet_id != "" &&
    length(var.lambda_nat_route_subnet_ids) > 0 &&
    !contains(var.lambda_nat_route_subnet_ids, local.effective_lambda_nat_public_subnet_id) &&
    (
      !local.lambda_nat_managed_public_subnet_enabled ||
      (
        var.lambda_nat_public_subnet_id == "" &&
        var.lambda_nat_public_subnet_cidr_block != "" &&
        !(var.lambda_nat_create_internet_gateway && var.lambda_nat_internet_gateway_id != "")
      )
    )
  )
  lambda_nat_egress_enabled = var.enable_lambda_nat_egress
}

data "aws_internet_gateway" "lambda_nat" {
  count = local.lambda_nat_discover_internet_gateway ? 1 : 0

  filter {
    name   = "attachment.vpc-id"
    values = [var.vpc_id]
  }
}

resource "aws_internet_gateway" "lambda_nat" {
  count = local.lambda_nat_managed_public_subnet_enabled && var.lambda_nat_create_internet_gateway ? 1 : 0

  vpc_id = var.vpc_id

  tags = {
    Name        = "${local.name_prefix}-lambda-nat-igw"
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_subnet" "lambda_nat_public" {
  count = local.lambda_nat_managed_public_subnet_enabled ? 1 : 0

  vpc_id                  = var.vpc_id
  cidr_block              = var.lambda_nat_public_subnet_cidr_block
  availability_zone       = var.lambda_nat_public_subnet_availability_zone == "" ? null : var.lambda_nat_public_subnet_availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name        = "${local.name_prefix}-lambda-nat-public"
    Project     = var.project
    Environment = var.environment
    Tier        = "public"
  }
}

resource "aws_route_table" "lambda_nat_public" {
  count = local.lambda_nat_managed_public_subnet_enabled ? 1 : 0

  vpc_id = var.vpc_id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = local.effective_lambda_nat_internet_gateway_id
  }

  tags = {
    Name        = "${local.name_prefix}-lambda-nat-public-rt"
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_route_table_association" "lambda_nat_public" {
  count = local.lambda_nat_managed_public_subnet_enabled ? 1 : 0

  subnet_id      = aws_subnet.lambda_nat_public[0].id
  route_table_id = aws_route_table.lambda_nat_public[0].id
}

resource "aws_eip" "lambda_nat" {
  count = local.lambda_nat_egress_enabled ? 1 : 0

  domain = "vpc"

  lifecycle {
    precondition {
      condition     = local.lambda_nat_egress_inputs_valid
      error_message = "enable_lambda_nat_egress requires vpc_id, db_subnet_ids, lambda_subnet_ids, either an existing lambda_nat_public_subnet_id or lambda_nat_create_public_subnet with lambda_nat_public_subnet_cidr_block, at least one lambda_nat_route_subnet_ids value, and non-conflicting NAT public subnet/Internet Gateway inputs."
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
  subnet_id     = local.effective_lambda_nat_public_subnet_id

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
