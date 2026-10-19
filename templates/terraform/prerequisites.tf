# Service roles that Control Tower requires before a landing zone can be created through the API.
data "aws_partition" "current" {}

resource "aws_iam_role" "ct_admin" {
  name = "AWSControlTowerAdmin"
  path = "/service-role/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "controltower.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ct_admin" {
  name = "AWSControlTowerAdminPolicy"
  role = aws_iam_role.ct_admin.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "ec2:DescribeAvailabilityZones", Resource = "*" }]
  })
}

resource "aws_iam_role_policy_attachment" "ct_admin" {
  role       = aws_iam_role.ct_admin.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSControlTowerServiceRolePolicy"
}

resource "aws_iam_role" "ct_cloudtrail" {
  name = "AWSControlTowerCloudTrailRole"
  path = "/service-role/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ct_cloudtrail" {
  name = "AWSControlTowerCloudTrailRolePolicy"
  role = aws_iam_role.ct_cloudtrail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "arn:${data.aws_partition.current.partition}:logs:*:*:log-group:aws-controltower/CloudTrailLogs:*"
    }]
  })
}

resource "aws_iam_role" "ct_stackset" {
  name = "AWSControlTowerStackSetRole"
  path = "/service-role/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudformation.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ct_stackset" {
  name = "AWSControlTowerStackSetRolePolicy"
  role = aws_iam_role.ct_stackset.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = "arn:${data.aws_partition.current.partition}:iam::*:role/AWSControlTowerExecution"
    }]
  })
}

resource "aws_iam_role" "ct_config_aggregator" {
  name = "AWSControlTowerConfigAggregatorRoleForOrganizations"
  path = "/service-role/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "config.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ct_config_aggregator" {
  role       = aws_iam_role.ct_config_aggregator.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSConfigRoleForOrganizations"
}
