#!/usr/bin/env bash
# Install and configure a local-only RabbitMQ broker for OpenVision.
# Run on the EC2 host as the deployment user: bash scripts/configure-rabbitmq.sh
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/backend/.env}"
RABBITMQ_VHOST="${RABBITMQ_VHOST:-openvision}"
RABBITMQ_USER="${RABBITMQ_USER:-openvision_worker}"

[[ "$RABBITMQ_VHOST" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid RABBITMQ_VHOST" >&2; exit 1; }
[[ "$RABBITMQ_USER" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid RABBITMQ_USER" >&2; exit 1; }

if ! command -v rabbitmqctl >/dev/null 2>&1; then
    sudo apt-get update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y rabbitmq-server
fi

sudo install -d -m 0755 /etc/rabbitmq
if [ ! -f /etc/rabbitmq/rabbitmq.conf ] || ! sudo grep -q '^listeners.tcp.default = 127.0.0.1:5672$' /etc/rabbitmq/rabbitmq.conf; then
    printf '%s\n' \
        'listeners.tcp.default = 127.0.0.1:5672' \
        'management.tcp.ip = 127.0.0.1' \
        'loopback_users.guest = true' \
        | sudo tee -a /etc/rabbitmq/rabbitmq.conf >/dev/null
fi
sudo systemctl enable --now rabbitmq-server
sudo rabbitmq-diagnostics -q ping

RABBITMQ_PASSWORD="${RABBITMQ_PASSWORD:-}"
if [ -z "$RABBITMQ_PASSWORD" ]; then
    RABBITMQ_PASSWORD="$(openssl rand -hex 32)"
fi

if sudo rabbitmqctl -q list_vhosts name | grep -Fxq "$RABBITMQ_VHOST"; then
    :
else
    sudo rabbitmqctl add_vhost "$RABBITMQ_VHOST"
fi
if sudo rabbitmqctl -q list_users | awk '{print $1}' | grep -Fxq "$RABBITMQ_USER"; then
    sudo rabbitmqctl change_password "$RABBITMQ_USER" "$RABBITMQ_PASSWORD"
else
    sudo rabbitmqctl add_user "$RABBITMQ_USER" "$RABBITMQ_PASSWORD"
fi
sudo rabbitmqctl set_permissions -p "$RABBITMQ_VHOST" "$RABBITMQ_USER" '.*' '.*' '.*'

ENCODED_PASSWORD="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$RABBITMQ_PASSWORD")"
BROKER_URL="amqp://${RABBITMQ_USER}:${ENCODED_PASSWORD}@127.0.0.1:5672/${RABBITMQ_VHOST}"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
set_env() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}
set_env CELERY_BROKER_URL "$BROKER_URL"
if ! grep -q '^CELERY_RESULT_BACKEND=.' "$ENV_FILE"; then
    REDIS_URL="$(sed -n 's/^REDIS_URL=//p' "$ENV_FILE" | tail -n 1)"
    [ -n "$REDIS_URL" ] && set_env CELERY_RESULT_BACKEND "$REDIS_URL"
fi

echo "RabbitMQ is listening locally and the Celery broker URL was written to $ENV_FILE."
echo "Restart OpenVision workers only after the existing Redis task queues have drained."
