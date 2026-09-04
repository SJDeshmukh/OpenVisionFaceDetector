#!/usr/bin/env bash
# OpenVision AWS installer
#
# Usage:
#   bash setup_aws.sh          Interactive deployment (choose Docker or bare metal)
#   bash setup_aws.sh check    Read-only source/configuration checks
#   bash setup_aws.sh stop     Stop OpenVision application services only
#   bash setup_aws.sh boot-check      Idempotently start and verify an installed deployment
#   bash setup_aws.sh configure-mail  Securely configure Gmail SMTP and restart app services
#   bash setup_aws.sh configure-ai    Choose/configure the XChat AI provider and restart the API
#   bash setup_aws.sh omniroute-status    Show install/service/key status without exposing secrets
#   bash setup_aws.sh omniroute-password  Reveal the saved dashboard bootstrap password
#   bash setup_aws.sh omniroute-key       Reveal the saved XChat gateway key
#
# Optional provider fallbacks:
#   Put GROQ_API_KEY, GEMINI_API_KEY, and/or CEREBRAS_API_KEY in
#   ai-provider-keys.env (mode 0600). OmniRoute remains the first provider.
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
MODE_FILE="$SCRIPT_DIR/.openvision-deployment-mode"
OMNIROUTE_ENV_FILE="$SCRIPT_DIR/.omniroute.env"
OMNIROUTE_DATA_DIR="$SCRIPT_DIR/.omniroute-data"
OMNIROUTE_SERVICE="openvision-omniroute.service"
AI_PROVIDER_KEYS_FILE="${AI_PROVIDER_KEYS_FILE:-$SCRIPT_DIR/ai-provider-keys.env}"
RECOVER_SYSTEMD_SERVICES=0
APT_LOCK_TIMEOUT_SECONDS="${APT_LOCK_TIMEOUT_SECONDS:-900}"
ORCHESTRATION_KEYS_NOTICE_SHOWN=0

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

recover_systemd_services() {
    if [ "${RECOVER_SYSTEMD_SERVICES:-0}" = "1" ]; then
        printf 'Restoring OpenVision services after the failed deployment...\n' >&2
        sudo systemctl start openvision-backend openvision-celery openvision-celery-beat 2>/dev/null || true
    fi
}

die() {
    recover_systemd_services
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}

