"""Declare all configured Celery queues/exchanges before selective workers start."""
from celery_app import celery


def main():
    if celery is None:
        raise SystemExit("Celery broker is not configured")
    with celery.connection_for_write() as connection:
        connection.ensure_connection(max_retries=3, timeout=5)
        channel = connection.channel()
        try:
            for queue in celery.conf.task_queues:
                queue(channel).declare()
        finally:
            channel.close()


if __name__ == "__main__":
    main()
