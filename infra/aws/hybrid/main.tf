locals {
  tags = merge({
    Application = "TapInX"
    Component   = "hybrid-workers"
    ManagedBy   = "Terraform"
  }, var.tags)
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "report_artifacts" {
  bucket        = "${var.name_prefix}-report-artifacts-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  force_destroy = false
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "report_artifacts" {
  bucket                  = aws_s3_bucket.report_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "report_artifacts" {
  bucket = aws_s3_bucket.report_artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "report_artifacts" {
  bucket = aws_s3_bucket.report_artifacts.id
  rule {
    id     = "expire-prepared-reports"
    status = "Enabled"
    filter {
      prefix = "prepared-email/"
    }
    expiration {
      days = var.report_artifact_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "report_artifacts_tls" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.report_artifacts.arn,
      "${aws_s3_bucket.report_artifacts.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "report_artifacts" {
  bucket = aws_s3_bucket.report_artifacts.id
  policy = data.aws_iam_policy_document.report_artifacts_tls.json
}

resource "aws_dynamodb_table" "report_idempotency" {
  name         = "${var.name_prefix}-report-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "idempotency_key"
  attribute {
    name = "idempotency_key"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  server_side_encryption {
    enabled = true
  }
  tags = local.tags
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids
  tags              = local.tags
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_sqs_queue" "dead_letter" {
  name                      = "${var.name_prefix}-dead-letter"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}

resource "aws_sqs_queue" "database_jobs" {
  name                       = "${var.name_prefix}-database-jobs"
  visibility_timeout_seconds = 3660
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 4
  })
  tags = local.tags
}

resource "aws_sqs_queue" "outbound_jobs" {
  name                       = "${var.name_prefix}-outbound-jobs"
  visibility_timeout_seconds = 360
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 4
  })
  tags = local.tags
}

resource "aws_security_group" "vpc_worker" {
  name_prefix = "${var.name_prefix}-lambda-"
  description = "TapInX DB Lambda: PostgreSQL through PgBouncer only"
  vpc_id      = var.vpc_id
  tags        = local.tags
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_egress_rule" "vpc_worker_to_pgbouncer" {
  security_group_id            = aws_security_group.vpc_worker.id
  referenced_security_group_id = var.ec2_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 6432
  to_port                      = 6432
  description                  = "PgBouncer on the existing EC2 host"
}

resource "aws_vpc_security_group_egress_rule" "vpc_worker_to_s3" {
  security_group_id = aws_security_group.vpc_worker.id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "Encrypted report artifacts through the free S3 Gateway endpoint"
}

resource "aws_vpc_security_group_ingress_rule" "ec2_from_vpc_worker" {
  security_group_id            = var.ec2_security_group_id
  referenced_security_group_id = aws_security_group.vpc_worker.id
  ip_protocol                  = "tcp"
  from_port                    = 6432
  to_port                      = 6432
  description                  = "PgBouncer access from cost-optimized Lambda workers"
}

resource "aws_iam_role" "vpc_worker" {
  name_prefix        = "${var.name_prefix}-db-"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}

resource "aws_iam_role" "outbound_worker" {
  name_prefix        = "${var.name_prefix}-outbound-"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "vpc_worker_logs" {
  role       = aws_iam_role.vpc_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "vpc_worker_network" {
  role       = aws_iam_role.vpc_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "outbound_worker_logs" {
  role       = aws_iam_role.outbound_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "vpc_worker_queue" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.database_jobs.arn]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.report_artifacts.arn}/prepared-email/*"]
  }
}

data "aws_iam_policy_document" "outbound_worker_queue" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.outbound_jobs.arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.report_artifacts.arn}/prepared-email/*"]
  }
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.report_idempotency.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.database_jobs.arn, aws_sqs_queue.dead_letter.arn]
  }
}

data "aws_iam_policy_document" "ec2_report_submit" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.database_jobs.arn]
  }
  statement {
    actions   = ["sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.database_jobs.arn, aws_sqs_queue.dead_letter.arn]
  }
}

resource "aws_iam_role_policy" "ec2_report_submit" {
  count  = var.ec2_application_role_name == "" ? 0 : 1
  name   = "${var.name_prefix}-report-submit"
  role   = var.ec2_application_role_name
  policy = data.aws_iam_policy_document.ec2_report_submit.json
}

resource "aws_iam_role_policy" "vpc_worker_queue" {
  role   = aws_iam_role.vpc_worker.id
  policy = data.aws_iam_policy_document.vpc_worker_queue.json
}

resource "aws_iam_role_policy" "outbound_worker_queue" {
  role   = aws_iam_role.outbound_worker.id
  policy = data.aws_iam_policy_document.outbound_worker_queue.json
}

resource "aws_cloudwatch_log_group" "vpc_worker" {
  name              = "/aws/lambda/${var.name_prefix}-db-worker"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "outbound_worker" {
  name              = "/aws/lambda/${var.name_prefix}-outbound-worker"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_lambda_function" "vpc_worker" {
  function_name                  = "${var.name_prefix}-db-worker"
  filename                       = var.vpc_worker_zip
  source_code_hash               = filebase64sha256(var.vpc_worker_zip)
  handler                        = "lambda_workers.vpc_db_handler.handler"
  runtime                        = "python3.11"
  architectures                  = ["x86_64"]
  role                           = aws_iam_role.vpc_worker.arn
  memory_size                    = 512
  timeout                        = 600
  reserved_concurrent_executions = var.vpc_worker_reserved_concurrency
  environment {
    variables = {
      DATABASE_URL               = var.database_url
      DB_CONNECT_TIMEOUT_SECONDS = "5"
      TAPINX_DB_ONLY_LAMBDA      = "1"
      REPORT_ARTIFACT_BUCKET     = aws_s3_bucket.report_artifacts.id
      REPORT_ARTIFACT_MAX_BYTES  = tostring(8 * 1024 * 1024)
      REPORT_MESSAGE_ID_DOMAIN   = "reports.tapinx.in"
      REPORT_LAMBDA_VENDOR_IDS   = join(",", var.report_lambda_vendor_ids)
    }
  }
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.vpc_worker.id]
  }
  depends_on = [
    aws_cloudwatch_log_group.vpc_worker,
    aws_iam_role_policy.vpc_worker_queue,
    aws_iam_role_policy_attachment.vpc_worker_logs,
    aws_iam_role_policy_attachment.vpc_worker_network,
  ]
  tags = local.tags
}

resource "aws_lambda_function" "outbound_worker" {
  function_name                  = "${var.name_prefix}-outbound-worker"
  filename                       = var.outbound_worker_zip
  source_code_hash               = filebase64sha256(var.outbound_worker_zip)
  handler                        = "lambda_workers.outbound_email_handler.handler"
  runtime                        = "python3.11"
  architectures                  = ["x86_64"]
  role                           = aws_iam_role.outbound_worker.arn
  memory_size                    = 256
  timeout                        = 60
  reserved_concurrent_executions = 5
  environment {
    variables = {
      MAIL_SMTP_USERNAME       = var.smtp_username
      MAIL_SMTP_APP_PASSWORD   = var.smtp_app_password
      MAIL_SMTP_HOST           = var.smtp_host
      MAIL_SMTP_PORT           = tostring(var.smtp_port)
      MAIL_FROM_ADDRESS        = var.smtp_username
      MAIL_FROM_NAME           = "OpenVisionX Reports"
      REPORT_IDEMPOTENCY_TABLE = aws_dynamodb_table.report_idempotency.name
      DATABASE_JOBS_QUEUE_URL  = aws_sqs_queue.database_jobs.url
    }
  }
  depends_on = [
    aws_cloudwatch_log_group.outbound_worker,
    aws_iam_role_policy.outbound_worker_queue,
    aws_iam_role_policy_attachment.outbound_worker_logs,
  ]
  tags = local.tags
}

resource "aws_lambda_event_source_mapping" "database_jobs" {
  event_source_arn        = aws_sqs_queue.database_jobs.arn
  function_name           = aws_lambda_function.vpc_worker.arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = var.vpc_worker_reserved_concurrency
  }
  depends_on = [aws_iam_role_policy.vpc_worker_queue]
}

resource "aws_lambda_permission" "report_artifacts" {
  statement_id   = "AllowReportArtifactBucket"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.outbound_worker.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.report_artifacts.arn
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_s3_bucket_notification" "report_artifacts" {
  bucket = aws_s3_bucket.report_artifacts.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.outbound_worker.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "prepared-email/"
    filter_suffix       = ".json"
  }
  depends_on = [aws_lambda_permission.report_artifacts]
}

resource "aws_lambda_function_event_invoke_config" "outbound_worker" {
  function_name                = aws_lambda_function.outbound_worker.function_name
  maximum_event_age_in_seconds = 21600
  maximum_retry_attempts       = 2
  destination_config {
    on_failure {
      destination = aws_sqs_queue.dead_letter.arn
    }
  }
}

resource "aws_lambda_event_source_mapping" "outbound_jobs" {
  event_source_arn        = aws_sqs_queue.outbound_jobs.arn
  function_name           = aws_lambda_function.outbound_worker.arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = 5
  }
  depends_on = [aws_iam_role_policy.outbound_worker_queue]
}

resource "aws_iam_role" "scheduler" {
  name_prefix = "${var.name_prefix}-scheduler-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = aws_sqs_queue.database_jobs.arn
    }]
  })
}

resource "aws_cloudwatch_event_rule" "daily_cleanup" {
  count               = var.enable_maintenance_schedule ? 1 : 0
  name                = "${var.name_prefix}-daily-cleanup"
  description         = "Queue PostgreSQL orphan cleanup once per day"
  schedule_expression = "cron(15 20 * * ? *)"
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "daily_cleanup" {
  count     = var.enable_maintenance_schedule ? 1 : 0
  rule      = aws_cloudwatch_event_rule.daily_cleanup[0].name
  target_id = "database-jobs"
  arn       = aws_sqs_queue.database_jobs.arn
  role_arn  = aws_iam_role.scheduler.arn
  input = jsonencode({
    version = 1
    task    = "maintenance.cleanup_orphans"
    payload = {}
  })
}

resource "aws_cloudwatch_event_rule" "report_dispatch" {
  count               = var.enable_report_schedule ? 1 : 0
  name                = "${var.name_prefix}-report-dispatch"
  description         = "Check for due automated reports every fifteen minutes"
  schedule_expression = "rate(15 minutes)"
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "report_dispatch" {
  count     = var.enable_report_schedule ? 1 : 0
  rule      = aws_cloudwatch_event_rule.report_dispatch[0].name
  target_id = "database-report-jobs"
  arn       = aws_sqs_queue.database_jobs.arn
  role_arn  = aws_iam_role.scheduler.arn
  input = jsonencode({
    version = 1
    task    = "reports.dispatch_due"
    payload = {}
  })
}