run_root() {
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

on_error() {
    local exit_code=$?
    trap - ERR
    recover_systemd_services
    printf '\nDeployment failed at line %s (exit %s).\n' "${BASH_LINENO[0]}" "$exit_code" >&2
    printf 'Inspect services with: sudo systemctl status openvision-backend openvision-celery openvision-celery-beat --no-pager\n' >&2
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

file_env_set() {
    local target_file="$1"
    local key="$2"
    local value="$3"
    touch "$target_file"
    if grep -q "^${key}=" "$target_file"; then
        sed -i "s#^${key}=.*#${key}=${value}#" "$target_file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$target_file"
    fi
}

file_env_get() {
    local target_file="$1"
    local key="$2"
    [ -f "$target_file" ] || return 0
    sed -n "s/^${key}=//p" "$target_file" | tail -n 1
}

mask_secret() {
    local value="${1:-}"
    if [ -z "$value" ]; then
        printf 'not saved'
    elif [ "${#value}" -le 12 ]; then
        printf 'saved (masked)'
    else
        printf '%s...%s' "${value:0:6}" "${value: -4}"
    fi
}

saved_omniroute_gateway_key() {
    local value=""
    value="$(file_env_get "$OMNIROUTE_ENV_FILE" OPENVISION_XCHAT_API_KEY)"
    if [ "$(detected_deployment_mode)" = "docker" ] && [ -f "$SCRIPT_DIR/.env" ]; then
        [ -n "$value" ] || value="$(file_env_get "$SCRIPT_DIR/.env" OMNIROUTE_API_KEY)"
    fi
    if [ -z "$value" ]; then
        value="$(file_env_get "$ENV_FILE" OMNIROUTE_API_KEY)"
    fi
    if [ -z "$value" ] && [ -f "$SCRIPT_DIR/.env" ]; then
        value="$(file_env_get "$SCRIPT_DIR/.env" OMNIROUTE_API_KEY)"
    fi
    printf '%s' "$value"
}

node_supports_omniroute() {
    local version="" major=0 minor=0 patch=0
    command -v node >/dev/null 2>&1 || return 1
    version="$(node --version 2>/dev/null || true)"
    if [[ "$version" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
        major="${BASH_REMATCH[1]}"
        minor="${BASH_REMATCH[2]}"
        patch="${BASH_REMATCH[3]}"
    else
        return 1
    fi
    if [ "$major" -eq 22 ]; then
        [ "$minor" -gt 22 ] || { [ "$minor" -eq 22 ] && [ "$patch" -ge 2 ]; }
        return
    fi
    [ "$major" -ge 24 ] && [ "$major" -lt 27 ]
}

install_omniroute_cli() {
    local npm_prefix=""
    if ! node_supports_omniroute; then
        log "Installing Node.js 24 for OmniRoute"
        run_root apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" update
        run_root env DEBIAN_FRONTEND=noninteractive apt-get \
            -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" install -y ca-certificates curl openssl
        if [ "$EUID" -eq 0 ]; then
            curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
        else
            curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
        fi
        run_root env DEBIAN_FRONTEND=noninteractive apt-get \
            -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" install -y nodejs
    fi
    node_supports_omniroute || die "OmniRoute requires Node.js >=22.22.2 <23 or >=24 <27"
    if ! command -v omniroute >/dev/null 2>&1; then
        log "Installing OmniRoute"
        npm_prefix="$(npm config get prefix)"
        if [ -d "$npm_prefix" ] && [ -w "$npm_prefix" ]; then
            npm install -g omniroute@latest
        else
            run_root npm install -g omniroute@latest
        fi
    fi
}

ensure_omniroute_secret() {
    local key="$1"
    local value="$2"
    [ -n "$(file_env_get "$OMNIROUTE_ENV_FILE" "$key")" ] \
        || file_env_set "$OMNIROUTE_ENV_FILE" "$key" "$value"
}

ensure_random_omniroute_secret() {
    local key="$1"
    local byte_count="$2"
    if [ -z "$(file_env_get "$OMNIROUTE_ENV_FILE" "$key")" ]; then
        file_env_set "$OMNIROUTE_ENV_FILE" "$key" "$(openssl rand -hex "$byte_count")"
    fi
}

configure_omniroute_secret_file() {
    local runtime_mode="$1"
    local initial_password="${INITIAL_PASSWORD:-}"
    local data_dir="$OMNIROUTE_DATA_DIR"
    local bind_host="127.0.0.1"

    command -v openssl >/dev/null 2>&1 || die "openssl is required to create OmniRoute secrets"
    touch "$OMNIROUTE_ENV_FILE"
    chmod 600 "$OMNIROUTE_ENV_FILE"

    ensure_random_omniroute_secret JWT_SECRET 32
    ensure_random_omniroute_secret API_KEY_SECRET 32
    if [ -z "$(file_env_get "$OMNIROUTE_ENV_FILE" INITIAL_PASSWORD)" ]; then
        initial_password="${initial_password:-$(openssl rand -hex 24)}"
        initial_password="$(printf '%s' "$initial_password" | tr -d '\r\n')"
        [ "${#initial_password}" -ge 16 ] || die "INITIAL_PASSWORD must contain at least 16 characters"
        file_env_set "$OMNIROUTE_ENV_FILE" INITIAL_PASSWORD "$initial_password"
    fi
    ensure_random_omniroute_secret STORAGE_ENCRYPTION_KEY 32
    ensure_omniroute_secret STORAGE_ENCRYPTION_KEY_VERSION "v1"
    ensure_random_omniroute_secret MACHINE_ID_SALT 32
    ensure_random_omniroute_secret OMNIROUTE_WS_BRIDGE_SECRET 32

    if [ "$runtime_mode" = "docker" ]; then
        data_dir="/app/data"
        bind_host="0.0.0.0"
    else
        mkdir -p "$OMNIROUTE_DATA_DIR"
        chmod 700 "$OMNIROUTE_DATA_DIR"
    fi
    file_env_set "$OMNIROUTE_ENV_FILE" PORT "20128"
    file_env_set "$OMNIROUTE_ENV_FILE" NODE_ENV "production"
    file_env_set "$OMNIROUTE_ENV_FILE" DATA_DIR "$data_dir"
    file_env_set "$OMNIROUTE_ENV_FILE" OMNIROUTE_SERVER_HOST "$bind_host"
    file_env_set "$OMNIROUTE_ENV_FILE" BASE_URL "http://127.0.0.1:20128"
    file_env_set "$OMNIROUTE_ENV_FILE" REQUIRE_API_KEY "true"
    file_env_set "$OMNIROUTE_ENV_FILE" ALLOW_API_KEY_REVEAL "false"
    file_env_set "$OMNIROUTE_ENV_FILE" AUTH_COOKIE_SECURE "false"
    file_env_set "$OMNIROUTE_ENV_FILE" APP_LOG_TO_FILE "true"
    file_env_set "$OMNIROUTE_ENV_FILE" OMNIROUTE_MEMORY_MB "1024"
    chmod 600 "$OMNIROUTE_ENV_FILE"
}

install_omniroute_systemd_service() {
    local omniroute_bin="" node_bin_dir=""
    [ "$RUN_USER" != "root" ] || die "Run configure-ai as the normal deployment user, not with sudo"
    install_omniroute_cli
    omniroute_bin="$(readlink -f "$(command -v omniroute)")"
    node_bin_dir="$(dirname "$(readlink -f "$(command -v node)")")"
    sudo tee "/etc/systemd/system/${OMNIROUTE_SERVICE}" >/dev/null <<UNIT
[Unit]
Description=OpenVision OmniRoute AI gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${SCRIPT_DIR}
Environment="PATH=${node_bin_dir}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=${OMNIROUTE_ENV_FILE}
ExecStart=${omniroute_bin} serve --no-open --no-tray --no-recovery
Restart=on-failure
RestartSec=5
TimeoutStopSec=40
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$OMNIROUTE_SERVICE"
}

extract_created_omniroute_key() {
    python3 -c '
import json
import sys

payload = sys.stdin.read()
decoder = json.JSONDecoder()
for offset, char in enumerate(payload):
    if char != "{":
        continue
    try:
        candidate, _ = decoder.raw_decode(payload, offset)
    except json.JSONDecodeError:
        continue
    if isinstance(candidate, dict) and isinstance(candidate.get("key"), str):
        key = candidate["key"].strip()
        if len(key) >= 20:
            print(key)
            raise SystemExit(0)
print("OmniRoute CLI did not return a usable API key", file=sys.stderr)
raise SystemExit(1)
'
}

provision_omniroute_gateway_key() {
    local runtime_mode="$1"
    local gateway_key="${OMNIROUTE_API_KEY:-}"
    local cli_output=""

    [ -n "$gateway_key" ] || gateway_key="$(saved_omniroute_gateway_key)"
    if [ -n "$gateway_key" ]; then
        if [ -z "$(file_env_get "$OMNIROUTE_ENV_FILE" OPENVISION_XCHAT_API_KEY)" ]; then
            file_env_set "$OMNIROUTE_ENV_FILE" OPENVISION_XCHAT_API_KEY "$gateway_key"
            chmod 600 "$OMNIROUTE_ENV_FILE"
        fi
        printf 'OmniRoute XChat key: reusing the saved key.\n'
        return 0
    fi

    log "Creating the OmniRoute XChat API key through the local CLI"
    if [ "$runtime_mode" = "docker" ]; then
        if ! cli_output="$(run_root docker compose --profile omniroute exec -T omniroute \
            env OMNIROUTE_BASE_URL=http://127.0.0.1:20128 \
            omniroute --output json --quiet --no-color api api-keys post-api-keys \
            --body '{"name":"OpenVision XChat"}' 2>&1)"; then
            die "OmniRoute local CLI could not create the XChat API key"
        fi
    else
        if ! cli_output="$(OMNIROUTE_BASE_URL=http://127.0.0.1:20128 \
            omniroute --output json --quiet --no-color api api-keys post-api-keys \
            --body '{"name":"OpenVision XChat"}' 2>&1)"; then
            die "OmniRoute local CLI could not create the XChat API key"
        fi
    fi
    gateway_key="$(printf '%s' "$cli_output" | extract_created_omniroute_key)"
    [[ "$gateway_key" =~ ^[A-Za-z0-9._-]{20,200}$ ]] \
        || die "OmniRoute returned an API key with an unexpected format"
    file_env_set "$OMNIROUTE_ENV_FILE" OPENVISION_XCHAT_API_KEY "$gateway_key"
    chmod 600 "$OMNIROUTE_ENV_FILE"
    printf 'OmniRoute XChat key: created once and saved for reuse.\n'
}

ensure_omniroute_gateway() {
    local runtime_mode="$1"
    local existing_gateway_key=""
    configure_omniroute_secret_file "$runtime_mode"
    if [ "$runtime_mode" = "docker" ]; then
        run_root docker compose --profile omniroute up -d omniroute
    else
        install_omniroute_systemd_service
    fi
    wait_for_url "http://127.0.0.1:20128/" 60 || die "OmniRoute did not become ready on loopback port 20128"
    if [ "$runtime_mode" = "bare" ]; then
        sudo systemctl is-active --quiet "$OMNIROUTE_SERVICE" || {
            sudo journalctl -u "$OMNIROUTE_SERVICE" -n 100 --no-pager || true
            die "The OmniRoute systemd service did not remain active"
        }
    fi
    provision_omniroute_gateway_key "$runtime_mode"
    existing_gateway_key="$(saved_omniroute_gateway_key)"
    [ -n "$existing_gateway_key" ] || die "OmniRoute XChat key provisioning did not persist a key"
    printf 'OmniRoute is running headlessly. Its generated secrets and XChat key are preserved in %s (mode 0600).\n' "$OMNIROUTE_ENV_FILE"
}

detected_deployment_mode() {
    local deployment_mode=""
    deployment_mode="$(sed -n '1p' "$MODE_FILE" 2>/dev/null || true)"
    if [[ "$deployment_mode" =~ ^(docker|bare)$ ]]; then
        printf '%s' "$deployment_mode"
    elif command -v docker >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/.env" ]; then
        printf 'docker'
    else
        printf 'bare'
    fi
}

show_omniroute_status() {
    local gateway_key="" initial_password="" service_state="not installed" runtime_mode="" xchat_env="$ENV_FILE"
    local fallback_providers="" fallback_display=""
    runtime_mode="$(detected_deployment_mode)"
    if [ "$runtime_mode" = "docker" ] && [ -f "$SCRIPT_DIR/.env" ]; then
        xchat_env="$SCRIPT_DIR/.env"
    fi
    gateway_key="$(saved_omniroute_gateway_key)"
    initial_password="$(file_env_get "$OMNIROUTE_ENV_FILE" INITIAL_PASSWORD)"
    fallback_providers="$(file_env_get "$xchat_env" XCHAT_FALLBACK_PROVIDERS)"
    fallback_display="${fallback_providers//,/ -> }"
    if [ "$runtime_mode" = "docker" ] && command -v docker >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        if [ -n "$(run_root docker compose --profile omniroute ps -q omniroute 2>/dev/null || true)" ]; then
            service_state="docker $(run_root docker compose --profile omniroute ps --status running -q omniroute 2>/dev/null | grep -q . && printf running || printf stopped)"
        fi
    elif command -v systemctl >/dev/null 2>&1 && systemctl cat "$OMNIROUTE_SERVICE" >/dev/null 2>&1; then
        service_state="$(systemctl is-active "$OMNIROUTE_SERVICE" 2>/dev/null || true)"
    fi
    printf 'OmniRoute CLI:       %s\n' "$(command -v omniroute >/dev/null 2>&1 && omniroute --version 2>/dev/null | head -n 1 || printf 'not installed')"
    printf 'OmniRoute service:   %s\n' "$service_state"
    printf 'Dashboard password: %s\n' "$([ -n "$initial_password" ] && printf 'generated and saved' || printf 'not generated')"
    printf 'XChat gateway key:   %s\n' "$(mask_secret "$gateway_key")"
    printf 'XChat provider chain: OmniRoute%s\n' "$([ -n "$fallback_display" ] && printf ' -> %s' "$fallback_display")"
    printf 'Protected secrets:   %s\n' "$OMNIROUTE_ENV_FILE"
    printf 'XChat environment:   %s\n' "$xchat_env"
}

configure_mail_file() {
    local target_file="$1"
    local app_password="$2"
    file_env_set "$target_file" MAIL_SMTP_HOST smtp.gmail.com
    file_env_set "$target_file" MAIL_SMTP_PORT 587
    file_env_set "$target_file" MAIL_SMTP_USERNAME openvisionx@gmail.com
    file_env_set "$target_file" MAIL_SMTP_APP_PASSWORD "$app_password"
    file_env_set "$target_file" MAIL_FROM_ADDRESS openvisionx@gmail.com
    file_env_set "$target_file" MAIL_FROM_NAME "OpenVisionX Reports"
    chmod 600 "$target_file"
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
    sudo systemctl stop openvision-backend openvision-celery openvision-celery-beat face-backend 2>/dev/null || true
}

install_boot_check_service() {
    sudo tee /etc/systemd/system/openvision-boot-check.service >/dev/null <<UNIT
[Unit]
Description=OpenVision post-boot startup and health check
After=network-online.target docker.service postgresql.service redis-server.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash ${SCRIPT_DIR}/setup_aws.sh boot-check
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable openvision-boot-check.service
}

prompt_mail_app_password() {
    local existing_value="${1:-}"
    local entered_value=""
    if [ -n "${MAIL_SMTP_APP_PASSWORD:-}" ]; then
        entered_value="$MAIL_SMTP_APP_PASSWORD"
    elif [ -n "$existing_value" ]; then
        entered_value="$existing_value"
    elif [ -t 0 ]; then
        printf '\nGmail SMTP setup (input is hidden)\n' >&2
        read -r -s -p "Paste the NEW Google App Password for openvisionx@gmail.com (Enter to skip): " entered_value
        printf '\n' >&2
    fi
    entered_value="$(printf '%s' "$entered_value" | tr -d '[:space:]')"
    if [ -n "$entered_value" ] && [[ ! "$entered_value" =~ ^[A-Za-z0-9]{16}$ ]]; then
        die "MAIL_SMTP_APP_PASSWORD must be the 16-character Google App Password, without spaces"
    fi
    printf '%s' "$entered_value"
}

prompt_xchat_provider() {
    local existing_value="${1:-}"
    local entered_value=""
    if [ -n "${XCHAT_PROVIDER:-}" ]; then
        entered_value="$XCHAT_PROVIDER"
    elif [ -t 0 ]; then
        existing_value="${existing_value,,}"
        [[ "$existing_value" =~ ^(gemini|mistral|groq|omniroute|none)$ ]] || existing_value="gemini"
        printf '\nXChat AI provider\n' >&2
        printf '  1) Gemini\n  2) Mistral\n  3) Groq (openai/gpt-oss-20b)\n  4) OmniRoute (auto routing/fallback)\n  5) Disabled\n' >&2
        read -r -p "Select provider (current/default: ${existing_value}): " entered_value
        entered_value="${entered_value:-$existing_value}"
    else
        entered_value="${existing_value:-none}"
    fi
    case "${entered_value,,}" in
        1|gemini) printf 'gemini' ;;
        2|mistral) printf 'mistral' ;;
        3|groq|grok) printf 'groq' ;;
        4|omniroute|omni-route|omni) printf 'omniroute' ;;
        5|none|disabled|off) printf 'none' ;;
        *) die "Choose Gemini, Mistral, Groq, OmniRoute, or Disabled for XChat" ;;
    esac
}

