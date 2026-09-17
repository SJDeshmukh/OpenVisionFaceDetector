# TapInX hybrid cost optimization

This is the approved no-NAT design. Applying it is intentionally separate from
committing the code: review and benchmark each phase before removing any EC2
process.

## Safety boundaries

- PostgreSQL, Nginx, Socket.IO and live device state remain on EC2.
- The existing Celery worker remains the production fallback until equivalent
  Lambda paths have passed an attendance-cycle soak test.
- VPC workers may connect only to PgBouncer on TCP 6432. They must not call
  public APIs, SMTP or Bedrock.
- Outbound workers are not VPC-attached and must receive complete payloads; they
  never query PostgreSQL.
- No NAT Gateway or paid interface VPC endpoint is created by this module.
- Mobile API URLs and behavior are unchanged.

## Phase 1: PgBouncer and maintenance worker

Build the isolated Lambda ZIP files:

```bash
scripts/build-hybrid-lambdas.sh
```

Start the existing stack with the PgBouncer override in a non-production test:

```bash
docker compose -f docker-compose.yml -f docker-compose.hybrid.yml config
docker compose -f docker-compose.yml -f docker-compose.hybrid.yml up -d
```

The override caps the API pool at eight connections and initially caps the VPC
Lambda at five concurrent executions. The EC2 security group must allow port
6432 only from the Lambda security group. PostgreSQL port 5432 remains private.

Prepare `infra/aws/hybrid/terraform.tfvars` from the example, then run `terraform
plan`. Do not apply until the plan has been reviewed. The database password and
SMTP password are sensitive Terraform inputs, so production Terraform state
must be encrypted and access-controlled.

The first VPC task is orphan cleanup. It has no external network dependency.
The EventBridge schedule is disabled by default; enable it only after running
the query against a production backup and reviewing the affected-row counts.
When enabled, EventBridge sends the task to SQS, AWS invokes the VPC Lambda,
and the Lambda talks only to PgBouncer.

## Report preparation and delivery (implemented, disabled by default)

The report path now uses these boundaries:

1. The API or report scheduler sends only a report request to the database SQS
   queue.
2. The VPC Lambda reads PostgreSQL through PgBouncer, calculates the existing
   attendance/payroll report, and writes a private AES-256-encrypted JSON
   artifact to S3 through a free Gateway endpoint.
3. S3 invokes the non-VPC Lambda. It obtains a DynamoDB idempotency lease,
   delivers SMTP, and sends a small status result to the database queue.
4. The VPC Lambda reconciles `sent` or `failed` into
   `report_delivery_jobs`/`automated_report_deliveries`. Successful artifacts
   are deleted immediately; a two-day lifecycle is the cleanup safety net.

No NAT Gateway or paid interface endpoint is needed. The S3 route uses the
private subnet route-table IDs supplied in `terraform.tfvars`.

Celery remains the default. After a staging run and a controlled production
canary, switch only report submission with:

```dotenv
REPORT_TASK_BACKEND=lambda_sqs
REPORT_DATABASE_QUEUE_URL=<terraform database_jobs_queue_url output>
REPORT_DLQ_URL=<terraform dead_letter_queue_url output>
REPORT_LAMBDA_VENDOR_IDS=<one approved vendor ID>
```

An empty `REPORT_LAMBDA_VENDOR_IDS` is deliberately fail-safe: every vendor
continues through Celery. Add one numeric vendor ID for the canary. Comma-separate
additional IDs only after each succeeds. `*` enables every vendor and is reserved
for the final cutover. Configure the same IDs in Terraform through
`report_lambda_vendor_ids`; the DB Lambda enforces the allowlist independently
of the API dispatcher.

The API/worker EC2 instance role also needs `sqs:SendMessage` for that one
queue. Set `ec2_application_role_name` in the Terraform variables to attach the
included least-privilege inline policy, or use the
`ec2_report_submit_policy_json` output with your existing IAM management.
If the API runs inside Docker, verify that the container can obtain the instance
role through IMDSv2; EC2 installations that restrict the metadata response hop
limit to one commonly need a hop limit of two for bridged containers. Do not
replace the instance role with long-lived AWS keys in `.env`.

Leave `enable_report_schedule = false` until manual employee reports and a test
automated report have both reconciled to `sent`. Celery must remain available
for immediate rollback: set `REPORT_TASK_BACKEND=celery` and restart the API
and worker.

## Health and delivery status

- `GET /api/admin/hybrid-reports/health` is restricted to Super Admin and
  reports the active backend, canary scope, 24-hour delivery counts, database
  query health, database-queue depth and DLQ depth. It returns HTTP 503 when the
  Lambda path is degraded.
- `GET /api/reports/email-employees/status/<task_id>` is tenant-scoped and
  returns per-recipient preparation/delivery results for the request ID returned
  by the send endpoint.
- Clients may send an `Idempotency-Key` header (maximum 128 safe characters)
  when starting an employee report. Reusing it after an ambiguous HTTP retry
  preserves the same Lambda delivery keys.

The DynamoDB lease prevents duplicate sends from ordinary S3/Lambda retries.
SMTP cannot provide a true atomic exactly-once transaction: a process crash in
the narrow interval after SMTP accepts a message but before DynamoDB records
`sent` can still cause a retry. A stable Message-ID reduces that risk and the
delivery status/DLQ makes the edge case auditable.

## Queue contract

Every message is versioned:

```json
{
  "version": 1,
  "task": "maintenance.cleanup_orphans",
  "payload": {}
}
```

The outbound queue also accepts `outbound.send_email`. Its payload must
contain `recipient`, `subject`, and `body`; attachments use base64 content. A
stable `message_id` should be provided by the producer. Report artifact
delivery uses the DynamoDB idempotency path described above.

## Remaining migration order

1. Run PgBouncer with the current API/Celery stack and verify transactions,
   payroll, leave approval and attendance under load.
2. Deploy only the maintenance queue/worker and verify DLQ and CloudWatch logs.
3. Run the implemented report pipeline in staging, then canary one vendor while
   Celery remains the rollback path.
4. After a full reporting cycle, enable the EventBridge report schedule and
   remove only the corresponding Celery Beat entry.
5. Move advance and parent notification payload preparation to the DB worker;
   keep FCM/SMTP delivery in a non-VPC worker.
6. Migrate lightweight REST route groups incrementally. Keep `/socket.io/*` on
   EC2.
7. Measure CPU, peak RSS, PostgreSQL connections and latency for a complete
   attendance cycle after REST migration.
8. Only then test a `t3.small`; roll back immediately on swapping, OOM, database
   saturation or increased p95 latency.
9. Benchmark bulk face processing as an asynchronous container Lambda using
   presigned S3 uploads. Do not send images through API Gateway.

The original `backend/lambda_handler.py` imports the full Flask application and
must not be used for this migration. The workers in `backend/lambda_workers`
have deliberately small dependency and network boundaries.
