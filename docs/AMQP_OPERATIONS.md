# AMQP Operations Runbook

OpenVision uses Celery over RabbitMQ for durable background task delivery. Redis remains the cache, deduplication store, and Celery result backend. Mobile apps and browsers continue to use HTTPS, FCM, and Socket.IO; they never receive RabbitMQ credentials.

## Queue topology

| Queue | Work | Worker service |
|---|---|---|
| `face_priority` | face detection, embeddings, recognition batches | `openvision-celery` |
| `notifications` | email and push jobs | `openvision-celery-io` |
| `reports` | scheduled and requested reports | `openvision-celery-io` |
| `bulk_jobs` | imports and administrative batches | `openvision-celery-io` |
| `maintenance` | lifecycle and low-priority tasks | `openvision-celery-io` |
| `dead_letter` | broker-rejected or expired messages for investigation | no consumer |

Task messages are persistent. Workers acknowledge tasks after execution and use a prefetch multiplier of one. Tasks therefore must remain idempotent because an interrupted task can be delivered again.

Attendance-triggered parent notifications are submitted to `notifications`. If the broker is temporarily unavailable, the API falls back to the existing local background thread so an attendance request is not rejected solely because RabbitMQ is down.

## First EC2 rollout

Do not switch brokers while Redis still contains queued Celery work.

1. Deploy the code while leaving the existing `CELERY_BROKER_URL` unchanged.
2. Temporarily stop or disable endpoints/jobs that submit background work.
3. Check `/api/admin/system/queues` and Celery worker inspection until the old Redis queues are empty and no tasks are active or reserved.
4. Stop worker and beat services, but keep the API running only if task-producing operations are blocked:

   ```bash
   sudo systemctl stop openvision-celery openvision-celery-io openvision-celery-beat
   ```

5. Install/configure RabbitMQ and update `backend/.env`:

   ```bash
   bash scripts/configure-rabbitmq.sh
   ```

6. Redeploy the bare-metal services with AMQP enabled:

   ```bash
   ENABLE_AMQP=1 bash setup_aws.sh
   ```

7. Confirm that RabbitMQ is local-only and healthy:

   ```bash
   sudo rabbitmq-diagnostics listeners
   sudo rabbitmq-diagnostics alarms
   sudo rabbitmqctl list_queues -p openvision name messages consumers
   ```

8. Submit one face job, one notification, and one report. Verify completion and then restore normal traffic.

Port `5672` and the RabbitMQ management port must not be opened in the EC2 security group. The installer binds RabbitMQ to `127.0.0.1`.

## Payload storage

`TASK_PAYLOAD_OFFLOAD=true` stores large face images outside the broker and sends only an opaque reference. The bare-metal installer creates `/var/lib/openvision/task-payloads` with mode `0700`.

The local directory is correct while the API and worker run on one EC2 host. Before adding workers on another host, configure `S3_BUCKET`; payloads will then be stored under the private `task-payloads/` prefix. An EC2 IAM role is preferred over static AWS access keys.

Payload references expire operationally after `TASK_PAYLOAD_TTL_SECONDS`. Successful tasks delete their payload. Stale local payloads are removed opportunistically when new payloads are stored.

## Monitoring and alerts

- Superadmin queue data: `GET /api/admin/system/queues`
- Task history: `GET /api/admin/jobs/events`
- Task metrics: `GET /api/admin/jobs/metrics`
- Prometheus: `GET /metrics`

Prometheus exposes:

- `openvision_celery_broker_up`
- `openvision_celery_queue_messages{queue=...}`
- `openvision_celery_queue_consumers{queue=...}`

Alert when the broker is down, `dead_letter` is non-zero, a live queue has no consumer, or queue depth remains above the deployment's operating threshold.

## Failure and recovery

Inspect a failure before retrying it. Tasks can perform database writes and are designed to use stable IDs rather than treating delivery as exactly-once.

```bash
sudo journalctl -u rabbitmq-server -n 200 --no-pager
sudo journalctl -u openvision-celery -n 200 --no-pager
sudo journalctl -u openvision-celery-io -n 200 --no-pager
sudo rabbitmq-diagnostics status
sudo rabbitmqctl list_queues -p openvision name messages_ready messages_unacknowledged consumers
```

Do not purge `dead_letter` automatically. Export or inspect its messages, correct the cause, and only then requeue or remove them.

## Rollback to Redis

1. Block new background job submissions.
2. Drain RabbitMQ and verify there are no unacknowledged messages.
3. Stop worker and beat services.
4. Set `CELERY_BROKER_URL` back to the value of `REDIS_URL`.
5. Restart both workers and Beat.
6. Run the same face, notification, and report smoke tests.

Messages are not automatically copied between RabbitMQ and Redis in either direction.
