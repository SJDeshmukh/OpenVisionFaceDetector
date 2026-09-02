#!/usr/bin/env bash
# OpenVision AWS installer
#
# Usage:
#   bash setup_aws.sh          Interactive deployment (choose Docker or bare metal)
#   bash setup_aws.sh check    Read-only source/configuration checks
#   bash setup_aws.sh stop     Stop OpenVision application services only
#
# Bare-metal environment overrides:
#   DEPLOY_DOMAIN=tapinx.in    Public DNS name (default: tapinx.in)
#   ENABLE_SSL=auto|yes|no     Provision Let's Encrypt when DNS resolves here
#   MIGRATE_SQLITE=0|1         Import a legacy SQLite database (default: 0)

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ACTION="${1:-setup}"
DEPLOY_DOMAIN="${DEPLOY_DOMAIN:-tapinx.in}"
ENABLE_SSL="${ENABLE_SSL:-auto}"
MIGRATE_SQLITE="${MIGRATE_SQLITE:-0}"
ENV_FILE="$SCRIPT_DIR/backend/.env"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"

[[ "$DEPLOY_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || {
    printf 'ERROR: DEPLOY_DOMAIN contains invalid characters.\n' >&2
    exit 1
}
[[ "$ENABLE_SSL" =~ ^(auto|yes|no)$ ]] || {
    printf 'ERROR: ENABLE_SSL must be auto, yes, or no.\n' >&2
    exit 1
}
[[ "$MIGRATE_SQLITE" =~ ^[01]$ ]] || {
    printf 'ERROR: MIGRATE_SQLITE must be 0 or 1.\n' >&2
    exit 1
}

log() {
    printf '\n==> %s\n' "$1"
}

die() {
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}

on_error() {
    local exit_code=$?
    printf '\nDeployment failed at line %s (exit %s).\n' "${BASH_LINENO[0]}" "$exit_code" >&2
    printf 'Inspect services with: sudo systemctl status openvision-backend openvision-celery --no-pager\n' >&2
    exit "$exit_code"
}
trap on_error ERR

require_source_tree() {
    local required=(
        "backend/app.py"
        "backend/requirements.txt"
        "backend/celery_app.py"
        "web-dashboard/package.json"
        "web-dashboard/package-lock.json"
        "nginx_face_detection.conf"
    )
    local path
    for path in "${required[@]}"; do
        [ -f "$SCRIPT_DIR/$path" ] || die "Missing required project file: $path"
    done
}

env_get() {
    local key="$1"
    [ -f "$ENV_FILE" ] || return 0
    sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

env_set() {
    local key="$1"
    local value="$2"
    touch "$ENV_FILE"
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

wait_for_url() {
    local url="$1"
    local attempts="${2:-30}"
    local i
    for ((i = 1; i <= attempts; i++)); do
        if curl --fail --silent --show-error --max-time 5 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

stop_application_services() {
    sudo systemctl stop openvision-backend openvision-celery face-backend 2>/dev/null || true
}

if [ "$ACTION" = "check" ]; then
    require_source_tree
    bash -n "$SCRIPT_DIR/setup_aws.sh"
    printf 'Source tree: OK\n'
    printf 'Bash syntax: OK\n'
    if command -v docker >/dev/null 2>&1; then
        if [ -f "$SCRIPT_DIR/.env" ]; then
            docker compose config --quiet
            printf 'Docker Compose configuration: OK\n'
        else
            printf 'Docker Compose configuration: skipped (root .env not created yet)\n'
        fi
    fi
    printf 'Bare-metal deployment will target domain: %s\n' "$DEPLOY_DOMAIN"
    exit 0
fi

if [ "$ACTION" = "stop" ]; then
    log "Stopping OpenVision application services"
    stop_application_services
    if command -v docker >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        sudo docker compose stop api worker 2>/dev/null || true
    fi
    printf 'OpenVision API and worker services are stopped. PostgreSQL, Redis, Nginx, and unrelated containers were left running.\n'
    exit 0
fi

[ "$ACTION" = "setup" ] || die "Unknown command '$ACTION'. Use setup, check, or stop."
require_source_tree
[ "$EUID" -ne 0 ] || die "Run this script as the normal deployment user, not with sudo. It requests sudo only where needed."

printf '%s\n' "=============================================================================="
printf '%s\n' "OpenVision AWS Deployment"
printf '%s\n' "=============================================================================="
read -r -p "Do you want to use Docker for deployment? (y/n): " USE_DOCKER

if [[ "$USE_DOCKER" =~ ^[Yy]$ ]]; then
    log "Preparing isolated Docker deployment"
    command -v openssl >/dev/null 2>&1 || die "openssl is required"

    if ! command -v docker >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl gnupg lsb-release
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
        printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
            "$(dpkg --print-architecture)" "$(lsb_release -cs)" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    fi

    ROOT_ENV="$SCRIPT_DIR/.env"
    touch "$ROOT_ENV"
    chmod 600 "$ROOT_ENV"
    grep -q '^DB_PASSWORD=' "$ROOT_ENV" || printf 'DB_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> "$ROOT_ENV"
    grep -q '^REDIS_PASSWORD=' "$ROOT_ENV" || printf 'REDIS_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> "$ROOT_ENV"
    grep -q '^SECRET_KEY=' "$ROOT_ENV" || printf 'SECRET_KEY=%s\n' "$(openssl rand -hex 32)" >> "$ROOT_ENV"

    sudo docker compose config --quiet
    sudo docker compose up -d --build --remove-orphans --scale worker=1
    wait_for_url "http://127.0.0.1:5001/api/health" 45 || die "Docker API did not become healthy"
    printf '\nDocker API deployment completed successfully at http://%s:5001\n' "$(hostname -I | awk '{print $1}')"
    exit 0
fi

log "Selected safe bare-metal deployment"
sudo -v

log "Stopping only existing OpenVision application services"
stop_application_services
if sudo lsof -nP -iTCP:5001 -sTCP:LISTEN >/dev/null 2>&1; then
    sudo lsof -nP -iTCP:5001 -sTCP:LISTEN || true
    die "Port 5001 is occupied by a process outside the OpenVision systemd services"
fi

log "Installing operating-system dependencies"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3-pip python3-venv python3-dev \
    postgresql postgresql-contrib libpq-dev \
    redis-server redis-tools \
    nginx curl ca-certificates openssl \
    libgl1 libglib2.0-0 libgomp1 libheif-dev \
    psmisc lsof build-essential rsync \
    certbot python3-certbot-nginx

NODE_MAJOR=0
if command -v node >/dev/null 2>&1; then
    NODE_MAJOR="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
fi
if [ "$NODE_MAJOR" -lt 24 ]; then
    log "Installing Node.js 24 LTS"
    curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
node --version
npm --version

log "Configuring swap without replacing existing swap data"
if [ ! -e /swapfile ]; then
    sudo fallocate -l 4G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=4096 status=progress
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
fi
if ! sudo swapon --show=NAME --noheadings | grep -Fxq /swapfile; then
    sudo swapon /swapfile
fi
grep -qE '^/swapfile[[:space:]]' /etc/fstab || printf '/swapfile none swap sw 0 0\n' | sudo tee -a /etc/fstab >/dev/null

log "Starting PostgreSQL and Redis"
sudo systemctl enable --now postgresql redis-server

mkdir -p "$SCRIPT_DIR/backend"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

DB_PASSWORD="$(env_get DB_PASSWORD)"
[ -n "$DB_PASSWORD" ] || DB_PASSWORD="$(openssl rand -hex 24)"
if [[ ! "$DB_PASSWORD" =~ ^[A-Za-z0-9]+$ ]]; then
    printf 'Existing DB_PASSWORD contains URL/SQL-sensitive characters; rotating the dedicated application-role password.\n'
    DB_PASSWORD="$(openssl rand -hex 24)"
fi
SECRET_KEY="$(env_get SECRET_KEY)"
[ -n "$SECRET_KEY" ] || SECRET_KEY="$(openssl rand -hex 32)"

log "Creating the dedicated PostgreSQL application role and database"
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='openvision_app'" | grep -q 1; then
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE openvision_app WITH LOGIN PASSWORD '${DB_PASSWORD}'" >/dev/null
else
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE openvision_app WITH LOGIN PASSWORD '${DB_PASSWORD}'" >/dev/null
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='face_detection'" | grep -q 1; then
    sudo -u postgres createdb --owner=openvision_app face_detection
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE face_detection OWNER TO openvision_app" >/dev/null
sudo -u postgres psql -v ON_ERROR_STOP=1 -d face_detection <<'SQL' >/dev/null
ALTER SCHEMA public OWNER TO openvision_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO openvision_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO openvision_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO openvision_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO openvision_app;
SQL

REDIS_PASSWORD="$(env_get REDIS_PASSWORD)"
if redis-cli ping 2>/dev/null | grep -q PONG; then
    REDIS_URL="redis://127.0.0.1:6379/0"
elif [ -n "$REDIS_PASSWORD" ] && redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null | grep -q PONG; then
    REDIS_PASSWORD_ENCODED="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$REDIS_PASSWORD")"
    REDIS_URL="redis://:${REDIS_PASSWORD_ENCODED}@127.0.0.1:6379/0"
else
    die "Redis is running but could not be authenticated; check /etc/redis/redis.conf and backend/.env"
fi

TOTAL_RAM_MB="$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo)"
LOW_RAM_MODE=1
[ "$TOTAL_RAM_MB" -ge 3072 ] && LOW_RAM_MODE=0
PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')"

env_set SECRET_KEY "$SECRET_KEY"
env_set DB_PASSWORD "$DB_PASSWORD"
env_set DATABASE_URL "postgresql://openvision_app:${DB_PASSWORD}@127.0.0.1:5432/face_detection"
env_set DB_TYPE "postgres"
env_set REDIS_URL "$REDIS_URL"
env_set CELERY_BROKER_URL "$REDIS_URL"
env_set BACKEND_URL "http://${DEPLOY_DOMAIN}"
env_set FRONTEND_URL "http://${DEPLOY_DOMAIN}"
env_set LOW_RAM_MODE "$LOW_RAM_MODE"
chmod 600 "$ENV_FILE"

log "Creating the Python environment and installing project requirements"
if [ ! -d "$SCRIPT_DIR/backend/.venv" ]; then
    python3 -m venv "$SCRIPT_DIR/backend/.venv"
fi
# shellcheck disable=SC1091
source "$SCRIPT_DIR/backend/.venv/bin/activate"
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r "$SCRIPT_DIR/backend/requirements.txt"

log "Downloading and validating AI model resources"
python "$SCRIPT_DIR/backend/download_models.py"
MODEL_FILES=(
    "$SCRIPT_DIR/multiple_face_detection/models/realesrgan/RealESRGAN_x4plus.pth"
    "$SCRIPT_DIR/multiple_face_detection/models/realesrgan/RealESRGAN_x2plus.pth"
    "$SCRIPT_DIR/multiple_face_detection/models/gfpgan/GFPGANv1.4.pth"
    "$SCRIPT_DIR/backend/standalone_live_mesh/3DDFA-V3/assets/face_model.npy"
    "$SCRIPT_DIR/backend/standalone_live_mesh/3DDFA-V3/assets/net_recon.pth"
)
for model_file in "${MODEL_FILES[@]}"; do
    [ -s "$model_file" ] || die "Required model was not downloaded: $model_file"
done

log "Initializing and validating the PostgreSQL schema"
(
    cd "$SCRIPT_DIR/backend"
    export PYTHONPATH="$SCRIPT_DIR/backend:$SCRIPT_DIR"
    python -c "from db_factory import init_schemas; init_schemas()"
    if [ "$MIGRATE_SQLITE" = "1" ]; then
        python -c "import sys; from migrate_to_postgres import run_safe_migration; sys.exit(0 if run_safe_migration() else 1)"
    fi
)
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -U openvision_app -d face_detection -tAc \
    "SELECT CASE WHEN to_regclass('public.vendors') IS NOT NULL THEN 1 ELSE 0 END" | grep -q 1 \
    || die "PostgreSQL schema validation failed: vendors table is missing"

log "Building the web dashboard"
(
    cd "$SCRIPT_DIR/web-dashboard"
    npm ci --legacy-peer-deps
    NODE_OPTIONS="--max-old-space-size=1536" npm run build
    [ -f dist/index.html ] || die "Dashboard build did not create dist/index.html"
)

log "Deploying dashboard assets"
sudo install -d -o www-data -g www-data -m 0755 /var/www/face_detection
sudo rsync -a --delete "$SCRIPT_DIR/web-dashboard/dist/" /var/www/face_detection/
sudo chown -R www-data:www-data /var/www/face_detection

log "Installing Nginx configuration for ${DEPLOY_DOMAIN}"
sudo tee /etc/nginx/sites-available/face_detection >/dev/null <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DEPLOY_DOMAIN} www.${DEPLOY_DOMAIN};
    client_max_body_size 50M;

    root /var/www/face_detection;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    location /socket.io/ {
        proxy_pass http://127.0.0.1:5001/socket.io/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
    }
}
NGINX
sudo ln -sfn /etc/nginx/sites-available/face_detection /etc/nginx/sites-enabled/face_detection
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx

log "Installing application-scoped systemd services"
sudo tee /etc/systemd/system/openvision-backend.service >/dev/null <<UNIT
[Unit]
Description=OpenVision API
After=network-online.target postgresql.service redis-server.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${SCRIPT_DIR}/backend
Environment="PATH=${SCRIPT_DIR}/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=${SCRIPT_DIR}/backend:${SCRIPT_DIR}"
EnvironmentFile=${ENV_FILE}
ExecStart=${SCRIPT_DIR}/backend/.venv/bin/gunicorn --worker-class gthread --workers 1 --threads 4 --bind 127.0.0.1:5001 app:app --timeout 600
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=mixed
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/systemd/system/openvision-celery.service >/dev/null <<UNIT
[Unit]
Description=OpenVision Celery Worker
After=network-online.target postgresql.service redis-server.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${SCRIPT_DIR}/backend
Environment="PATH=${SCRIPT_DIR}/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=${SCRIPT_DIR}/backend:${SCRIPT_DIR}"
Environment="OMP_NUM_THREADS=1"
Environment="MKL_NUM_THREADS=1"
Environment="OPENBLAS_NUM_THREADS=1"
Environment="FORCE_3D_ENGINE=1"
EnvironmentFile=${ENV_FILE}
ExecStart=${SCRIPT_DIR}/backend/.venv/bin/celery -A celery_app worker --loglevel=info --concurrency=1 --pool=threads --max-tasks-per-child=500 --prefetch-multiplier=1 -n worker1@%H
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=mixed
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable openvision-backend openvision-celery
sudo systemctl restart openvision-backend openvision-celery
sudo systemctl is-active --quiet openvision-backend
sudo systemctl is-active --quiet openvision-celery

log "Running deployment health checks"
wait_for_url "http://127.0.0.1:5001/api/health" 45 || {
    sudo journalctl -u openvision-backend -n 100 --no-pager || true
    die "OpenVision API did not become healthy"
}
curl --fail --silent --show-error -H "Host: ${DEPLOY_DOMAIN}" http://127.0.0.1/api/health >/dev/null \
    || die "Nginx could not proxy the API health endpoint"

if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow 'Nginx Full' >/dev/null || true
fi

SSL_ENABLED=0
if [ "$ENABLE_SSL" != "no" ]; then
    DOMAIN_IP="$(getent ahostsv4 "$DEPLOY_DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    if [ "$ENABLE_SSL" = "yes" ] || { [ "$ENABLE_SSL" = "auto" ] && [ -n "$DOMAIN_IP" ] && [ "$DOMAIN_IP" = "$PUBLIC_IP" ]; }; then
        log "Provisioning Let's Encrypt for ${DEPLOY_DOMAIN}"
        CERTBOT_DOMAINS=(-d "$DEPLOY_DOMAIN")
        WWW_IP="$(getent ahostsv4 "www.${DEPLOY_DOMAIN}" 2>/dev/null | awk 'NR==1{print $1}' || true)"
        [ -n "$WWW_IP" ] && [ "$WWW_IP" = "$PUBLIC_IP" ] && CERTBOT_DOMAINS+=(-d "www.${DEPLOY_DOMAIN}")
        if sudo certbot --nginx "${CERTBOT_DOMAINS[@]}" --non-interactive --agree-tos \
            --register-unsafely-without-email --redirect; then
            SSL_ENABLED=1
            env_set BACKEND_URL "https://${DEPLOY_DOMAIN}"
            env_set FRONTEND_URL "https://${DEPLOY_DOMAIN}"
            sudo systemctl restart openvision-backend openvision-celery
            wait_for_url "https://${DEPLOY_DOMAIN}/api/health" 20 \
                || die "HTTPS certificate was installed, but the public health endpoint is unavailable"
        else
            printf 'WARNING: SSL provisioning failed; HTTP deployment remains available. Check DNS and rerun Certbot.\n' >&2
        fi
    else
        printf 'SSL skipped: %s resolves to %s, but this server public IP is %s.\n' \
            "$DEPLOY_DOMAIN" "${DOMAIN_IP:-nothing}" "$PUBLIC_IP"
    fi
fi

printf '\n%s\n' "=============================================================================="
printf '%s\n' "OPENVISION BARE-METAL DEPLOYMENT COMPLETED"
printf '%s\n' "=============================================================================="
if [ "$SSL_ENABLED" -eq 1 ]; then
    printf 'Dashboard: https://%s\n' "$DEPLOY_DOMAIN"
    printf 'API:       https://%s/api\n' "$DEPLOY_DOMAIN"
else
    printf 'Dashboard: http://%s\n' "$DEPLOY_DOMAIN"
    printf 'API:       http://%s/api\n' "$DEPLOY_DOMAIN"
fi
printf 'Local health: http://127.0.0.1:5001/api/health\n'
printf 'Services:     sudo systemctl status openvision-backend openvision-celery nginx\n'
printf 'Application logs: sudo journalctl -u openvision-backend -f\n'
