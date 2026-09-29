#!/usr/bin/env bash
# Read-only deployment health check for a Chimera aircraft.
# Run on the Orin as user, from ~/chimera-deploy or with an absolute path.
set -uo pipefail

STACK=${STACK:-$HOME/px4-sim-stack}
WS=${WS:-$HOME/ros2_ws}
UAS_NUM=${UAS_NUM:-$(sed -n 's/^UAS_NUM=//p' /etc/environment 2>/dev/null | tr -d '"' | tail -1)}
UAS_MODEL=${CHIMERA_MODEL:-$(sed -n 's/^CHIMERA_MODEL=//p' /etc/environment 2>/dev/null | tr -d '"' | tail -1)}
DECLARED_MODEL=$UAS_MODEL
# A drone deployed before deploy.sh wrote CHIMERA_MODEL has none. Take the
# model from the number, as onboard.launch.py's MODEL_FOR_UAS does, so the
# checks that depend on it still run.
if [[ -z "$UAS_MODEL" ]]; then
    case "$UAS_NUM" in 1|2) UAS_MODEL=v3 ;; 3|4) UAS_MODEL=v2 ;; esac
fi

PASS=0
WARN=0
FAIL=0

section() { printf '\n==> %s\n' "$*"; }
pass() { PASS=$((PASS + 1)); printf '[PASS] %s\n' "$*"; }
warn() { WARN=$((WARN + 1)); printf '[WARN] %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf '[FAIL] %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

ros_exec() {
    local command=${1:?command required}
    # ros-env.sh is the image's list of overlays: /opt/ros, the patched MAVROS
    # in /opt/mavros, then the workspace. Without MAVROS, mavros_msgs has no
    # type support here and every MAVROS topic looks silent.
    docker exec "$CONTAINER" bash -lc ". /usr/local/bin/ros-env.sh; $command"
}

topic_has_samples() {
    local topic=${1:?topic required}
    local output
    output=$(ros_exec "timeout 7 ros2 topic hz '$topic'" 2>&1 || true)
    printf '%s\n' "$output" | grep -q 'average rate:'
}

topic_has_message() {
    # For a latched topic (transient local, published once), which never
    # shows a rate.
    local topic=${1:?topic required}
    ros_exec "timeout 10 ros2 topic echo --once '$topic'" >/dev/null 2>&1
}

section "deployment identity"
if [[ "$UAS_NUM" =~ ^[1-9]$ ]]; then
    pass "UAS_NUM=$UAS_NUM"
else
    fail "UAS_NUM is missing or invalid: '${UAS_NUM:-unset}'"
fi
case "$DECLARED_MODEL" in
    v2|v3) pass "CHIMERA_MODEL=$DECLARED_MODEL" ;;
    *) fail "CHIMERA_MODEL is missing or invalid: '${DECLARED_MODEL:-unset}'; deploy_onboard.sh needs it. Add it with: echo CHIMERA_MODEL=${UAS_MODEL:-v2 or v3} | sudo tee -a /etc/environment" ;;
esac

section "network"
if ! have ip || ! have nmcli; then
    fail "ip and nmcli are required"
