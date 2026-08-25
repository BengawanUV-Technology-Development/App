#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  setup_chrony_ground_macos.sh --ground-ip <ip> --jetson-ip <ip> [--upstream <host-or-ip>]...

The Ground becomes the chrony time server. By default it uses the Ground
clock as a local reference, so Internet NTP is not required for operation.
Optional --upstream entries can improve the Ground clock when a network source
is available, but the Jetson still uses only this Ground server.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

GROUND_IP=""
JETSON_IP=""
DISABLE_MACOS_NETWORK_TIME=1
UPSTREAMS=()

while (($# > 0)); do
    case "$1" in
        --ground-ip)
            (($# >= 2)) || die "--ground-ip requires a value"
            GROUND_IP="$2"
            shift 2
            ;;
        --jetson-ip)
            (($# >= 2)) || die "--jetson-ip requires a value"
            JETSON_IP="$2"
            shift 2
            ;;
        --upstream)
            (($# >= 2)) || die "--upstream requires a value"
            UPSTREAMS+=("$2")
            shift 2
            ;;
        --keep-macos-network-time)
            DISABLE_MACOS_NETWORK_TIME=0
            shift
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
[[ -n "$JETSON_IP" ]] || die "--jetson-ip is required"

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
valid_ipv4 "$JETSON_IP" || die "Jetson IP is not a valid IPv4 address: $JETSON_IP"
command -v brew >/dev/null 2>&1 || die "Homebrew is required on the Ground Mac"

if ! brew list --formula chrony >/dev/null 2>&1; then
    echo "Installing chrony with Homebrew..."
    brew install chrony
fi

BREW_PREFIX="$(brew --prefix)"
CHRONY_PREFIX="$(brew --prefix chrony)"
CHRONYD="$CHRONY_PREFIX/sbin/chronyd"
CHRONYC="$CHRONY_PREFIX/bin/chronyc"
[[ -x "$CHRONYD" ]] || die "chronyd was not found at $CHRONYD"
[[ -x "$CHRONYC" ]] || die "chronyc was not found at $CHRONYC"

CONFIG="$BREW_PREFIX/etc/chrony.conf"
STATE_DIR="$BREW_PREFIX/var/chrony"
LOG_DIR="$BREW_PREFIX/var/log/chrony"
RUN_DIR="$BREW_PREFIX/var/run/chrony"
PLIST="/Library/LaunchDaemons/com.bengawan.chrony-ground.plist"
LABEL="com.bengawan.chrony-ground"

temporary_config="$(mktemp -t bengawan-chrony-ground.conf)"
temporary_plist="$(mktemp -t bengawan-chrony-ground.plist)"
cleanup() {
    rm -f "$temporary_config" "$temporary_plist"
}
trap cleanup EXIT

{
    echo "# Managed by Bengawan UAV setup_chrony_ground_macos.sh"
    echo "# Ground is the authoritative clock for the Jetson mission timeline."
    if ((${#UPSTREAMS[@]} > 0)); then
        for upstream in "${UPSTREAMS[@]}"; do
            echo "server $upstream iburst"
        done
    fi
    echo "driftfile $STATE_DIR/chrony.drift"
    echo "dumpdir $STATE_DIR"
    echo "logdir $LOG_DIR"
    echo "pidfile $RUN_DIR/chronyd.pid"
    echo "makestep 1.0 3"
    echo "local stratum 10"
    echo "manual"
    echo "allow $JETSON_IP/32"
    echo "bindcmdaddress 127.0.0.1"
    echo "log measurements statistics tracking"
} > "$temporary_config"

cat > "$temporary_plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$CHRONYD</string>
        <string>-n</string>
        <string>-r</string>
        <string>-f</string>
        <string>$CONFIG</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/chronyd.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/chronyd.stderr.log</string>
</dict>
</plist>
EOF

echo "Installing Ground chrony configuration..."
sudo install -d -o root -g wheel -m 0755 "$STATE_DIR" "$LOG_DIR" "$RUN_DIR"
if [[ -f "$CONFIG" ]]; then
    backup="$CONFIG.pre-bengawan-$(date -u +%Y%m%dT%H%M%SZ)"
    sudo cp -p "$CONFIG" "$backup"
    echo "Previous config backed up to $backup"
fi
sudo install -o root -g wheel -m 0644 "$temporary_config" "$CONFIG"
sudo install -o root -g wheel -m 0644 "$temporary_plist" "$PLIST"

if ((DISABLE_MACOS_NETWORK_TIME)); then
    if ! sudo /usr/sbin/systemsetup -setusingnetworktime off; then
        echo "warning: could not disable macOS network time automatically" >&2
        echo "         disable it manually before flight to avoid competing time services" >&2
    fi
fi

sudo "$CHRONYD" -p -f "$CONFIG" >/dev/null
sudo launchctl bootout system/"$LABEL" >/dev/null 2>&1 || true
sudo pkill -TERM -x chronyd >/dev/null 2>&1 || true
sleep 1
sudo launchctl bootstrap system "$PLIST"
sudo launchctl enable system/"$LABEL" >/dev/null 2>&1 || true
sudo launchctl kickstart -k system/"$LABEL"

echo "Waiting for Ground chronyd..."
for _ in $(seq 1 15); do
    if sudo "$CHRONYC" -h 127.0.0.1 -n tracking >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

sudo "$CHRONYC" -h 127.0.0.1 -n tracking
sudo "$CHRONYC" -h 127.0.0.1 -n sources -v
echo
echo "Ground chrony server is configured for Jetson $JETSON_IP on UDP/123."
echo "If the Jetson cannot synchronize, check the macOS/Tailscale firewall for UDP/123."