prompt_ai_api_key() {
    local provider_name="$1"
    local env_name="$2"
    local existing_value="${3:-}"
    local entered_value=""
    local supplied_value="${!env_name:-}"
    if [ -n "$supplied_value" ]; then
        entered_value="$supplied_value"
    elif [ -t 0 ]; then
        printf '\n%s XChat setup (input is hidden)\n' "$provider_name" >&2
        if [ -n "$existing_value" ]; then
            read -r -s -p "Press Enter to keep the saved ${provider_name} key, or paste a replacement: " entered_value
            entered_value="${entered_value:-$existing_value}"
        else
            read -r -s -p "Paste a NEW ${provider_name} API key: " entered_value
        fi
        printf '\n' >&2
    elif [ -n "$existing_value" ]; then
        entered_value="$existing_value"
    fi
    entered_value="$(printf '%s' "$entered_value" | tr -d '[:space:]')"
    if [ -n "$entered_value" ] && [[ ! "$entered_value" =~ ^[A-Za-z0-9._-]{20,200}$ ]]; then
        die "${env_name} has an unexpected format"
    fi
    printf '%s' "$entered_value"
}

prompt_mistral_api_key() {
    prompt_ai_api_key "Mistral" MISTRAL_API_KEY "${1:-}"
}

prompt_gemini_api_key() {
    prompt_ai_api_key "Gemini" GEMINI_API_KEY "${1:-}"
}

