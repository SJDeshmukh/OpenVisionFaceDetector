variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type    = string
  default = "tapinx-hybrid"
}

variable "vpc_id" {
  type        = string
  description = "VPC containing the existing EC2/PostgreSQL host."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets with a route to the EC2 private address. No NAT route is required."
  validation {
    condition     = length(var.private_subnet_ids) >= 1
    error_message = "At least one private subnet is required."
  }
}

variable "private_route_table_ids" {
  type        = list(string)
  description = "Route tables used by the Lambda private subnets. An S3 Gateway endpoint is attached to these at no hourly charge."
  validation {
    condition     = length(var.private_route_table_ids) >= 1
    error_message = "At least one private route table is required for the S3 Gateway endpoint."
  }
}

variable "ec2_security_group_id" {
  type        = string
  description = "Security group attached to the existing EC2 host."
}

variable "ec2_application_role_name" {
  type        = string
  default     = ""
  description = "Optional existing EC2 instance-role name. When set, Terraform grants only SQS SendMessage to the database jobs queue."
}

variable "database_url" {
  type        = string
  sensitive   = true
  description = "PostgreSQL URL using the EC2 private address and PgBouncer port 6432. Protect Terraform state."
  validation {
    condition     = startswith(var.database_url, "postgresql://") && can(regex(":6432(/|\\?)", var.database_url))
    error_message = "database_url must be a PostgreSQL URL using PgBouncer port 6432."
  }
}

variable "vpc_worker_zip" {
  type    = string
  default = "../../../backend/.dist/hybrid/vpc-db-worker.zip"
}

variable "outbound_worker_zip" {
  type    = string
  default = "../../../backend/.dist/hybrid/outbound-email-worker.zip"
}

variable "vpc_worker_reserved_concurrency" {
  type    = number
  default = 5
  validation {
    condition     = var.vpc_worker_reserved_concurrency >= 2 && var.vpc_worker_reserved_concurrency <= 10
    error_message = "SQS scaling requires reserved concurrency between 2 and 10; start low to protect PostgreSQL."
  }
}

variable "enable_maintenance_schedule" {
  type        = bool
  default     = false
  description = "Enable only after the cleanup query has been validated against a production backup."
}

variable "enable_report_schedule" {
  type        = bool
  default     = false
  description = "Keep false until the Lambda report path has passed staging and shadow-mode checks."
}

variable "report_lambda_vendor_ids" {
  type        = list(string)
  default     = []
  description = "Vendor IDs allowed on the Lambda report path. Use [\"*\"] only after canary validation."
  validation {
    condition = alltrue([
      for vendor_id in var.report_lambda_vendor_ids :
      vendor_id == "*" || can(tonumber(vendor_id))
    ]) && (!(contains(var.report_lambda_vendor_ids, "*")) || length(var.report_lambda_vendor_ids) == 1)
    error_message = "Use numeric vendor IDs, or [\"*\"] by itself for full rollout."
  }
}

variable "report_artifact_retention_days" {
  type        = number
  default     = 2
  description = "Safety-net retention; successful deliveries delete artifacts immediately."
  validation {
    condition     = var.report_artifact_retention_days >= 1 && var.report_artifact_retention_days <= 7
    error_message = "Report artifacts must expire between 1 and 7 days."
  }
}

variable "smtp_username" {
  type      = string
  sensitive = true
}

variable "smtp_app_password" {
  type      = string
  sensitive = true
}

variable "smtp_host" {
  type    = string
  default = "smtp.gmail.com"
}

variable "smtp_port" {
  type    = number
  default = 587
}

variable "tags" {
  type    = map(string)
  default = {}
}
