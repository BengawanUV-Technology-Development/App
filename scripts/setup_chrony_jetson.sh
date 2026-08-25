#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  setup_chrony_jetson.sh --ground-ip <ip>

Configure the Jetson as a chrony client of the Ground laptop. The script
disables competing systemd-timesyncd service, installs chrony when needed,
and keeps a timestamped backup of the previous chrony configuration.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

GROUND_IP=""
while (($# > 0)); do
    case "$1" in
        --ground-ip)
            (($# >= 2)) || die "--ground-ip requires a value"
            GROUND_IP="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            die "unknown argument: $1"
            ;;
    esac
done

[[ -n "$GROUND_IP" ]] || die "--ground-ip is required"

valid_ipv4() {
    local value="$1"
    [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    local part
    IFS=. read -r -a parts <<< "$value"
    for part in "${parts[@]}"; do
        ((part >= 0 && part <= 255)) || return 1
    done
}

valid_ipv4 "$GROUND_IP" || die "Ground IP is not a valid IPv4 address: $GROUND_IP"

if ((EUID != 0)); then
    exec sudo -- "$0" --ground-ip "$GROUND_IP"
fi

command -v apt-get >/dev/null 2>&1 || die "apt-get is required on the Jetson"

if ! command -v chronyd >/dev/null 2>&1 || ! command -v chronyc >/dev/null 2>&1; then
    echo "Installing chrony on Jetson..."
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y chrony
fi

CHRONYD="$(command -v chronyd)"
CHRONYC="$(command -v chronyc)"
CONFIG="/etc/chrony/chrony.conf"
[[ -x "$CHRONYD" ]] || die "chronyd was not found after installation"
[[ -x "$CHRONYC" ]] || die "chronyc was not found after installation"

install -d -m 0755 /etc/chrony /var/lib/chrony /var/log/chrony

if [[ -f "$CONFIG" ]]; then
    backup="$CONFIG.pre-bengawan-$(date -u +%Y%m%dT%H%M%SZ)"
    cp -p "$CONFIG" "$backup"
    echo "Previous Jetson config backed up to $backup"
fi

temporary_config="$(mktemp /tmp/bengawan-chrony-jetson.XXXXXX)"
cleanup() {
    rm -f "$temporary_config"
}
trap cleanup EXIT

cat > "$temporary_config" <<EOF
# Managed by Bengawan UAV setup_chrony_jetson.sh
# Ground is the authoritative clock for the mission timeline.
server $GROUND_IP iburst prefer
driftfile /var/lib/chrony/chrony.drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony
EOF

install -o root -g root -m 0644 "$temporary_config" "$CONFIG"

systemctl disable --now systemd-timesyncd.service >/dev/null 2>&1 || true
systemctl unmask chrony.service >/dev/null 2>&1 || true
systemctl enable chrony.service
systemctl restart chrony.service

echo "Waiting for Jetson chrony to select Ground $GROUND_IP..."
if ! "$CHRONYC" waitsync 60 0.1; then
    echo "warning: chrony did not reach sync within 60 seconds" >&2
fi

"$CHRONYC" -n tracking
"$CHRONYC" -n sources -v
echo
echo "Jetson chrony client is configured to use Ground $GROUND_IP on UDP/123."