prompt_groq_api_key() {
    prompt_ai_api_key "Groq" GROQ_API_KEY "${1:-}"
}

prompt_omniroute_api_key() {
    local existing_value="${1:-}"
    local entered_value=""
    if [ -n "${OMNIROUTE_API_KEY:-}" ]; then
        entered_value="$OMNIROUTE_API_KEY"
    elif [ -n "$(file_env_get "$OMNIROUTE_ENV_FILE" OPENVISION_XCHAT_API_KEY)" ]; then
        entered_value="$(file_env_get "$OMNIROUTE_ENV_FILE" OPENVISION_XCHAT_API_KEY)"
    elif [ -n "$existing_value" ]; then
        entered_value="$existing_value"
    fi
    entered_value="$(printf '%s' "$entered_value" | tr -d '[:space:]')"
    if [ -n "$entered_value" ] && [[ ! "$entered_value" =~ ^[A-Za-z0-9._-]{20,200}$ ]]; then
        die "OMNIROUTE_API_KEY has an unexpected format"
    fi
    printf '%s' "$entered_value"
}

prepare_ai_provider_keys_file() {
    [ -e "$AI_PROVIDER_KEYS_FILE" ] || return 0
    [ -f "$AI_PROVIDER_KEYS_FILE" ] || die "AI provider keys path is not a regular file: $AI_PROVIDER_KEYS_FILE"
    chmod 600 "$AI_PROVIDER_KEYS_FILE" \
        || die "Unable to protect $AI_PROVIDER_KEYS_FILE; make it owned by $RUN_USER and rerun setup"
    [ "$(stat -c '%a' "$AI_PROVIDER_KEYS_FILE")" = "600" ] \
        || die "$AI_PROVIDER_KEYS_FILE must have file mode 0600"
}

validate_orchestration_key() {
    local key_name="$1"
    local value="$2"
    [[ "$value" =~ ^[A-Za-z0-9._-]{20,300}$ ]] \
        || die "$key_name in $AI_PROVIDER_KEYS_FILE has an unexpected format"
}

configure_orchestration_file() {
    local target_file="$1"
    local provider_name="$2"
    local key_name="" value=""
    local imported=()

    file_env_set "$target_file" XCHAT_FALLBACK_PROVIDERS "groq,gemini,cerebras"
    file_env_set "$target_file" XCHAT_ORCHESTRATION_PROVIDER_RETRIES "0"
    [ "$provider_name" = "omniroute" ] || return 0
    prepare_ai_provider_keys_file
    [ -f "$AI_PROVIDER_KEYS_FILE" ] || return 0

    for key_name in GROQ_API_KEY GEMINI_API_KEY CEREBRAS_API_KEY; do
        value="$(file_env_get "$AI_PROVIDER_KEYS_FILE" "$key_name" | tr -d '\r\n')"
        [ -n "$value" ] || continue
        validate_orchestration_key "$key_name" "$value"
        file_env_set "$target_file" "$key_name" "$value"
        imported+=("${key_name%_API_KEY}")
    done
    if [ "${#imported[@]}" -eq 0 ] \
        && grep -Eq '^[[:space:]]*[^#[:space:]].*$' "$AI_PROVIDER_KEYS_FILE"; then
        die "$AI_PROVIDER_KEYS_FILE contains no supported KEY=value entries; use ai-provider-keys.env.example"
    fi
    chmod 600 "$target_file"
    if [ "${#imported[@]}" -gt 0 ] && [ "$ORCHESTRATION_KEYS_NOTICE_SHOWN" -eq 0 ]; then
        printf 'XChat fallback keys imported securely for: %s.\n' "$(IFS=,; printf '%s' "${imported[*]}")"
        ORCHESTRATION_KEYS_NOTICE_SHOWN=1
    fi
}

configure_ai_file() {
    local target_file="$1"
    local provider_name="$2"
    local api_key="$3"
    file_env_set "$target_file" XCHAT_PROVIDER "$provider_name"
    file_env_set "$target_file" MISTRAL_MODEL "mistral-small-latest"
    file_env_set "$target_file" MISTRAL_TIMEOUT_SECONDS "30"
    file_env_set "$target_file" MISTRAL_MAX_RETRIES "2"
    file_env_set "$target_file" GEMINI_MODEL "gemini-3.8-flash"
    file_env_set "$target_file" GEMINI_TIMEOUT_SECONDS "30"
    file_env_set "$target_file" GEMINI_MAX_RETRIES "2"
    file_env_set "$target_file" GROQ_MODEL "openai/gpt-oss-20b"
    file_env_set "$target_file" GROQ_TIMEOUT_SECONDS "30"
    file_env_set "$target_file" GROQ_MAX_RETRIES "2"
    file_env_set "$target_file" GROQ_REASONING_EFFORT "low"
    file_env_set "$target_file" GROQ_MAX_OUTPUT_TOKENS "450"
    file_env_set "$target_file" CEREBRAS_MODEL "gpt-oss-120b"
    file_env_set "$target_file" CEREBRAS_API_URL "https://api.cerebras.ai/v1/chat/completions"
    file_env_set "$target_file" CEREBRAS_TIMEOUT_SECONDS "30"
    file_env_set "$target_file" CEREBRAS_MAX_RETRIES "2"
    file_env_set "$target_file" CEREBRAS_MAX_OUTPUT_TOKENS "700"
    file_env_set "$target_file" OMNIROUTE_MODEL "auto"
    file_env_set "$target_file" OMNIROUTE_TIMEOUT_SECONDS "60"
    file_env_set "$target_file" OMNIROUTE_MAX_RETRIES "0"
    file_env_set "$target_file" OMNIROUTE_MAX_OUTPUT_TOKENS "700"
    if [ "$provider_name" = "gemini" ]; then
        file_env_set "$target_file" GEMINI_API_KEY "$api_key"
    elif [ "$provider_name" = "mistral" ]; then
        file_env_set "$target_file" MISTRAL_API_KEY "$api_key"
    elif [ "$provider_name" = "groq" ]; then
        file_env_set "$target_file" GROQ_API_KEY "$api_key"
    elif [ "$provider_name" = "omniroute" ]; then
        file_env_set "$target_file" OMNIROUTE_API_KEY "$api_key"
    fi
    configure_orchestration_file "$target_file" "$provider_name"
    file_env_set "$target_file" XCHAT_HISTORY_DAYS "30"
    file_env_set "$target_file" XCHAT_MAX_MESSAGES "200"
    chmod 600 "$target_file"
}

existing_xchat_provider() {
    local target_file="$1"
    local configured_provider=""
    configured_provider="$(file_env_get "$target_file" XCHAT_PROVIDER)"
    if [[ "${configured_provider,,}" =~ ^(gemini|mistral|groq|omniroute|none)$ ]]; then
        printf '%s' "${configured_provider,,}"
    elif [ -n "$(file_env_get "$target_file" OMNIROUTE_API_KEY)" ]; then
        printf 'omniroute'
    elif [ -n "$(file_env_get "$target_file" GROQ_API_KEY)" ]; then
        printf 'groq'
    elif [ -n "$(file_env_get "$target_file" GEMINI_API_KEY)" ]; then
        printf 'gemini'
    elif [ -n "$(file_env_get "$target_file" MISTRAL_API_KEY)" ]; then
        printf 'mistral'
    else
        printf 'gemini'
    fi
}

