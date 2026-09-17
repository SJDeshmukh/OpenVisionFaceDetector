output "database_jobs_queue_url" {
  value = aws_sqs_queue.database_jobs.url
}

output "outbound_jobs_queue_url" {
  value = aws_sqs_queue.outbound_jobs.url
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.dead_letter.url
}

output "vpc_lambda_security_group_id" {
  value = aws_security_group.vpc_worker.id
}

output "report_artifact_bucket" {
  value = aws_s3_bucket.report_artifacts.id
}

output "report_idempotency_table" {
  value = aws_dynamodb_table.report_idempotency.name
}

output "ec2_report_submit_policy_json" {
  description = "Attach this least-privilege SQS submit/health policy to the EC2 role if ec2_application_role_name was left empty."
  value       = data.aws_iam_policy_document.ec2_report_submit.json
}