else
    if [[ "$UAS_MODEL" == v3 ]]; then
        EXPECTED_IF=${ROBO_IF:-eno1}
        EXPECTED_ADDR="10.200.142.6${UAS_NUM}"
        actual_addr=$(ip -4 -o addr show dev "$EXPECTED_IF" 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
        [[ "$actual_addr" == "$EXPECTED_ADDR" ]] \
            && pass "$EXPECTED_IF has $EXPECTED_ADDR" \
            || fail "$EXPECTED_IF address is '${actual_addr:-missing}', expected $EXPECTED_ADDR"
        connection=$(nmcli -g GENERAL.CONNECTION device show "$EXPECTED_IF" 2>/dev/null || true)
        [[ -n "$connection" && "$connection" != "--" ]] \
            && pass "$EXPECTED_IF active profile: $connection" \
            || fail "$EXPECTED_IF has no active NetworkManager profile"
        method=$(nmcli -g ipv4.method connection show "$connection" 2>/dev/null || true)
        never_default=$(nmcli -g ipv4.never-default connection show "$connection" 2>/dev/null || true)
        [[ "$method" == manual ]] && pass "$connection uses static IPv4" \
            || fail "$connection IPv4 method is '${method:-missing}', expected manual"
        [[ "$never_default" == yes ]] && pass "$connection has no default route" \
            || warn "$connection permits a default route; use share-on only when internet is needed"
        if ip route show default dev "$EXPECTED_IF" | grep -q .; then
            warn "internet sharing/default route is currently enabled on $EXPECTED_IF"
        else
            pass "no default route on $EXPECTED_IF"
        fi
        while IFS= read -r profile; do
            [[ -n "$profile" && "$profile" != "$connection" ]] || continue
            profile_type=$(nmcli -g connection.type connection show "$profile" 2>/dev/null || true)
            profile_if=$(nmcli -g connection.interface-name connection show "$profile" 2>/dev/null || true)
            profile_auto=$(nmcli -g connection.autoconnect connection show "$profile" 2>/dev/null || true)
            if [[ "$profile_type" == ethernet && "$profile_if" == "$EXPECTED_IF" && "$profile_auto" == yes ]]; then
                fail "competing Ethernet profile '$profile' still autoconnects on $EXPECTED_IF"
            fi
        done < <(nmcli -t -f NAME connection show)
    else
        wifi=$(ip -o -4 addr show | awk '$2 ~ /^(wl|wlan)/ && $4 ~ /^10\.200\.142\./ {print $2; exit}')
        [[ -n "$wifi" ]] && pass "v2 Wi-Fi flight interface: $wifi" \
            || warn "no 10.200.142.x Wi-Fi address found; v2 Wi-Fi may not be connected"
    fi
fi

section "native services"
for service in mavlink-router.service chrony.service; do
    if systemctl is-active --quiet "$service"; then
        pass "$service active"
    else
        fail "$service is not active"
    fi
done

if systemctl is-active --quiet rcam.service; then
    pass "rcam.service active"
else
    recent_rcam=$(journalctl -u rcam.service --since '2 minutes ago' --no-pager 2>/dev/null || true)
    if printf '%s\n' "$recent_rcam" | grep -Eqi 'thermal-fork|Boson|No frames from thermal'; then
        warn "rcam is inactive after the known thermal/RGB/gimbal USB congestion failure"
    else
        fail "rcam.service is not active"
    fi
fi

section "thermal camera caveat"
if have lsusb && lsusb | grep -Eqi 'FLIR|Boson'; then
    pass "Boson is currently visible on USB"
else
    warn "Boson is not currently visible on USB; with RGB, thermal, and gimbal active this is the known ~30-second USB-hub failure"
fi
thermal_log=$(journalctl -u rcam.service --since '10 minutes ago' --no-pager 2>/dev/null || true)
if printf '%s\n' "$thermal_log" | grep -Eqi 'thermal-fork producer started|thermal.*factory started'; then
    pass "thermal stream has started during this boot"
elif have lsusb && lsusb | grep -Eqi 'FLIR|Boson'; then
    pass "Boson is visible; no recent thermal startup line is available"
else
    warn "no recent thermal stream-start record found"
fi
if printf '%s\n' "$thermal_log" | grep -Eqi 'No frames from thermal-fork|Boson is off the air|no capture device'; then
    warn "thermal stream later failed as expected under shared USB-hub congestion"
fi
# The palette and AGC live in the camera, so a swapped camera arrives on FLIR's
# factory settings: white hot, which the detectors do much worse on.
if have lsusb && lsusb | grep -Eqi 'FLIR|Boson'; then
    here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    if boson=$(timeout 30 python3 "$here/boson_setup.py" --check 2>&1); then
        pass "Boson is on the Chimera settings (black hot, AGC)"
    else
        warn "Boson is not on the Chimera settings: ${boson##*$'\n'}. Run remote/boson_setup.py --apply"
    fi
    if [[ "$UAS_MODEL" == v3 ]]; then
        if timeout 30 python3 "$here/boson_averager.py" 2>/dev/null | grep -Eq '^averager +: 1'; then
            pass "Boson averager is on (30 Hz), as a v3 needs"
        else
            warn "Boson averager is off or unreadable; a v3 then loses the thermal camera off USB. Run remote/boson_averager.py --on, then power cycle the camera"
        fi
    fi
fi

section "PX4Sim container"
if [[ -x "$STACK/px4sim" ]]; then
    pass "px4sim front door present"
else
    fail "$STACK/px4sim is missing or not executable"
fi
CONTAINER=$(docker ps --filter 'name=px4simstack-onboard-1' --filter status=running --format '{{.Names}}' 2>/dev/null | head -1)
if [[ -n "$CONTAINER" ]]; then
    pass "aircraft container running: $CONTAINER"
else
    stopped_container=$(docker ps -a --filter 'name=px4simstack-onboard-1' --format '{{.Names}}' 2>/dev/null | head -1)
    if [[ -n "$stopped_container" ]]; then
        stopped_state=$(docker inspect -f 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} finished={{.State.FinishedAt}}' "$stopped_container" 2>/dev/null || true)
        fail "px4sim onboard container is not running ($stopped_state)"
        stopped_errors=$(docker logs --tail 20 "$stopped_container" 2>&1 | grep -Ei 'error|fatal|exception|killed|shutdown' | tail -5 || true)
        [[ -n "$stopped_errors" ]] && printf '       last container errors:\n%s\n' "$stopped_errors"
    else
        fail "px4sim onboard container does not exist"
    fi
fi

if [[ -n "${CONTAINER:-}" ]]; then
    section "ROS 2 and sensors"
    if topic_has_samples "/uas${UAS_NUM}/image"; then
        pass "/uas${UAS_NUM}/image is publishing"
    else
        fail "/uas${UAS_NUM}/image has no samples"
    fi
    if topic_has_message "/uas${UAS_NUM}/camera/camera_info"; then
        pass "/uas${UAS_NUM}/camera/camera_info is latched"
    else
        warn "/uas${UAS_NUM}/camera/camera_info has no message"
    fi
    if topic_has_samples "/uas${UAS_NUM}/state"; then
        pass "/uas${UAS_NUM}/state has MAVROS samples"
    else
        fail "/uas${UAS_NUM}/state has no MAVROS samples; PX4 telemetry is unavailable"
    fi
    if topic_has_samples "/uas${UAS_NUM}/imu/data"; then
        pass "/uas${UAS_NUM}/imu/data is publishing"
    else
        fail "/uas${UAS_NUM}/imu/data has no samples"
    fi
    if topic_has_samples "/uas${UAS_NUM}/altitude"; then
        pass "/uas${UAS_NUM}/altitude is publishing"
    else
        warn "/uas${UAS_NUM}/altitude has no samples"
    fi

    section "detector"
    detector=$(ros_exec "ros2 param get /uas${UAS_NUM}/ds_pipeline model.detector" 2>/dev/null \
        | sed -n 's/^String value is: //p')
    # The engine loads once, when the container starts, so read this whole run.
    # <pgie...> is the detector; the injury classifier is <sgie...>.
    started=$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null)
    engine=$(docker logs --since "$started" "$CONTAINER" 2>&1 \
        | grep '<pgie' \
        | grep -oE '(deserialized trt engine from|serialize cuda engine to file) *:? *[^ ]+\.engine' \
        | grep -oE '[^/ :]+\.engine$' | tail -1)
    if [[ -z "$engine" ]]; then
        fail "no detector TensorRT engine loaded in this container run${detector:+ (configured: $detector)}"
    elif [[ -n "$detector" && "$engine" != "$detector".onnx_* ]]; then
        fail "detector engine $engine does not match the configured model $detector"
    else
        pass "detector TensorRT engine loaded: $engine"
    fi