selected_ai_key() {
    local provider_name="$1"
    local target_file="$2"
    case "$provider_name" in
        gemini) prompt_gemini_api_key "$(file_env_get "$target_file" GEMINI_API_KEY)" ;;
        mistral) prompt_mistral_api_key "$(file_env_get "$target_file" MISTRAL_API_KEY)" ;;
        groq) prompt_groq_api_key "$(file_env_get "$target_file" GROQ_API_KEY)" ;;
        omniroute) prompt_omniroute_api_key "$(file_env_get "$target_file" OMNIROUTE_API_KEY)" ;;
        none) printf '' ;;
    esac
}

selected_ai_model() {
    case "$1" in
        gemini) printf 'gemini-3.8-flash' ;;
        mistral) printf 'mistral-small-latest' ;;
        groq) printf 'openai/gpt-oss-20b' ;;
        omniroute) printf 'auto' ;;
        none) printf '' ;;
    esac
}

prompt_stt_enabled() {
    local existing_value="${1:-}"
    local entered_value=""
    if [ -n "${STT_ENABLED:-}" ]; then
        entered_value="$STT_ENABLED"
    elif [ -t 0 ]; then
        printf '\nXChat local microphone setup\n' >&2
        read -r -p "Enable local Whisper base voice input on this server? (Y/n): " entered_value
        entered_value="${entered_value:-y}"
    else
        entered_value="${existing_value:-false}"
    fi
    case "${entered_value,,}" in
        y|yes|1|true|on) printf 'true' ;;
        n|no|0|false|off) printf 'false' ;;
        *) die "Answer y or n when asked whether to enable local Whisper" ;;
    esac
}

configure_stt_file() {
    local target_file="$1"
    local enabled_value="$2"
    file_env_set "$target_file" STT_ENABLED "$enabled_value"
    file_env_set "$target_file" STT_MODEL base
    file_env_set "$target_file" STT_CPU_THREADS 1
    file_env_set "$target_file" STT_MAX_AUDIO_SECONDS 20
    file_env_set "$target_file" STT_MAX_AUDIO_BYTES 2500000
    file_env_set "$target_file" STT_VAD_MIN_SILENCE_MS 500
}

verify_stt_health() {
    local url="$1"
    local enabled_value="$2"
    [ "$enabled_value" = "true" ] || return 0
    if ! curl --fail --silent --show-error --max-time 10 "$url" \
        | python3 -c 'import json, sys; data=json.load(sys.stdin); sys.exit(0 if data.get("stt", {}).get("ready") is True else 1)'; then
        return 1
    fi
    printf 'Local Whisper microphone: enabled and ready.\n'
}

verify_ai_access() {
    local provider_name="$1"
    local api_key="$2"
    local model_name="$3"
    [ -n "$api_key" ] || [ "$provider_name" = "omniroute" ] || return 0
    AI_PROVIDER="$provider_name" AI_API_KEY="$api_key" AI_MODEL="$model_name" AI_API_URL="${OMNIROUTE_API_URL:-}" python3 - <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request

provider = os.environ["AI_PROVIDER"]
api_key = os.environ["AI_API_KEY"]
model = os.environ["AI_MODEL"]
if provider == "gemini":
    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
    headers = {"x-goog-api-key": api_key}
    request = urllib.request.Request(url, method="GET", headers=headers)
elif provider == "groq":
    # Some valid Groq keys are denied access to the model-list endpoint even
    # though they can use the configured model. Validate the route XChat uses.
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply OK."}],
    }).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        # Groq's Cloudflare policy rejects urllib's default Python-urllib UA
        # with error 1010 before the request reaches API authentication.
        "User-Agent": "OpenVisionX/1.0",
    }
    request = urllib.request.Request(url, data=payload, method="POST", headers=headers)
elif provider == "omniroute":
    url = os.environ.get("AI_API_URL") or "http://127.0.0.1:20128/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply OK."}],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "OpenVisionX/1.0"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(url, data=payload, method="POST", headers=headers)
elif provider == "cerebras":
    url = "https://api.cerebras.ai/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply OK."}],
    }).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "User-Agent": "OpenVisionX/1.0",
    }
    request = urllib.request.Request(url, data=payload, method="POST", headers=headers)
else:
    url = "https://api.mistral.ai/v1/models"
    headers = {"Authorization": "Bearer " + api_key}
    request = urllib.request.Request(url, method="GET", headers=headers)

for attempt in range(3):
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        if provider in {"groq", "omniroute", "cerebras"}:
            if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
                raise RuntimeError(f"{provider} returned no completion choices")
            print(f"{provider.title()} API: configured model accepted by chat completions.")
            raise SystemExit(0)
        if isinstance(data, dict):
            cards = data.get("models", []) if provider == "gemini" else data.get("data", [])
        else:
            cards = data
        identifiers = set()
        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            identifiers.update(str(card.get(field) or "") for field in ("id", "root", "name", "baseModelId"))
            aliases = card.get("aliases") or []
            identifiers.update(str(alias) for alias in aliases if alias)
        identifiers.update(identifier.removeprefix("models/") for identifier in tuple(identifiers))
        if model not in identifiers:
            raise RuntimeError(f"configured model {model} is not available to this key")
        print(f"{provider.title()} API: key accepted and configured model is available.")
        raise SystemExit(0)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            error = json.loads(body)
            if isinstance(error, dict) and isinstance(error.get("error"), dict):
                error = error["error"]
            detail = error.get("message") or error.get("status") or error.get("code") or error.get("type") or "request rejected"
        except Exception:
            detail = body or "request rejected"
        detail = " ".join(str(detail).split())[:240]
        if api_key:
            detail = detail.replace(api_key, "[redacted]")
        if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
            time.sleep(2 ** attempt)
            continue
        if exc.code in {429, 500, 502, 503, 504}:
            print(f"{provider.title()} API preflight deferred: HTTP {exc.code}: {detail}", file=sys.stderr)
            raise SystemExit(75)
        print(f"{provider.title()} API validation failed: HTTP {exc.code}: {detail}", file=sys.stderr)
        raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError) as exc:
        if attempt < 2:
            time.sleep(2 ** attempt)
            continue
        print(f"{provider.title()} API preflight deferred: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(75)
    except Exception as exc:
        print(f"{provider.title()} API validation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
PY
}

validate_orchestration_fallbacks() {
    local target_file="$1"
    local provider_name="$2"
    local fallback_name="" key_name="" model_name="" key_value="" validation_status=0
    local enabled=()
    [ "$provider_name" = "omniroute" ] || return 0

    for fallback_name in groq gemini cerebras; do
        case "$fallback_name" in
            groq)
                key_name="GROQ_API_KEY"
                model_name="$(file_env_get "$target_file" GROQ_MODEL)"
                ;;
            gemini)
                key_name="GEMINI_API_KEY"
                model_name="$(file_env_get "$target_file" GEMINI_MODEL)"
                ;;
            cerebras)
                key_name="CEREBRAS_API_KEY"
                model_name="$(file_env_get "$target_file" CEREBRAS_MODEL)"
                ;;
        esac
        key_value="$(file_env_get "$target_file" "$key_name")"
        [ -n "$key_value" ] || continue
        if verify_ai_access "$fallback_name" "$key_value" "$model_name"; then
            enabled+=("$fallback_name")
            continue
        else
            validation_status=$?
        fi
        if [ "$validation_status" -eq 75 ]; then
            printf 'WARNING: %s fallback preflight was deferred; keeping it in the chain.\n' "$fallback_name" >&2
            enabled+=("$fallback_name")
        else
            printf 'WARNING: %s fallback validation failed; excluding it until the next successful setup run.\n' "$fallback_name" >&2
        fi
    done
    file_env_set "$target_file" XCHAT_FALLBACK_PROVIDERS "$(IFS=,; printf '%s' "${enabled[*]}")"
}

validate_ai_for_deploy() {
    local provider_name="$1"
    local api_key="$2"
    local model_name="$3"
    local validation_status=0
    if verify_ai_access "$provider_name" "$api_key" "$model_name"; then
        return 0
    else
        validation_status=$?
    fi
    if [ "$validation_status" -eq 75 ]; then
        printf 'WARNING: Continuing deployment because %s is rate-limited or temporarily unavailable.\n' "$provider_name" >&2
        printf 'XChat will recover without redeployment when the provider quota/service recovers.\n' >&2
        return 0
    fi
    die "${provider_name} API validation failed; correct the key/account shown above and rerun setup"
}

frontend_dependency_fingerprint() {
    (
        cd "$SCRIPT_DIR/web-dashboard"
        {
            node --version
            npm --version
            sha256sum package.json package-lock.json
        } | sha256sum | awk '{print $1}'
    )
}

frontend_source_fingerprint() {
    local dependency_fingerprint="$1"
    (
        cd "$SCRIPT_DIR/web-dashboard"
        {
            printf '%s\n' "$dependency_fingerprint" "${VITE_API_URL:-}"
            find src public -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
            for source_file in index.html vite.config.js postcss.config.js package.json package-lock.json; do
                [ ! -f "$source_file" ] || sha256sum "$source_file"
            done
            for env_file in .env.production .env.production.local; do
                [ ! -f "$env_file" ] || sha256sum "$env_file"
            done
        } | sha256sum | awk '{print $1}'
    )
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

if [ "$ACTION" = "omniroute-status" ]; then
    show_omniroute_status
    exit 0
fi

if [ "$ACTION" = "omniroute-password" ]; then
    OMNIROUTE_SAVED_PASSWORD="$(file_env_get "$OMNIROUTE_ENV_FILE" INITIAL_PASSWORD)"
    [ -n "$OMNIROUTE_SAVED_PASSWORD" ] || die "OmniRoute dashboard password has not been generated; select OmniRoute with configure-ai first"
    printf 'Warning: this prints the dashboard password to your terminal. Do not paste it into logs or chat.\n' >&2
    printf '%s\n' "$OMNIROUTE_SAVED_PASSWORD"
    exit 0
fi

if [ "$ACTION" = "omniroute-key" ]; then
    OMNIROUTE_SAVED_KEY="$(saved_omniroute_gateway_key)"
    [ -n "$OMNIROUTE_SAVED_KEY" ] || die "No OmniRoute XChat gateway key is saved; run setup or configure-ai and select OmniRoute"
    printf 'Warning: this prints the XChat gateway key to your terminal. Do not paste it into logs or chat.\n' >&2
    printf '%s\n' "$OMNIROUTE_SAVED_KEY"
    exit 0
fi

if [ "$ACTION" = "stop" ]; then
    log "Stopping OpenVision application services"
    stop_application_services
    sudo systemctl stop "$OMNIROUTE_SERVICE" 2>/dev/null || true
    if command -v docker >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        sudo docker compose --profile omniroute stop api worker beat omniroute 2>/dev/null || true
    fi
    printf 'OpenVision API, worker services, and its OmniRoute gateway are stopped. PostgreSQL, Redis, Nginx, and unrelated containers were left running.\n'
    exit 0
fi

if [ "$ACTION" = "boot-check" ]; then
    require_source_tree
    DEPLOYMENT_MODE="$(sed -n '1p' "$MODE_FILE" 2>/dev/null || true)"
    if [ "$DEPLOYMENT_MODE" = "docker" ]; then
        [ -f "$SCRIPT_DIR/.env" ] || die "Docker environment file is missing"
        if [ "$(file_env_get "$SCRIPT_DIR/.env" XCHAT_PROVIDER)" = "omniroute" ]; then
            [ -f "$OMNIROUTE_ENV_FILE" ] || die "OmniRoute secrets file is missing; restore it instead of generating replacement encryption secrets"
            run_root docker compose --profile omniroute up -d --remove-orphans
            wait_for_url "http://127.0.0.1:20128/" 60 || die "OmniRoute failed its post-boot health check"
        else
            run_root docker compose up -d --remove-orphans
        fi
    elif [ "$DEPLOYMENT_MODE" = "bare" ]; then
        run_root systemctl start postgresql redis-server nginx
        if [ "$(file_env_get "$ENV_FILE" XCHAT_PROVIDER)" = "omniroute" ]; then
            [ -f "$OMNIROUTE_ENV_FILE" ] || die "OmniRoute secrets file is missing; restore it instead of generating replacement encryption secrets"
            run_root systemctl start "$OMNIROUTE_SERVICE"
            wait_for_url "http://127.0.0.1:20128/" 60 || die "OmniRoute failed its post-boot health check"
        fi
        run_root systemctl start openvision-backend openvision-celery openvision-celery-beat
    else
        die "Deployment mode is unknown; run setup_aws.sh once to install OpenVision"
    fi
    wait_for_url "http://127.0.0.1:5001/api/health" 60 || die "OpenVision API failed its post-boot health check"
    printf 'OpenVision %s deployment is running and healthy.\n' "$DEPLOYMENT_MODE"
    exit 0
fi

if [ "$ACTION" = "configure-mail" ]; then
    require_source_tree
    SMTP_APP_PASSWORD="$(prompt_mail_app_password "")"
    [ -n "$SMTP_APP_PASSWORD" ] || die "A Google App Password is required"
    configure_mail_file "$ENV_FILE" "$SMTP_APP_PASSWORD"
    if [ -f "$SCRIPT_DIR/.env" ]; then
        configure_mail_file "$SCRIPT_DIR/.env" "$SMTP_APP_PASSWORD"
    fi

    if command -v docker >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/.env" ] && [ -n "$(sudo docker compose ps -q api 2>/dev/null || true)" ]; then
        sudo docker compose up -d --no-deps --force-recreate api worker beat
        printf 'Gmail SMTP configured; Docker API, worker, and Beat services restarted.\n'
    elif command -v systemctl >/dev/null 2>&1 && systemctl cat openvision-backend.service >/dev/null 2>&1; then
        sudo systemctl restart openvision-backend openvision-celery openvision-celery-beat
        printf 'Gmail SMTP configured; OpenVision API, worker, and Beat services restarted.\n'
    else
        printf 'Gmail SMTP configured in backend/.env. Start or redeploy the OpenVision services to apply it.\n'
    fi
    exit 0
fi

if [ "$ACTION" = "configure-ai" ]; then
    require_source_tree
    AI_RUNTIME_MODE="$(detected_deployment_mode)"
    AI_CONFIG_FILE="$ENV_FILE"
    if [ "$AI_RUNTIME_MODE" = "docker" ] && [ -f "$SCRIPT_DIR/.env" ]; then
        AI_CONFIG_FILE="$SCRIPT_DIR/.env"
    fi
    AI_PROVIDER="$(prompt_xchat_provider "$(existing_xchat_provider "$AI_CONFIG_FILE")")"
    if [ "$AI_PROVIDER" = "omniroute" ]; then
        ensure_omniroute_gateway "$AI_RUNTIME_MODE"
    fi
    AI_KEY="$(selected_ai_key "$AI_PROVIDER" "$AI_CONFIG_FILE")"
    AI_MODEL="$(selected_ai_model "$AI_PROVIDER")"
    if [ "$AI_PROVIDER" != "none" ]; then
        [ -n "$AI_KEY" ] || die "An API key is required for ${AI_PROVIDER}"
        validate_ai_for_deploy "$AI_PROVIDER" "$AI_KEY" "$AI_MODEL"
    fi
    configure_ai_file "$ENV_FILE" "$AI_PROVIDER" "$AI_KEY"
    if [ -f "$SCRIPT_DIR/.env" ]; then
        configure_ai_file "$SCRIPT_DIR/.env" "$AI_PROVIDER" "$AI_KEY"
    fi
    validate_orchestration_fallbacks "$AI_CONFIG_FILE" "$AI_PROVIDER"
    ACTIVE_FALLBACK_PROVIDERS="$(file_env_get "$AI_CONFIG_FILE" XCHAT_FALLBACK_PROVIDERS)"
    file_env_set "$ENV_FILE" XCHAT_FALLBACK_PROVIDERS "$ACTIVE_FALLBACK_PROVIDERS"
    if [ -f "$SCRIPT_DIR/.env" ]; then
        file_env_set "$SCRIPT_DIR/.env" XCHAT_FALLBACK_PROVIDERS "$ACTIVE_FALLBACK_PROVIDERS"
    fi
    if command -v docker >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/.env" ] && [ -n "$(sudo docker compose ps -q api 2>/dev/null || true)" ]; then
        sudo docker compose up -d --no-deps --force-recreate api
        printf 'XChat provider set to %s; Docker API restarted.\n' "$AI_PROVIDER"
    elif command -v systemctl >/dev/null 2>&1 && systemctl cat openvision-backend.service >/dev/null 2>&1; then
        sudo systemctl restart openvision-backend
        printf 'XChat provider set to %s; OpenVision API restarted.\n' "$AI_PROVIDER"
    else
        printf 'XChat provider set to %s in backend/.env. Start or redeploy the API to apply it.\n' "$AI_PROVIDER"
    fi
    exit 0
fi

[ "$ACTION" = "setup" ] || die "Unknown command '$ACTION'. Use setup, check, stop, boot-check, configure-mail, configure-ai, omniroute-status, omniroute-password, or omniroute-key."
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
        sudo apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" update
        sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" install -y ca-certificates curl gnupg lsb-release
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
        printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
            "$(dpkg --print-architecture)" "$(lsb_release -cs)" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
        sudo apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" update
        sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    fi

    ROOT_ENV="$SCRIPT_DIR/.env"
    touch "$ROOT_ENV"
    chmod 600 "$ROOT_ENV"
    grep -q '^DB_PASSWORD=' "$ROOT_ENV" || printf 'DB_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> "$ROOT_ENV"
    grep -q '^REDIS_PASSWORD=' "$ROOT_ENV" || printf 'REDIS_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> "$ROOT_ENV"
    grep -q '^SECRET_KEY=' "$ROOT_ENV" || printf 'SECRET_KEY=%s\n' "$(openssl rand -hex 32)" >> "$ROOT_ENV"
    EXISTING_MAIL_PASSWORD="$(sed -n 's/^MAIL_SMTP_APP_PASSWORD=//p' "$ROOT_ENV" | tail -n 1)"
    SMTP_APP_PASSWORD="$(prompt_mail_app_password "$EXISTING_MAIL_PASSWORD")"
    if [ -n "$SMTP_APP_PASSWORD" ]; then
        if grep -q '^MAIL_SMTP_APP_PASSWORD=' "$ROOT_ENV"; then
            sed -i "s#^MAIL_SMTP_APP_PASSWORD=.*#MAIL_SMTP_APP_PASSWORD=${SMTP_APP_PASSWORD}#" "$ROOT_ENV"
        else
            printf 'MAIL_SMTP_APP_PASSWORD=%s\n' "$SMTP_APP_PASSWORD" >> "$ROOT_ENV"
        fi
    else
        printf 'WARNING: Gmail App Password was not configured; automated report emails will remain unavailable.\n' >&2
    fi
    grep -q '^MAIL_SMTP_USERNAME=' "$ROOT_ENV" || printf 'MAIL_SMTP_USERNAME=openvisionx@gmail.com\n' >> "$ROOT_ENV"
    grep -q '^MAIL_FROM_ADDRESS=' "$ROOT_ENV" || printf 'MAIL_FROM_ADDRESS=openvisionx@gmail.com\n' >> "$ROOT_ENV"
    STT_ENABLED_VALUE="$(prompt_stt_enabled "$(file_env_get "$ROOT_ENV" STT_ENABLED)")"
    configure_stt_file "$ROOT_ENV" "$STT_ENABLED_VALUE"
    AI_PROVIDER="$(prompt_xchat_provider "$(existing_xchat_provider "$ROOT_ENV")")"
    if [ "$AI_PROVIDER" = "omniroute" ]; then
        ensure_omniroute_gateway docker
    fi
    AI_KEY="$(selected_ai_key "$AI_PROVIDER" "$ROOT_ENV")"
    AI_MODEL="$(selected_ai_model "$AI_PROVIDER")"
    if [ "$AI_PROVIDER" != "none" ]; then
        [ -n "$AI_KEY" ] || die "An API key is required for ${AI_PROVIDER}"
        validate_ai_for_deploy "$AI_PROVIDER" "$AI_KEY" "$AI_MODEL"
    fi
    configure_ai_file "$ROOT_ENV" "$AI_PROVIDER" "$AI_KEY"
    validate_orchestration_fallbacks "$ROOT_ENV" "$AI_PROVIDER"

    sudo docker compose config --quiet
    if [ "$AI_PROVIDER" = "omniroute" ]; then
        sudo docker compose --profile omniroute up -d --build --remove-orphans --scale worker=1
    else
        sudo docker compose up -d --build --remove-orphans --scale worker=1
    fi
    HEALTH_ATTEMPTS=45
    [ "$STT_ENABLED_VALUE" = "true" ] && HEALTH_ATTEMPTS=300
    wait_for_url "http://127.0.0.1:5001/api/health" "$HEALTH_ATTEMPTS" || die "Docker API did not become healthy"
    verify_stt_health "http://127.0.0.1:5001/api/health" "$STT_ENABLED_VALUE" || {
        sudo docker compose logs --tail=100 api || true
        die "Local Whisper was enabled but did not become ready"
    }
    printf 'docker\n' > "$MODE_FILE"
    chmod 600 "$MODE_FILE"
    install_boot_check_service
    printf '\nDocker API deployment completed successfully at http://%s:5001\n' "$(hostname -I | awk '{print $1}')"
    exit 0
fi

log "Selected safe bare-metal deployment"
RECOVER_SYSTEMD_SERVICES=1
sudo -n true || die "Passwordless sudo is required for unattended AWS installation. Configure the deployment user in sudoers, then rerun."

log "Installing operating-system dependencies"
printf 'Package-manager lock wait timeout: %s seconds.\n' "$APT_LOCK_TIMEOUT_SECONDS"
sudo apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" update
sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" install -y \
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
    sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT_SECONDS" install -y nodejs
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
SMTP_APP_PASSWORD="$(prompt_mail_app_password "$(env_get MAIL_SMTP_APP_PASSWORD)")"
AI_PROVIDER="$(prompt_xchat_provider "$(existing_xchat_provider "$ENV_FILE")")"
if [ "$AI_PROVIDER" = "omniroute" ]; then
    ensure_omniroute_gateway bare
fi
AI_KEY="$(selected_ai_key "$AI_PROVIDER" "$ENV_FILE")"
AI_MODEL="$(selected_ai_model "$AI_PROVIDER")"
if [ "$AI_PROVIDER" != "none" ]; then
    [ -n "$AI_KEY" ] || die "An API key is required for ${AI_PROVIDER}"
    validate_ai_for_deploy "$AI_PROVIDER" "$AI_KEY" "$AI_MODEL"
fi

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
STT_ENABLED_VALUE="$(prompt_stt_enabled "$(env_get STT_ENABLED)")"
configure_stt_file "$ENV_FILE" "$STT_ENABLED_VALUE"
env_set MAIL_SMTP_HOST "smtp.gmail.com"
env_set MAIL_SMTP_PORT "587"
env_set MAIL_SMTP_USERNAME "openvisionx@gmail.com"
env_set MAIL_FROM_ADDRESS "openvisionx@gmail.com"
env_set MAIL_FROM_NAME "OpenVisionX Reports"
if [ -n "$SMTP_APP_PASSWORD" ]; then
    env_set MAIL_SMTP_APP_PASSWORD "$SMTP_APP_PASSWORD"
else
    printf 'WARNING: Gmail App Password was not configured; automated report emails will remain unavailable.\n' >&2
fi
configure_ai_file "$ENV_FILE" "$AI_PROVIDER" "$AI_KEY"
validate_orchestration_fallbacks "$ENV_FILE" "$AI_PROVIDER"
chmod 600 "$ENV_FILE"

log "Stopping only existing OpenVision application services"
stop_application_services
if sudo lsof -nP -iTCP:5001 -sTCP:LISTEN >/dev/null 2>&1; then
    sudo lsof -nP -iTCP:5001 -sTCP:LISTEN || true
    die "Port 5001 is occupied by a process outside the OpenVision systemd services"
fi

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
    FRONTEND_CACHE_DIR="$SCRIPT_DIR/.openvision-cache"
    DEPENDENCY_STAMP="$FRONTEND_CACHE_DIR/frontend-dependencies.sha256"
    BUILD_STAMP="$FRONTEND_CACHE_DIR/frontend-build.sha256"
    mkdir -p "$FRONTEND_CACHE_DIR"

    DEPENDENCY_FINGERPRINT="$(frontend_dependency_fingerprint)"
    REUSED_DEPENDENCIES=0
    if [ -x node_modules/.bin/vite ] \
        && [ "$(sed -n '1p' "$DEPENDENCY_STAMP" 2>/dev/null || true)" = "$DEPENDENCY_FINGERPRINT" ]; then
        printf 'Frontend dependencies unchanged; reusing node_modules.\n'
        REUSED_DEPENDENCIES=1
    else
        npm ci --legacy-peer-deps --prefer-offline --no-audit
        printf '%s\n' "$DEPENDENCY_FINGERPRINT" > "$DEPENDENCY_STAMP"
    fi

    BUILD_FINGERPRINT="$(frontend_source_fingerprint "$DEPENDENCY_FINGERPRINT")"
    if [ -f dist/index.html ] && [ -d dist/assets ] \
        && [ "$(sed -n '1p' "$BUILD_STAMP" 2>/dev/null || true)" = "$BUILD_FINGERPRINT" ]; then
        printf 'Frontend sources unchanged; reusing the verified dashboard build.\n'
    else
        if ! NODE_OPTIONS="--max-old-space-size=1536" npm run build; then
            if [ "$REUSED_DEPENDENCIES" -ne 1 ]; then
                exit 1
            fi
            printf 'Cached frontend dependencies failed; rebuilding them once.\n'
            npm ci --legacy-peer-deps --prefer-offline --no-audit
            printf '%s\n' "$DEPENDENCY_FINGERPRINT" > "$DEPENDENCY_STAMP"
            NODE_OPTIONS="--max-old-space-size=1536" npm run build
        fi
        printf '%s\n' "$BUILD_FINGERPRINT" > "$BUILD_STAMP"
    fi
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

sudo tee /etc/systemd/system/openvision-celery-beat.service >/dev/null <<UNIT
[Unit]
Description=OpenVision Celery Beat Scheduler
After=network-online.target redis-server.service openvision-celery.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${SCRIPT_DIR}/backend
Environment="PATH=${SCRIPT_DIR}/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=${SCRIPT_DIR}/backend:${SCRIPT_DIR}"
EnvironmentFile=${ENV_FILE}
ExecStart=${SCRIPT_DIR}/backend/.venv/bin/celery -A celery_app.celery beat --loglevel=info --schedule=/tmp/openvision-celerybeat-schedule
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
sudo systemctl enable openvision-backend openvision-celery openvision-celery-beat
sudo systemctl restart openvision-backend openvision-celery openvision-celery-beat
sudo systemctl is-active --quiet openvision-backend
sudo systemctl is-active --quiet openvision-celery
sudo systemctl is-active --quiet openvision-celery-beat

printf 'bare\n' > "$MODE_FILE"
chmod 600 "$MODE_FILE"
install_boot_check_service

log "Running deployment health checks"
HEALTH_ATTEMPTS=45
[ "$STT_ENABLED_VALUE" = "true" ] && HEALTH_ATTEMPTS=300
wait_for_url "http://127.0.0.1:5001/api/health" "$HEALTH_ATTEMPTS" || {
    sudo journalctl -u openvision-backend -n 100 --no-pager || true
    die "OpenVision API did not become healthy"
}
verify_stt_health "http://127.0.0.1:5001/api/health" "$STT_ENABLED_VALUE" || {
    sudo journalctl -u openvision-backend -n 100 --no-pager || true
    die "Local Whisper was enabled but did not become ready"
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
            sudo systemctl restart openvision-backend openvision-celery openvision-celery-beat
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

RECOVER_SYSTEMD_SERVICES=0

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
printf 'Services:     sudo systemctl status openvision-backend openvision-celery openvision-celery-beat nginx\n'
printf 'Application logs: sudo journalctl -u openvision-backend -f\n'