fi

section "MAVLink path"
if [[ -e /dev/ttyTHS1 ]]; then
    pass "/dev/ttyTHS1 present for native MAVLink router"
else
    fail "/dev/ttyTHS1 is missing"
fi
router_config=/etc/mavlink-router/main.conf
if [[ -r "$router_config" ]]; then
    pass "mavlink-router configuration readable"
    if grep -q 'Device = /dev/ttyTHS1' "$router_config" && grep -q 'Baud = 500000' "$router_config"; then
        pass "router uses ttyTHS1 at 500000 baud"
    else
        fail "router UART endpoint is not ttyTHS1 at 500000 baud"
    fi
    # PX4's MAV_SYS_ID is the UAS number (local/main.conf filters the same way).
    if grep -Eq "^AllowSrcSysIn *= *${UAS_NUM},255" "$router_config"; then
        pass "router allows UAS${UAS_NUM} source sysid ${UAS_NUM}"
    else
        warn "router does not explicitly allow UAS${UAS_NUM} source sysid ${UAS_NUM}; confirm PX4 MAV_SYS_ID before changing filters"
    fi
else
    fail "cannot read $router_config"
fi
unknown=$(journalctl -u mavlink-router --since '2 minutes ago' --no-pager 2>/dev/null | grep -c 'unknown endpoints' || true)
if [[ "$unknown" -gt 0 ]]; then
    warn "mavlink-router is reporting unknown endpoints; inspect PX4 sysid and routing before changing filters"
else
    pass "no recent unknown-endpoint router report"
fi

printf '\nSummary: %d passed, %d warnings, %d failed\n' "$PASS" "$WARN" "$FAIL"
if (( FAIL > 0 )); then
    exit 1
fi
