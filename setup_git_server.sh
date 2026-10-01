#!/usr/bin/env bash
# setup_git_server.sh
#
# Turns the ground laptop (10.200.142.60) into a git host for the UAS Orins so
# they can clone/pull the flight repos over the silvus/wired LAN instead of
# needing to be on wifi with GitHub access.
#
#   local    run on the laptop  - build bare mirrors in /srv/git + git-daemon service
#   sync     run on the laptop  - make GitHub, this laptop and every Orin match:
#                                 drone commits -> GitHub, laptop commits -> GitHub,
#                                 GitHub -> laptop, GitHub -> mirrors -> Orins.
#                                 --no-push stops at the mirrors, --submodules also
#                                 updates chimera-deploy's, --no-upstream skips the
#                                 push to GitHub, --no-local leaves the laptop's own
#                                 working copies alone, --push-new also sends
#                                 branches GitHub has never seen, and
#                                 --clean-dependabot drops obsolete mirror-only
#                                 Dependabot branches. --branch/-b NAME asks
#                                 clean ground checkouts to use NAME when it
#                                 exists, then propagates each resolved branch.
#                                 --status only prints the current ground repo
#                                 branches and working-tree changes.
#   push     run on the laptop  - push the current mirrors into every Orin's
#                                 working copy and rebuild/restart changed clients
#   scenes   run on the laptop  - copy the built scenes into every Orin and
#                                 restart clients whose scene files changed. The
#                                 ground station builds them with
#                                 `./px4sim genscene` and holds the only copy.
#                                 They are build product, so git does not carry
#                                 them, and this does
#   remote   run on an Orin     - point its repos at the laptop instead of GitHub
#   deploy   run on the laptop  - copy this script to each Orin and run 'remote' there
#   status   run anywhere       - show what is being served / what is reachable
#
# Fetch is anonymous over git:// (port 9418, read-only). Push goes back over ssh
# to /srv/git, which is why 'deploy' also installs each Orin's key on the laptop.
#
# 'sync' is the one-command refresh. It moves commits in both directions, so
# GitHub, this laptop and every reachable Orin end up on the same tip, then
# rebuilds and restarts each stack through its px4sim front door. Nothing is
# ever force-pushed or merged over a dirty tree: anything that cannot be
# fast-forwarded is reported and left for a human.
#
# A stack whose inputs have not moved since its last good restart is left
# running. "Its inputs" means exactly what stack_fingerprint hashes, so a new
# feature that a restart must pick up has to be added to that hash, or sync
# will leave stale stacks up. See the note above stack_fingerprint.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

SERVER_IP="${SERVER_IP:-10.200.142.60}"
SERVER_USER="${SERVER_USER:-user}"
SERVE_ROOT="${SERVE_ROOT:-/srv/git}"
GIT_PORT="${GIT_PORT:-9418}"
CLIENTS=(${CLIENTS:-10.200.142.61 10.200.142.62 10.200.142.63 10.200.142.64})

WS_SRC="$HOME/ros2_ws/src"

# repos to serve: <mirror name>|<upstream url>|<checkout dir on the Orin>
REPOS=(
  "cdcl_umd_msgs|git@github.com:UMD-CDCL/cdcl_umd_msgs.git|$WS_SRC/cdcl_umd_msgs"
  "MAVInsight|git@github.com:UMD-UROC/MAVInsight.git|$WS_SRC/MAVInsight"
  "5g_drone|git@github.com:UMD-CDCL/5g_drone.git|$WS_SRC/5g_drone"
  "tracking_test_5g|git@github.com:UMD-CDCL/tracking_test_5g.git|$WS_SRC/tracking_test_5g"
  "px4_msgs|git@github.com:PX4/px4_msgs.git|$WS_SRC/px4_msgs"
  "px4-sim-stack|git@github.com:UMD-CDCL/px4-sim-stack.git|$HOME/px4-sim-stack"
  "chimera-deploy|git@github.com:UMD-UROC/chimera-deploy.git|$HOME/chimera-deploy"
)

# Message packages the HOST workspace must hold built. The field recorder
# (remote/record_all_common.sh, local/local_record_all.sh) runs natively and
# sources ~/ros2_ws/install, while the flight stack runs in the container
# with its own build. A host build older than the source cannot load newer
# types ("typesupport library ... could not be found") and decodes changed
# ones with the old layout, so every sync rebuilds these on the ground and on
# each drone when their commit moved. px4_msgs is pinned and not rebuilt here.
HOST_MSG_PACKAGES=(${HOST_MSG_PACKAGES:-cdcl_umd_msgs})

# The script that brings a host workspace up to date, run with the package
# names as arguments: locally on the ground, over ssh on a drone. It builds a
# package only when its commit differs from the last successful host build
# (~/.px4sim-sync-host-msgs) or its install is missing, so a sync that moved
# nothing costs nothing. It writes build/, install/ and log/ at the workspace
# root, never inside a checkout, so the trees stay clean for the next sync.
host_messages_script() {
  cat <<'EOF'
set -uo pipefail
ws="$HOME/ros2_ws" stamp="$HOME/.px4sim-sync-host-msgs" log="$HOME/.px4sim-sync-host-msgs.log"
[ -d "$ws/src" ] || { echo "no $ws/src - skipped"; exit 0; }
cd "$ws" || exit 1
have=$(cat "$stamp" 2>/dev/null || true) want="" build=()
for p in "$@"; do
  [ -d "src/$p/.git" ] || continue
  c=$(git -C "src/$p" rev-parse HEAD) || exit 1
  want+="$p=$c "
  case " $have " in *" $p=$c "*) [ -f "install/$p/share/$p/package.xml" ] && continue ;; esac
  build+=("$p")
done
[ "${#build[@]}" -gt 0 ] || { echo "current"; exit 0; }
set +u; . /opt/ros/humble/setup.bash; set -u
[ -x /usr/bin/cmake ] && export CMAKE_COMMAND=/usr/bin/cmake CTEST_COMMAND=/usr/bin/ctest
if MAKEFLAGS=-j4 colcon build --packages-select "${build[@]}" \
     --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF >"$log" 2>&1; then
  printf '%s\n' "$want" >"$stamp"
  echo "rebuilt ${build[*]}"
else
  echo "FAILED building ${build[*]} - see $log"
  exit 1
fi
EOF
}
refresh_local_host_messages() {
  printf '  %-18s ' "host messages"
  bash -s -- "${HOST_MSG_PACKAGES[@]}" < <(host_messages_script)
}
refresh_client_host_messages() {
  local ip="$1"
  printf '  %-18s ' "host messages"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" \
    bash -s -- "${HOST_MSG_PACKAGES[@]}" < <(host_messages_script)
}

# chimera-deploy submodules, mirrored so 'git submodule update' works offline
SUBMODULES=(
  "rtw88|https://github.com/lwfinger/rtw88"
  "EchoTherm-Daemon|https://github.com/EchoMAV/EchoTherm-Daemon.git"
  "echopilot_deploy|https://github.com/echomav/echopilot_deploy.git"
  "Camera_Modules|git@github.com:EchoMAV/Camera_Modules.git"
  "echopilot_ai_bsp|https://github.com/EchoMAV/echopilot_ai_bsp"
  "mavros|https://github.com/mavlink/mavros.git"
  "angles|https://github.com/ros/angles.git"
  "geographic_info|https://github.com/ros-geographic-info/geographic_info.git"
)

say()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[error]\033[0m $*" >&2; exit 1; }

# A sync talks to each drone about fifty times, one ssh after another. A fresh
# handshake costs ~270 ms on the wired LAN and more over the radio; riding an
# open master costs ~10 ms. So every call to a drone shares one connection per
# drone for the whole run. git and rsync spawn the ssh binary rather than this
# function, so they are handed SSH_MUX_OPTS explicitly. A master detaches from
# its caller's stdio, so it cannot hold a pipe open the way a stray tail did.
SSH_MUX_DIR=''
SSH_MUX_OPTS=()

ssh() { command ssh "${SSH_MUX_OPTS[@]}" "$@"; }

ssh_mux_start() {
  [ -z "$SSH_MUX_DIR" ] || return 0
  SSH_MUX_DIR="$(mktemp -d -t chimera-ssh.XXXXXX)"
  SSH_MUX_OPTS=(-o ControlMaster=auto -o "ControlPath=$SSH_MUX_DIR/%C" -o ControlPersist=120)
  trap ssh_mux_stop EXIT
}

ssh_mux_stop() {
  local sock
  for sock in "$SSH_MUX_DIR"/*; do
    [ -S "$sock" ] && command ssh -o "ControlPath=$sock" -O exit mux >/dev/null 2>&1
  done
  rm -rf "$SSH_MUX_DIR"
}

# Which drones answer, asked once per run and all at once. An offline drone
# costs a one second ping timeout, and preflight, deploy and push each paid it
# again in turn, while scenes waited out an ssh ConnectTimeout instead. A drone
# that answers gets its ssh master opened here, alongside the others.
declare -A CLIENT_UP=()

probe_clients() {
  local ip index
  local -a pids=()
  for ip in "${CLIENTS[@]}"; do
    (ping -c1 -W1 "$ip" >/dev/null 2>&1 || exit 1
     ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" true </dev/null >/dev/null 2>&1
     exit 0) &
    pids+=("$!")
  done
  for index in "${!pids[@]}"; do
    if wait "${pids[$index]}"; then
      CLIENT_UP[${CLIENTS[$index]}]=1
    else
      CLIENT_UP[${CLIENTS[$index]}]=0
    fi
  done
}

client_up() {
  case "${CLIENT_UP[$1]:-}" in
    1) return 0 ;;
    0) return 1 ;;
  esac
  ping -c1 -W1 "$1" >/dev/null 2>&1
}

# A sync keeps the noisy Docker output in per-job logs.  Its foreground shell
# tails this compact status stream so an operator knows which independent
# rebuild is alive without waiting for a whole image build to finish.
sync_status() {
  [ -n "${SYNC_STATUS_FILE:-}" ] || return 0
  printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*" >>"$SYNC_STATUS_FILE"
}

# the local working copy a mirror can be seeded from when GitHub is unreachable
local_source_for() {
  local name="$1"
  case "$name" in
    chimera-deploy) echo "$SCRIPT_DIR" ;;
    5g_drone)       echo "$WS_SRC/5g_drone" ;;
    px4-sim-stack)  echo "$HOME/px4-sim-stack" ;;
    *)              echo "$WS_SRC/$name" ;;
  esac
}

prepare_ground_branches() {
  local requested="$1" entry name url checkout dir actual
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url checkout <<< "$entry"
    [ "$name" = px4_msgs ] && continue
    dir="$(local_source_for "$name")"
    [ -d "$dir/.git" ] || die "ground repository missing: $name ($dir)"
    actual="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    if [ -n "$requested" ] && ! git -C "$dir" show-ref --verify --quiet "refs/heads/$requested"; then
      git -C "$dir" fetch -q origin "$requested" 2>/dev/null || true
      if git -C "$dir" show-ref --verify --quiet "refs/remotes/origin/$requested"; then
        git -C "$dir" diff --quiet && git -C "$dir" diff --cached --quiet \
          || die "ground repository dirty: $name cannot create '$requested'"
        git -C "$dir" switch --track -c "$requested" "origin/$requested" >/dev/null \
          || die "could not create ground $name branch '$requested'"
      fi
    fi
    if [ -n "$requested" ] && git -C "$dir" show-ref --verify --quiet "refs/heads/$requested"; then
      if [ "$actual" != "$requested" ]; then
        git -C "$dir" diff --quiet && git -C "$dir" diff --cached --quiet \
          || die "ground repository dirty: $name cannot switch to '$requested'"
        git -C "$dir" switch "$requested" >/dev/null \
          || die "could not switch ground $name to '$requested'"
      fi
    elif [ -n "$requested" ]; then
      warn "$name: branch '$requested' not present; using '${actual:-detached}'"
    fi
    [ -n "$actual" ] || actual="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    [ -n "$actual" ] || die "ground repository detached: $name"
  done
}

# the name an Orin checked this repo out under before the rename
old_checkout_for() {
  case "$1" in
    5g_drone) echo "$WS_SRC/umd_uas" ;;
  esac
}

github_up() {
  timeout 15 git ls-remote git@github.com:UMD-UROC/chimera-deploy.git HEAD >/dev/null 2>&1
}

###############################################################################
# local - build the mirrors and start the daemon
###############################################################################
cmd_local() {
  command -v git >/dev/null || die "git is not installed"
  [ -x /usr/lib/git-core/git-daemon ] || die "git-daemon not found at /usr/lib/git-core/git-daemon"

  say "creating $SERVE_ROOT"
  sudo mkdir -p "$SERVE_ROOT"
  sudo chown "$USER:$USER" "$SERVE_ROOT"

  local online=1
  github_up || { online=0; warn "GitHub unreachable - seeding mirrors from local working copies"; }

  say "building bare mirrors"
  local entry name url src
  for entry in "${REPOS[@]}" "${SUBMODULES[@]}"; do
    IFS='|' read -r name url _ <<< "$entry"
    mirror_repo "$name" "$url" "$online"
  done

  # a clone made before the rename still asks by this name
  ln -sfn "$SERVE_ROOT/5g_drone.git" "$SERVE_ROOT/umd_uas.git"
  echo "  linked umd_uas.git -> 5g_drone.git"

  install_daemon
  open_firewall

  say "serving on git://$SERVER_IP:$GIT_PORT/"
  ls -1 "$SERVE_ROOT" | sed 's/^/  /'
  cat <<EOF

Next:
  ./setup_git_server.sh deploy    # push the client config out to the Orins
  ./setup_git_server.sh sync      # GitHub -> mirrors -> every drone (while on wifi)
EOF
}

# mirror_repo <name> <upstream url> <online 0|1>
mirror_repo() {
  local name="$1" url="$2" online="$3"
  local dest="$SERVE_ROOT/$name.git"

  if [ -d "$dest" ]; then
    echo "  $name.git exists - skipping (use 'sync' to update)"
  elif [ "$online" = 1 ]; then
    echo "  cloning $name from GitHub"
    git clone --quiet --mirror "$url" "$dest"
  else
    local src; src="$(local_source_for "$name")"
    if [ -d "$src/.git" ]; then
      echo "  cloning $name from $src"
      git clone --quiet --mirror "$src" "$dest"
      git -C "$dest" remote set-url origin "$url"
      # a mirror of a working copy drags in refs/remotes/* and refs/stash,
      # which clients would otherwise see - keep only heads and tags
      local ref
      while read -r ref; do
        [ -n "$ref" ] && git -C "$dest" update-ref -d "$ref"
      done < <(git -C "$dest" for-each-ref --format='%(refname)' refs/remotes refs/stash)
    else
      warn "  no source for $name (no GitHub, no working copy at $src) - skipped"
      return 0
    fi
  fi

  # never prune on sync: Orins may have pushed branches that are not on GitHub
  git -C "$dest" config remote.origin.prune false
  git -C "$dest" config gc.auto 0
  touch "$dest/git-daemon-export-ok"
}

install_daemon() {
  say "installing git-daemon.service"
  sudo tee /etc/systemd/system/git-daemon.service >/dev/null <<EOF
[Unit]
Description=Git daemon serving chimera repo mirrors to the UAS LAN
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
ExecStart=/usr/lib/git-core/git-daemon --base-path=$SERVE_ROOT --export-all \\
    --reuseaddr --listen=$SERVER_IP --port=$GIT_PORT --verbose
Restart=always
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=read-only
ReadOnlyPaths=$SERVE_ROOT

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable --now git-daemon.service
  sleep 1
  systemctl is-active --quiet git-daemon.service \
    && echo "  git-daemon active on $SERVER_IP:$GIT_PORT" \
    || die "git-daemon failed to start - check: journalctl -u git-daemon -n 50"
}

open_firewall() {
  if sudo ufw status 2>/dev/null | grep -q "^Status: active"; then
    say "opening $GIT_PORT/tcp for 10.200.142.0/24"
    sudo ufw allow from 10.200.142.0/24 to any port "$GIT_PORT" proto tcp
    sudo ufw allow from 10.200.142.0/24 to any port 22 proto tcp
  fi
}

###############################################################################
# sync - send drone commits up to GitHub, refresh the mirrors, push to the Orins
###############################################################################
cmd_sync() {
  local do_push=1 subs=0 upstream=1 push_new=0 do_local=1 clean_dependabot=0 show_status=0 local_only=0 no_build=0 branch='' arg
  while [ "$#" -gt 0 ]; do
    arg="$1"
    case "$arg" in
      --status)       show_status=1 ;;
      --help|-h)
        cat <<'EOF'
Usage: ./setup_git_server.sh sync [options]

Options:
  --local              update only the local working copies
  --no-build           skip all local and drone builds and restarts;
                       drones still get the new commits
  --no-push            update mirrors without pushing to drones
  --submodules         update chimera-deploy submodules
  --no-upstream         skip publishing to GitHub
  --push-new            push new branches upstream and to drones
  --force-restart       restart every stack, even one that already runs
                        this deployment (see stack_fingerprint)
  --no-local            skip local working-copy updates and builds
  --clean-dependabot    remove obsolete Dependabot mirror branches
  --branch NAME         use NAME where available
  --status              show local repository status
  --help, -h            show this help
EOF
        return 0
        ;;
      --local)       local_only=1; do_push=0 ;;
      --no-build)    no_build=1 ;;
      --force-restart) FORCE_RESTART=1 ;;
      --no-push)     do_push=0 ;;
      --submodules)  subs=1 ;;
      --no-upstream) upstream=0 ;;
      --push-new)    push_new=1 ;;
      --no-local)    do_local=0 ;;
      --clean-dependabot) clean_dependabot=1 ;;
      --branch)
        [ "$#" -ge 2 ] || die "--branch requires a branch name"
        branch="$2"; shift
        ;;
      *) die "unknown option for sync: $arg" ;;
    esac
    shift
  done

  [ "$show_status" = 0 ] || { cmd_sync_status; return; }

  if [ "$local_only" = 1 ]; then
    do_push=0
    upstream=0
  fi

  [[ "$branch" != -* ]] || die "invalid sync branch: $branch"
  ssh_mux_start
  probe_clients
  check_sync_trees_clean
  prepare_ground_branches "$branch"

  if [ "$local_only" = 0 ]; then
    say "stage 1/5: scenes and drone git configuration"
    echo "  scenes: starting"
    echo "  drone configuration: starting"
    local setup_scenes_log setup_deploy_log setup_scenes_pid setup_deploy_pid setup_rc=0
    setup_scenes_log="$(mktemp -t chimera-sync-scenes.XXXXXX)"
    setup_deploy_log="$(mktemp -t chimera-sync-deploy.XXXXXX)"
    (SCENES_DEFER_RESTART=1 cmd_scenes >"$setup_scenes_log" 2>&1) & setup_scenes_pid=$!
    (cmd_deploy >"$setup_deploy_log" 2>&1) & setup_deploy_pid=$!
    wait "$setup_scenes_pid" || { setup_rc=1; echo "scene synchronization failed:"; cat "$setup_scenes_log"; }
    wait "$setup_deploy_pid" || { setup_rc=1; echo "drone configuration failed:"; cat "$setup_deploy_log"; }
    [ "$setup_rc" = 0 ] && echo "  scenes: done; drone configuration: done"
    rm -f "$setup_scenes_log" "$setup_deploy_log"
    [ "$setup_rc" = 0 ] || die "scene or drone configuration failed"
  fi

  # drone commits -> GitHub, laptop commits -> GitHub, GitHub -> laptop,
  # GitHub -> mirrors, mirrors -> drones. Every step before the refresh has to
  # land first, or the forced mirror fetch overwrites what it has not seen.
  if github_up; then
    say "stage 2/5: publishing mirror branches upstream"
    if [ "$upstream" = 1 ]; then
      push_mirrors_upstream "$push_new" "$clean_dependabot"
      echo "  upstream publish: done"
    else
      echo "  upstream publish: skipped"
    fi

    if [ "$do_local" = 1 ]; then
      say "stage 3/5: synchronizing ground working copies (parallel)"
      sync_local_worktrees_parallel 1 "$push_new"
      echo "  ground working copies: done"
      refresh_local_host_messages || die "ground host message build failed"
    else
      echo "  ground working copies: skipped"
    fi

    if [ "$local_only" = 0 ]; then
      say "stage 4/5: refreshing mirrors (parallel)"
      sync_mirrors_parallel
      echo "  mirrors: done"
    fi
  elif [ "$do_push" = 1 ]; then
    warn "GitHub unreachable - skipping the mirror refresh, pushing what we have"
    # the mirrors still hold whatever the drones pushed over the LAN, so the
    # laptop can pick those up without wifi
    if [ "$do_local" = 1 ]; then
      sync_local_worktrees_parallel 0 "$push_new"
      refresh_local_host_messages || die "ground host message build failed"
    fi
  else
    die "GitHub unreachable - connect to wifi first"
  fi

  local clients_pid='' ground_pid='' clients_log='' ground_log='' status_log='' rc=0
  local ground_output_lines=0 ground_output_lines_sent=0 client_output_lines=0
  declare -A client_output_lines_sent=()
  local clients_done=0 ground_done=0 status_lines=0
  local client_file=''
  local dashboard_width=120 line='' dashboard_lines=0
  dashboard_width="$(tput cols 2>/dev/null || echo 120)"
  [ "$dashboard_width" -gt 20 ] || dashboard_width=120
  if [ "$no_build" = 1 ]; then
    echo "  builds: skipped"
    # --no-build skips the rebuild, not the delivery. Returning before the push
    # left the drones on their old commits while the mirrors moved on, so a
    # rtsp_config.py change could be committed, synced and never reach rcam.
    if [ "$do_push" = 1 ]; then
      say "stage 5/5: updating drone checkouts (no build, no restart)"
      if [ -n "${SYNC_UI:-}" ]; then
        for ip in "${CLIENTS[@]}"; do echo "[$ip] SYNC_START"; done
      fi
      cmd_push --no-restart --branch "$branch" $([ "$subs" = 1 ] && echo --submodules) \
        || die "drone checkout update failed"
    fi
    return 0
  fi
  status_log="$(mktemp -t chimera-sync-status.XXXXXX)"
  export SYNC_CLIENT_LOG_DIR="$(mktemp -d -t chimera-sync-client-logs.XXXXXX)"
  export SYNC_STATUS_FILE="$status_log"
  say "stage 5/5: rebuilding ground and drones (parallel dashboard)"
  if [ "$do_push" = 1 ]; then
    # The ground image has no dependency on an aircraft image.  Start both
    # sides now; each side still waits for and reports all of its own jobs.
    clients_log="$(mktemp -t chimera-sync-clients.XXXXXX)"
    (cmd_push --branch "$branch" $([ "$subs" = 1 ] && echo --submodules)) >"$clients_log" 2>&1 &
    clients_pid=$!
    if [ -n "${SYNC_UI:-}" ]; then
      for ip in "${CLIENTS[@]}"; do echo "[$ip] SYNC_START"; done
    fi
  else
    echo
    echo "Mirrors updated. Send them to the Orins with:"
    echo "  ./setup_git_server.sh push"
  fi

  if [ "$do_local" = 1 ]; then
    ground_log="$(mktemp -t chimera-sync-ground.XXXXXX)"
    (sync_status 'ground: BUILDING';
     refresh_local_stack && sync_status 'ground: SUCCESS' || {
      sync_status 'ground: FAILURE (see ground build log)'; exit 1; }) >"$ground_log" 2>&1 &
    ground_pid=$!
    [ -n "${SYNC_UI:-}" ] && echo "[ground] BUILD_START"
  fi
  [ -n "$clients_pid" ] || clients_done=1
  [ -n "$ground_pid" ] || ground_done=1

  # Both rebuild groups run concurrently.  Drain status changes immediately,
  # but retain the full logs until each group has finished so Docker output
  # remains readable instead of interleaving across hosts.
  while [ "$clients_done" = 0 ] || [ "$ground_done" = 0 ]; do
    if [ -n "${SYNC_UI:-}" ]; then
      if [ -n "$ground_log" ] && [ -s "$ground_log" ]; then
        ground_output_lines="$(wc -l <"$ground_log")"
        if [ "$ground_output_lines" -gt "$ground_output_lines_sent" ]; then
          sed -n "$((ground_output_lines_sent + 1)),${ground_output_lines}p" "$ground_log" \
            | sed 's/^/[ground] /'
          ground_output_lines_sent="$ground_output_lines"
        fi
      fi
      for ip in "${CLIENTS[@]}"; do
        client_file="${SYNC_CLIENT_LOG_DIR:-}/$ip.log"
        if [ -s "$client_file" ]; then
          client_output_lines="$(wc -l <"$client_file")"
          if [ "$client_output_lines" -gt "${client_output_lines_sent[$ip]:-0}" ]; then
            sed -n "$(( ${client_output_lines_sent[$ip]:-0} + 1 )),${client_output_lines}p" "$client_file" \
              | sed "s/^/[$ip] /"
            client_output_lines_sent[$ip]="$client_output_lines"
          fi
        fi
      done
    else

    printf '\033[H\033[J'
    echo "sync progress"
    echo "----------------"
    printf 'ground\n'
    if [ -n "$ground_log" ] && [ -s "$ground_log" ]; then
      dashboard_lines=0
      while IFS= read -r line; do
        line="$(printf '%s' "$line" | sed $'s/\033\\[[0-9;]*[[:alpha:]]//g; s/\r/ /g')"
        printf '%.*s\n' "$dashboard_width" "$line"
        dashboard_lines=$((dashboard_lines + 1))
      done < <(tail -n 5 "$ground_log")
      [ "$dashboard_lines" -ge 5 ] || printf '  waiting\n%.0s' $(seq $((5 - dashboard_lines)))
    else
      printf '  waiting\n%.0s' {1..5}
    fi
    for ip in "${CLIENTS[@]}"; do
      printf '%s\n' "$ip"
      client_file="${SYNC_CLIENT_LOG_DIR:-}/$ip.log"
      if [ -s "$client_file" ]; then
        dashboard_lines=0
        while IFS= read -r line; do
          line="$(printf '%s' "$line" | sed $'s/\033\\[[0-9;]*[[:alpha:]]//g; s/\r/ /g')"
          printf '%.*s\n' "$dashboard_width" "$line"
          dashboard_lines=$((dashboard_lines + 1))
        done < <(tail -n 5 "$client_file")
        [ "$dashboard_lines" -ge 5 ] || printf '  waiting\n%.0s' $(seq $((5 - dashboard_lines)))
      else
        printf '  waiting\n%.0s' {1..5}
      fi
    done
    echo "----------------"
    fi
    local -a updates=()
    mapfile -t updates <"$status_log"
    while [ "$status_lines" -lt "${#updates[@]}" ]; do
      if [ -n "${SYNC_UI:-}" ] && [[ "${updates[$status_lines]}" =~ ([0-9.]+):[[:space:]]REBUILDING ]]; then
        echo "[${BASH_REMATCH[1]}] BUILD_START"
      fi
      status_lines=$((status_lines + 1))
    done

    if [ -n "$clients_pid" ] && [ "$clients_done" = 0 ] && ! kill -0 "$clients_pid" 2>/dev/null; then
      local client_rc=0
      wait "$clients_pid" || client_rc=$?
      [ "$client_rc" = 0 ] || rc=1
      clients_done=1
      if [ "$client_rc" != 0 ]; then
        echo "  [sync] client error log:"
      fi
    elif [ -z "$clients_pid" ]; then
      clients_done=1
    fi
    if [ -n "$ground_pid" ] && [ "$ground_done" = 0 ] && ! kill -0 "$ground_pid" 2>/dev/null; then
      local ground_rc=0
      wait "$ground_pid" || ground_rc=$?
      [ "$ground_rc" = 0 ] || rc=1
      ground_done=1
      if [ -n "${SYNC_UI:-}" ]; then
        [ "$ground_rc" = 0 ] && echo "[ground] DONE" || echo "[ground] ERROR"
      fi
      if [ "$ground_rc" != 0 ]; then
        echo "  [sync] ground error log:"
      fi
    elif [ -z "$ground_pid" ]; then
      ground_done=1
    fi
    [ "$clients_done" = 1 ] && [ "$ground_done" = 1 ] || sleep 1
  done
  rm -f "$clients_log" "$ground_log"
  rm -rf "$SYNC_CLIENT_LOG_DIR"
  unset SYNC_CLIENT_LOG_DIR
  # A job can publish its final status between the last drain and exit.
  mapfile -t updates <"$status_log"
  while [ "$status_lines" -lt "${#updates[@]}" ]; do
    echo "  [sync] ${updates[$status_lines]}"
    status_lines=$((status_lines + 1))
  done
  rm -f "$status_log"
  unset SYNC_STATUS_FILE
  if [ "$rc" != 0 ]; then
    warn "one or more parallel sync jobs failed"
    return "$rc"
  fi
  if [ -n "$branch" ]; then
    say "sync complete: ground and reachable drones are on $branch"
  else
    say "sync complete: ground and reachable drones match their ground branches"
  fi

  if [ "$upstream" = 0 ]; then
    echo
    echo "Note: --no-upstream was given, so branches the Orins pushed here have"
    echo "not been sent to GitHub. Send one on with:"
    echo "  git -C $SERVE_ROOT/<repo>.git -c remote.origin.mirror=false \\"
    echo "      push origin <branch>"
  fi
}

cmd_sync_status() {
  local entry name url dir
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url _ <<< "$entry"
    dir="$(local_source_for "$name")"
    printf '\n== %s (%s) ==\n' "$name" "$dir"
    if [ ! -d "$dir/.git" ]; then
      echo "repository missing"
      continue
    fi

    git -C "$dir" status --short --branch --untracked-files=all
  done
}

###############################################################################
# Bring the laptop's own working copies in line with GitHub: publish what they
# have that GitHub does not, then fast-forward them onto everything else -
# including the drone commits push_mirrors_upstream just sent up.
#
# Runs before the mirror refresh, so laptop commits reach the mirrors (and from
# there the drones) in the same pass.
#
# Fast-forwards only, and never touches a dirty tree. The laptop is where the
# real work happens; nothing here may cost an uncommitted edit.
###############################################################################
sync_local_worktrees_parallel() {
  local online="$1" push_new="$2" entry name log pid rc=0
  local -a pids=() names=() logs=()
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name _ _ <<< "$entry"
    log="$(mktemp -t "chimera-sync-local-$name.XXXXXX")"
    (REPOS=("$entry"); sync_local_worktrees "$online" "$push_new") >"$log" 2>&1 &
    pids+=("$!"); names+=("$name"); logs+=("$log")
  done
  for entry in "${!pids[@]}"; do
    rc=0; wait "${pids[$entry]}" || rc=$?
    if [ "$rc" != 0 ]; then
      echo "laptop ${names[$entry]}: FAILED"
      cat "${logs[$entry]}"
      return "$rc"
    fi
    rm -f "${logs[$entry]}"
  done
}

sync_mirrors_parallel() {
  local d name log rc
  local -a pids=() names=() logs=()
  say "refreshing mirrors in $SERVE_ROOT (parallel)"
  for d in "$SERVE_ROOT"/*.git; do
    [ -d "$d" ] || continue
    [ -L "$d" ] && continue
    name="$(basename "$d")"
    log="$(mktemp -t "chimera-sync-mirror-$name.XXXXXX")"
    (git -C "$d" fetch --quiet origin "+refs/heads/*:refs/heads/*" \
       "+refs/tags/*:refs/tags/*") >"$log" 2>&1 &
    pids+=("$!"); names+=("$name"); logs+=("$log")
  done
  for d in "${!pids[@]}"; do
    rc=0; wait "${pids[$d]}" || rc=$?
    if [ "$rc" != 0 ]; then
      echo "mirror ${names[$d]}: FAILED"
      cat "${logs[$d]}"
      return "$rc"
    fi
    rm -f "${logs[$d]}"
  done
  echo "  all mirrors refreshed"
}

sync_local_worktrees() {
  local online="$1" push_new="$2"
  say "syncing the laptop working copies"

  # chimera-deploy last: it holds this script. git replaces a file rather than
  # rewriting it in place, so the running shell keeps reading the original
  # inode and a mid-run merge is survivable - but there is no reason to lean on
  # that any earlier in the run than necessary.
  local order=() entry name
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name _ _ <<< "$entry"
    [ "$name" = chimera-deploy ] || order+=("$name")
  done
  order+=(chimera-deploy)

  local src_label="GitHub"
  [ "$online" = 1 ] || src_label="the mirror"

  local dir branch sha gh ahead behind out rc
  for name in "${order[@]}"; do
    dir="$(local_source_for "$name")"
    printf '  %-16s ' "$name"

    [ -d "$dir/.git" ] || { echo "no working copy at $dir - skipped"; continue; }

    branch="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    [ -n "$branch" ] || { echo "detached HEAD - skipped"; continue; }

    if [ "$online" = 1 ]; then
      # px4_msgs is intentionally pinned on local/drone working copies.
      # Do not fetch it from GitHub during sync; otherwise frequent upstream
      # message updates trigger an expensive colcon rebuild.
      if [ "$name" = px4_msgs ]; then
        echo "$branch: pinned - GitHub pull skipped"
        continue
      fi
      git -C "$dir" fetch -q origin 2>/dev/null \
        || { echo "$branch: fetch from GitHub failed"; continue; }
      gh="$(git -C "$dir" rev-parse -q --verify "refs/remotes/origin/$branch" 2>/dev/null || true)"
    else
      git -C "$dir" fetch -q "$SERVE_ROOT/$name.git" "refs/heads/$branch" 2>/dev/null \
        || { echo "$branch: not in the mirror - skipped"; continue; }
      gh="$(git -C "$dir" rev-parse -q --verify FETCH_HEAD 2>/dev/null || true)"
    fi

    sha="$(git -C "$dir" rev-parse HEAD)"

    if [ -z "$gh" ]; then
      # branch exists only here
      if [ "$online" != 1 ] || [ "$push_new" != 1 ]; then
        echo "$branch: local only - use --push-new to publish it"
        continue
      fi
    elif [ "$gh" = "$sha" ]; then
      echo "$branch: up to date"
      continue
    elif git -C "$dir" merge-base --is-ancestor "$sha" "$gh"; then
      behind="$(git -C "$dir" rev-list --count "$sha..$gh")"
      if ! git -C "$dir" diff --quiet 2>/dev/null || ! git -C "$dir" diff --cached --quiet 2>/dev/null; then
        echo "$branch: $behind behind, tree is dirty - left alone"
        continue
      fi
      if git -C "$dir" merge --ff-only "$gh" >/dev/null 2>&1; then
        echo "$branch: pulled $behind commit(s)"
      else
        echo "$branch: ff merge of $behind commit(s) FAILED"
      fi
      continue
    elif ! git -C "$dir" merge-base --is-ancestor "$gh" "$sha"; then
      ahead="$(git -C "$dir" rev-list --count "$gh..$sha")"
      behind="$(git -C "$dir" rev-list --count "$sha..$gh")"
      echo "$branch: DIVERGED ($ahead local, $behind on $src_label) - left alone"
      continue
    fi

    # strictly ahead of GitHub (or brand new with --push-new): publish it
    if [ "$online" != 1 ]; then
      echo "$branch: ahead of the mirror - goes up on the next online sync"
      continue
    fi
    rc=0
    out="$(git -C "$dir" push origin "refs/heads/$branch:refs/heads/$branch" 2>&1)" || rc=$?
    if [ "$rc" = 0 ]; then
      echo "$branch: pushed to GitHub"
    else
      echo "$branch: push to GitHub FAILED"
      printf '%s\n' "$out" | sed 's/^/      /'
    fi
  done
  return 0
}

###############################################################################
# Send commits the Orins pushed into the mirrors on up to GitHub.
#
# This MUST run before the fetch below. A mirror fetches +refs/*:refs/* - the
# refspec is forced - so GitHub's tip overwrites the mirror's ref even when the
# mirror is ahead. remote.origin.prune=false does not help: prune only spares
# branches GitHub does not have at all, not ones it has an older version of.
# A bare mirror also keeps no reflog, so anything lost that way is only
# recoverable as a dangling object.
#
# Only fast-forwards are sent. Diverged branches would need --force, which is
# not this script's call to make, so they are parked under refs/sync-backup/
# and reported. Branches that exist only in a mirror are not pushed by default
# either: with prune=false, a branch deleted on GitHub lives on here forever,
# and auto-pushing would resurrect it on every sync. Use --push-new for those.
# --clean-dependabot is deliberately narrower: it removes only mirror-only
# dependabot/* heads that GitHub confirms no longer has.
###############################################################################
push_mirrors_upstream() {
  local push_new="$1" clean_dependabot="$2"
  say "sending drone commits on to GitHub"

  # Each mirror only talks to its own GitHub repo, so they go up in parallel.
  # Asked one after another, fifteen ls-remotes were most of this stage. The
  # logs are printed in mirror order afterwards, so the output reads the same.
  local d index rc tmp p h c pushed=0 held=0 cleaned=0
  local -a dirs=() pids=()
  tmp="$(mktemp -d -t chimera-sync-upstream.XXXXXX)"
  for d in "$SERVE_ROOT"/*.git; do
    [ -d "$d" ] || continue
    [ -L "$d" ] && continue
    index="${#dirs[@]}"
    dirs+=("$d")
    publish_mirror_upstream "$d" "$push_new" "$clean_dependabot" "$tmp/$index.counts" \
      >"$tmp/$index.log" 2>&1 &
    pids+=("$!")
  done
  for index in "${!pids[@]}"; do
    rc=0; wait "${pids[$index]}" || rc=$?
    cat "$tmp/$index.log"
    [ "$rc" = 0 ] || { rm -rf "$tmp"; die "upstream publish failed for $(basename "${dirs[$index]}")"; }
    if [ -r "$tmp/$index.counts" ]; then
      read -r p h c <"$tmp/$index.counts"
      pushed=$((pushed + p)); held=$((held + h)); cleaned=$((cleaned + c))
    fi
  done
  rm -rf "$tmp"

  if [ "$pushed" = 0 ] && [ "$held" = 0 ] && [ "$cleaned" = 0 ]; then
    echo "  nothing to send - GitHub already has every mirror branch"
  else
    echo "  sent $pushed branch(es) to GitHub, $held held back, $cleaned obsolete Dependabot branch(es) removed"
  fi
  return 0
}

# One mirror's half of push_mirrors_upstream. Writes "pushed held cleaned" to
# the counts file once it has looked at every branch.
publish_mirror_upstream() {
  local d="$1" push_new="$2" clean_dependabot="$3" counts="$4"
  local name url remote_heads sha ref branch gh out rc pushed=0 held=0 cleaned=0
  name="$(basename "$d" .git)"

  url="$(git -C "$d" config --get remote.origin.url 2>/dev/null || true)"
  [ -n "$url" ] || return 0

  remote_heads="$(timeout 30 git ls-remote --heads "$url" 2>/dev/null)" || {
    warn "  $name: cannot reach $url - skipped"
    return 0
  }

  while read -r sha ref; do
    branch="${ref#refs/heads/}"
    gh="$(printf '%s\n' "$remote_heads" | awk -v r="$ref" '$2 == r { print $1 }')"

    if [ -z "$gh" ]; then
      if [ "$clean_dependabot" = 1 ] && [[ "$branch" == dependabot/* ]]; then
        if git -C "$d" update-ref -d "$ref" "$sha"; then
          printf '  %-22s %-34s %s\n' "$name" "$branch" "removed obsolete Dependabot branch"
          cleaned=$((cleaned + 1))
        else
          printf '  %-22s %-34s %s\n' "$name" "$branch" "FAILED to remove obsolete Dependabot branch"
          held=$((held + 1))
        fi
        continue
      fi
      if [ "$push_new" != 1 ]; then
        printf '  %-22s %-34s %s\n' "$name" "$branch" "mirror only - use --push-new"
        held=$((held + 1))
        continue
      fi
    else
      [ "$gh" = "$sha" ] && continue      # already there

      # The ancestry tests below need GitHub's tip in the object store, and
      # we will not have it when GitHub has moved on. Fetch just that one
      # ref: an explicit refspec replaces the configured +refs/*:refs/*, so
      # this cannot overwrite refs/heads the way 'remote update' does.
      if ! git -C "$d" cat-file -e "${gh}^{commit}" 2>/dev/null; then
        if ! git -C "$d" fetch -q origin "refs/heads/$branch" 2>/dev/null; then
          git -C "$d" update-ref "refs/sync-backup/$branch" "$sha"
          printf '  %-22s %-34s %s\n' "$name" "$branch" "cannot compare with GitHub"
          echo "      kept as refs/sync-backup/$branch (the refresh may drop it)"
          held=$((held + 1))
          continue
        fi
      fi

      git -C "$d" merge-base --is-ancestor "$sha" "$gh" && continue  # behind

      if ! git -C "$d" merge-base --is-ancestor "$gh" "$sha"; then
        git -C "$d" update-ref "refs/sync-backup/$branch" "$sha"
        printf '  %-22s %-34s %s\n' "$name" "$branch" "DIVERGED - not pushed"
        echo "      kept as refs/sync-backup/$branch (the refresh would drop it)"
        echo "      reconcile it by hand, then re-run sync"
        held=$((held + 1))
        continue
      fi
    fi

    printf '  %-22s %-34s ' "$name" "$branch"
    rc=0
    # explicit refspec, so remote.origin.mirror=true does not turn this into
    # a --mirror push (which would delete GitHub branches we do not carry)
    out="$(git -C "$d" -c remote.origin.mirror=false push origin \
             "refs/heads/$branch:refs/heads/$branch" 2>&1)" || rc=$?
    if [ "$rc" = 0 ]; then
      echo "-> GitHub"
      pushed=$((pushed + 1))
    else
      echo "FAILED"
      printf '%s\n' "$out" | sed 's/^/      /'
      git -C "$d" update-ref "refs/sync-backup/$branch" "$sha"
      echo "      kept as refs/sync-backup/$branch (the refresh would drop it)"
      held=$((held + 1))
    fi
  done < <(git -C "$d" for-each-ref --format='%(objectname) %(refname)' refs/heads)

  echo "$pushed $held $cleaned" >"$counts"
}

###############################################################################
# push - from the laptop, shove the mirrors into every Orin's working copy
#
# Each Orin repo gets receive.denyCurrentBranch=updateInstead, so a push to the
# branch it has checked out updates the working tree too - no 'git pull' on the
# drone. A dirty tree makes git refuse that ref, so local edits are never lost.
###############################################################################
cmd_push() {
  local subs=0 no_restart=0 branch='' arg failed=0
  while [ "$#" -gt 0 ]; do
    arg="$1"
    case "$arg" in
      --submodules) subs=1 ;;
      --no-restart) no_restart=1 ;;
      --force-restart) FORCE_RESTART=1 ;;
      --branch)
        [ "$#" -ge 2 ] || die "--branch requires a branch name"
        branch="$2"; shift
        ;;
      *) die "unknown option for push: $arg" ;;
    esac
    shift
  done
  # An empty branch means: use the current branch of each ground repository.

  # Each aircraft has its own checkout, Docker daemon and GPU, so rebuilding
  # them serially only burns operator time.  Keep the ground refresh outside
  # this function (cmd_sync calls it after us): it must see the completed
  # fleet, but the aircraft jobs themselves are independent.
  local ip ok=0 index rc
  local -a clients=() jobs=() logs=() log_tails=()
  for ip in "${CLIENTS[@]}"; do
    if ! client_up "$ip"; then
      if [ -n "${SYNC_CLIENT_LOG_DIR:-}" ]; then
        printf 'OFFLINE - not reachable; skipped\n' >"$SYNC_CLIENT_LOG_DIR/$ip.log"
      fi
      sync_status "$ip: UNREACHABLE"
      continue
    fi
    clients+=("$ip")
    if [ -n "${SYNC_CLIENT_LOG_DIR:-}" ]; then
      logs+=("$SYNC_CLIENT_LOG_DIR/$ip.log")
      : >"${logs[-1]}"
    else
      logs+=("$(mktemp -t chimera-sync-client.XXXXXX)")
    fi
    # Redirect each job rather than letting parallel SSH/Docker output splice
    # together.  The completed log is printed under its aircraft heading.
    (NO_RESTART="$no_restart" push_to_client "$ip" "$subs" "$branch") >"${logs[-1]}" 2>&1 &
    jobs+=("$!")
    # --pid ends the follower once its job is reaped. Killing the subshell
    # instead left tail -f running forever, and its sed kept holding whatever
    # stdout sync had, so a caller reading to EOF never got there.
    (stdbuf -oL tail -n +1 -f --pid="${jobs[-1]}" "${logs[-1]}" 2>/dev/null |
      stdbuf -oL sed "s/^/[$ip] /") &
    log_tails+=("$!")
    sync_status "$ip: BUILDING"
  done

  for index in "${!jobs[@]}"; do
    say "${clients[$index]}"
    rc=0
    wait "${jobs[$index]}" || rc=$?
    wait "${log_tails[$index]}" 2>/dev/null || true
    if [ "$rc" != 0 ]; then
      printf '\nERROR\n' >>"${logs[$index]}"
      echo "[${clients[$index]}] ERROR (see the preceding live lines)"
    elif [ -n "${SYNC_UI:-}" ]; then
      printf '\nDONE\n' >>"${logs[$index]}"
      echo "[${clients[$index]}] DONE"
    fi
    [ -n "${SYNC_CLIENT_LOG_DIR:-}" ] || rm -f "${logs[$index]}"
    if [ "$rc" = 0 ]; then
      ok=$((ok + 1))
      sync_status "${clients[$index]}: SUCCESS"
    else
      failed=1
      warn "${clients[$index]}: update or restart failed"
      sync_status "${clients[$index]}: FAILURE (see client build log)"
    fi
  done

  say "pushed to $ok of ${#CLIENTS[@]} clients"
  [ "$failed" = 0 ] || return 1
}

###############################################################################
# What a running px4sim stack was built from, as one hash. Sync restarts a
# stack only when this differs from the hash stored after that stack's last
# successful restart (~/.px4sim-sync-deployed on each machine).
#
# >>> EXTEND THIS HASH WHEN YOU ADD ANYTHING A RESTART MUST PICK UP. <<<
# If a new feature adds an input the running stack depends on and git does not
# carry in the repos below (a file outside the repos, a gitignored config, a
# generated artifact, a device setting, a new selector), add it here. If you
# do not, sync will call the stack current, leave it running, and the drones
# will silently disagree with the ground until someone passes --force-restart.
#
# Hashed today:
#   - every repo's checked-out branch and commit (the arguments)
#   - the submodules each repo pins (git submodule status)
#   - px4-sim-stack/.env, which carries the selectors
#   - the built scenes under modules/sim/scenes (build product, not in git)
#   - the IDs of the stack containers that are up, so a stack that is down,
#     crashed, or restarted by hand from another checkout never matches
#
# Runs on the ground, and on a drone after being shipped there by declare -f,
# so it may only use what both carry. Anything it cannot read makes the hash
# unique, which costs a restart and never skips one.
###############################################################################
stack_fingerprint() {
  local stack="$HOME/px4-sim-stack" dir
  {
    for dir in "$@"; do
      printf '%s %s %s\n' "$dir" \
        "$(git -C "$dir" symbolic-ref -q --short HEAD 2>/dev/null || echo detached)" \
        "$(git -C "$dir" rev-parse -q --verify HEAD 2>/dev/null || echo missing)"
      if [ -f "$dir/.gitmodules" ]; then
        git -C "$dir" submodule status --recursive 2>/dev/null || echo "submodules unreadable $RANDOM$RANDOM"
      fi
    done
    sha256sum "$stack/.env" 2>/dev/null || echo "no .env"
    find "$stack/modules/sim/scenes" -type f -printf '%P %s %T@\n' 2>/dev/null | LC_ALL=C sort || true
    docker ps --no-trunc -q --filter "label=com.docker.compose.project.working_dir=$stack" 2>/dev/null \
      | LC_ALL=C sort | grep . || echo "no containers $RANDOM$RANDOM"
  } | sha256sum | cut -d' ' -f1
}

# stack_fingerprint on a drone, then the stamp its last good restart left.
remote_stack_fingerprint() {
  local ip="$1" stamp_file="$2"; shift 2
  # The function body and stamp path expand here on purpose; \$@ is the drone's.
  # shellcheck disable=SC2087
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" "bash -s -- $(printf '%q ' "$@")" <<EOF
$(declare -f stack_fingerprint)
stack_fingerprint "\$@"
cat $(printf '%q' "$stamp_file") 2>/dev/null || true
EOF
}

write_remote_stack_stamp() {
  local ip="$1" stamp_file="$2"; shift 2
  # shellcheck disable=SC2087
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" "bash -s -- $(printf '%q ' "$@")" <<EOF
$(declare -f stack_fingerprint)
stack_fingerprint "\$@" >$(printf '%q' "$stamp_file")
EOF
}

refresh_local_stack() {
  local stack="$HOME/px4-sim-stack" stamp_file="$HOME/.px4sim-sync-deployed" entry name
  local -a dirs=()
  [ -x "$stack/px4sim" ] || { warn "local px4-sim-stack is missing - skipped build"; return 1; }
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name _ _ <<< "$entry"
    dirs+=("$(local_source_for "$name")")
  done
  # A sync can change a Docker build context, configuration, or a bind-mounted
  # runtime input outside the set of files Git reports as updated, and `start`
  # deliberately no-ops when running, so a restart is the disruptive front
  # door. It is skipped only when stack_fingerprint (extend it, see above) says
  # nothing has moved since the last restart that succeeded here.
  if [ "${FORCE_RESTART:-0}" != 1 ] \
      && [ "$(stack_fingerprint "${dirs[@]}")" = "$(cat "$stamp_file" 2>/dev/null)" ]; then
    say "local stack already runs this deployment; left running"
    return 0
  fi
  say "building and restarting the local stack"
  (cd "$stack" && ./px4sim restart) || return 1
  stack_fingerprint "${dirs[@]}" >"$stamp_file"
}

# Sync is a propagation operation, not a way to hide local work. Check every
# checkout before changing mirrors, branches, scenes, or drone configuration so
# one dirty repository cannot turn a run into a partial update. Offline drones
# are intentionally skipped; a reachable drone with a dirty tree is fatal.
check_sync_trees_clean() {
  local entry name url dir ip rhome rdir state rc=0 details

  say "preflight: checking working trees"
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url _ <<< "$entry"
    dir="$(local_source_for "$name")"
    [ -d "$dir/.git" ] || die "preflight: missing ground repository $name ($dir)"
    details="$(git -C "$dir" status --porcelain=v1 --untracked-files=all 2>/dev/null)" || {
      die "preflight: could not inspect ground repository $name"
    }
    if [ -n "$details" ]; then
      echo "$details" | sed "s/^/  $name: /"
      rc=1
    fi
  done

  for ip in "${CLIENTS[@]}"; do
    client_up "$ip" || continue
    rhome="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" 'echo "$HOME"' 2>/dev/null)" || {
      warn "preflight: $ip is reachable but SSH failed"
      rc=1
      continue
    }
    for entry in "${REPOS[@]}"; do
      IFS='|' read -r name url dir <<< "$entry"
      rdir="${dir/#$HOME/$rhome}"
      state="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" \
        "if [ -d '$rdir/.git' ]; then git -C '$rdir' status --porcelain=v1 --untracked-files=all; fi" \
        2>/dev/null)" || {
          warn "preflight: could not inspect $ip/$name"
          rc=1
          continue
        }
      if [ -n "$state" ]; then
        echo "$state" | sed "s/^/  $ip $name: /"
        rc=1
      fi
    done
  done
  [ "$rc" = 0 ] || die "preflight found uncommitted, staged, or untracked changes; resolve them before syncing"
  echo "  all inspected working trees clean"
}

sync_selectors_to_client() {
  local ip="$1" rhome="$2" scene scenario conops roles role camera result remote_command
  local ground_env="$HOME/px4-sim-stack/.env"
  [ -r "$ground_env" ] || { warn "ground .env is missing - cannot sync selectors"; return 1; }
  scene="$(sed -n 's/^SCENE=//p' "$ground_env" | head -1)"
  scenario="$(sed -n 's/^SCENARIO=//p' "$ground_env" | head -1)"
  conops="$(sed -n 's/^CONOPS=//p' "$ground_env" | head -1)"
  roles="$(sed -n 's/^UAS_ROLES=//p' "$ground_env" | head -1)"
  camera="$(sed -n 's/^ONBOARD_CAMERA=//p' "$ground_env" | head -1)"
  conops=${conops:-option1}
  # Day or night: which camera the detector reads. Set on the ground with key n
  # in ./px4sim ui, or ./px4sim camera day|night. Unset reads as day, the way
  # the console shows it.
  camera=${camera:-rgb}
  roles=${roles:-'assess assess search search'}
  roles=${roles#\"}; roles=${roles%\"}
  roles=${roles#\'}; roles=${roles%\'}
  [[ "$scene" =~ ^[A-Za-z0-9_-]+$ && "$scenario" =~ ^[A-Za-z0-9_-]+$ ]] || {
    warn "ground .env has invalid SCENE or SCENARIO"; return 1;
  }
  case "$conops" in option1|option2) ;; *) warn "ground .env has invalid CONOPS"; return 1 ;; esac
  case "$camera" in rgb|thermal) ;; *) warn "ground .env has invalid ONBOARD_CAMERA"; return 1 ;; esac
  [ -n "$roles" ] || { warn "ground .env has empty UAS_ROLES"; return 1; }
  for role in $roles; do
    case "$role" in search|assess) ;; *) warn "ground .env has invalid UAS_ROLES"; return 1 ;; esac
  done
  roles="\"$roles\""

  printf -v remote_command 'env_file=%q; scene=%q; scenario=%q; conops=%q; roles=%q; camera=%q; ' \
    "$rhome/px4-sim-stack/.env" "$scene" "$scenario" "$conops" "$roles" "$camera"
  # The selector variables expand on the aircraft when this command runs.
  # shellcheck disable=SC2016
  remote_command+='[ -f "$env_file" ] || exit 1
    set_env_key() {
      local key=$1 value=$2 escaped
      if grep -q "^$key=" "$env_file"; then
        escaped=$(printf "%s" "$value" | sed "s|[&\\\\]|\\\\&|g")
        sed -i "s|^$key=.*|$key=$escaped|" "$env_file"
      else
        printf "%s=%s\\n" "$key" "$value" >>"$env_file"
      fi
    }
    sync_key() {
      local key=$1 desired=$2 current
      current=$(sed -n "s/^$key=//p" "$env_file" | head -1)
      if [ "$current" != "$desired" ]; then
        set_env_key "$key" "$desired"
        changed=1
      fi
    }
    changed=0
    sync_key SCENE "$scene"
    sync_key SCENARIO "$scenario"
    sync_key CONOPS "$conops"
    sync_key UAS_ROLES "$roles"
    sync_key ONBOARD_CAMERA "$camera"
    printf "%s" "$changed"'
  result="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" "$remote_command" 2>/dev/null)" || {
    warn "$ip: could not sync selectors"; return 1;
  }
  if [ "$result" = 1 ]; then
    echo "  selectors: updated SCENE=$scene SCENARIO=$scenario CONOPS=$conops UAS_ROLES=$roles ONBOARD_CAMERA=$camera"
    return 2
  fi
  echo "  selectors: already SCENE=$scene SCENARIO=$scenario CONOPS=$conops UAS_ROLES=$roles ONBOARD_CAMERA=$camera"
  return 0
}

push_to_client() {
  local ip="$1" subs="$2" desired_branch="$3"
  local ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)

  local rhome
  rhome="$(ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" 'echo "$HOME"' 2>/dev/null)" || {
    warn "ssh failed - skipped"
    return 1
  }

  # The stack restarts when anything it was built from has moved: a commit, a
  # submodule, .env, the scenes, or its containers. stack_fingerprint hashes
  # all of that, and the hash is stored on the drone after each successful
  # restart. A deferred scene change, a selector change or --force-restart
  # restarts regardless, and a failed restart stores nothing, so the next sync
  # tries again. A new restart input belongs in stack_fingerprint, not here.
  local entry name url dir rdir mirror state branch tree out restart_required=0 repo_branch
  local -a rdirs=()
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url dir <<< "$entry"
    # REPOS paths are laptop-side; the Orin's home may sit elsewhere
    rdir="${dir/#$HOME/$rhome}"
    rdirs+=("$rdir")
    mirror="$SERVE_ROOT/$name.git"
    repo_branch="$desired_branch"
    if [ -z "$repo_branch" ] || ! git -C "$mirror" show-ref --verify --quiet "refs/heads/$repo_branch"; then
      repo_branch="$(git -C "$(local_source_for "$name")" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    fi
    [ -n "$repo_branch" ] || { echo "FAILED - $name: no ground branch"; return 1; }

    printf '  %-18s ' "$name"
    [ -d "$mirror" ] || { echo "no mirror - run 'local' first"; continue; }

    # arm the repo for a working-tree push and report what state it is in
    state="$(ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" "
      if [ ! -d '$rdir/.git' ]; then echo MISSING; exit 0; fi
      git -C '$rdir' config receive.denyCurrentBranch updateInstead
      b=\$(git -C '$rdir' symbolic-ref --quiet --short HEAD 2>/dev/null || echo '(detached)')
      if git -C '$rdir' diff --quiet 2>/dev/null && git -C '$rdir' diff --cached --quiet 2>/dev/null
        then echo \"READY \$b clean\"; else echo \"READY \$b dirty\"; fi
    " 2>/dev/null)" || { echo "ssh failed"; continue; }

    if [ "$state" = MISSING ]; then
      echo "not cloned - run 'deploy'"
      continue
    fi
    read -r _ branch tree <<< "$state"

    local rc=0 target="$SERVER_USER@$ip:$rdir"
    export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=5 ${SSH_MUX_OPTS[*]}"

    # no force here: a rejected ref means the Orin has commits we would destroy
    out="$(git -C "$mirror" push --quiet "$target" \
             'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' 2>&1)" || rc=$?

    # second pass on purpose - git maps each local ref to a single destination
    # per push, so the tracking refs are silently dropped if bundled above.
    # Forced, otherwise the Orin's 'git status' reports a phantom divergence.
    # Do not hide failure here: if this pass fails, a branch can exist in the
    # mirror but be missing from `git branch -r` on the drone.
    local tracking_rc=0 tracking_out
    tracking_out="$(git -C "$mirror" push --quiet "$target" \
        '+refs/heads/*:refs/remotes/origin/*' 2>&1)" || tracking_rc=$?
    if [ "$tracking_rc" != 0 ]; then
      rc=$tracking_rc
      out="${out}${out:+$'\n'}tracking-ref push failed:${tracking_out:+$'\n'}$tracking_out"
    fi

    if [ "$rc" = 0 ]; then
      if [ "$name" = px4_msgs ]; then
        echo "ok (pinned: $branch)"
      elif ! ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
          "git -C '$rdir' diff --quiet && git -C '$rdir' diff --cached --quiet && git -C '$rdir' switch '$repo_branch' >/dev/null 2>&1 && test \"\$(git -C '$rdir' symbolic-ref --short HEAD)\" = '$repo_branch'"; then
        echo "FAILED - $name: could not enforce branch $repo_branch on $ip"
        return 1
      else
        echo "ok ($repo_branch)"
      fi
    else
      # report why git actually refused, not why we guess it refused - a dirty
      # tree and a non-fast-forward need completely different fixes
      if printf '%s' "$out" | grep -qiE 'non-fast-forward|fetch first|behind its remote'; then
        echo "REJECTED - $branch: the Orin has commits the mirror does not"
        echo "      nothing was lost; push them here from the Orin, then re-run sync:"
        echo "      ssh $SERVER_USER@$ip 'git -C $rdir push origin $branch'"
      elif printf '%s' "$out" | grep -qiE 'working (directory|tree)|uncommitted|untracked|updateInstead'; then
        echo "PARTIAL - $branch has uncommitted changes on the Orin, tree left alone"
      elif [ "$tree" = dirty ]; then
        echo "FAILED - $branch (the Orin's tree is also dirty)"
      else
        echo "FAILED - $branch"
      fi
      printf '%s\n' "$out" | sed 's/^/      /'
    fi

    # MAVROS is an offline-pinned submodule used by the overlay build below;
    # it must follow the chimera-deploy gitlink on every sync.  --submodules
    # remains available for callers that want the other submodules refreshed.
    if [ "$name" = chimera-deploy ]; then
      update_client_submodules "$ip" "$rdir"
    fi
  done

  # The native recorder decodes with the host workspace, not the container.
  refresh_client_host_messages "$ip" || { warn "$ip: host message build failed"; return 1; }

  # Keep the onboard selectors aligned even when no repository changed. A
  # selector-only change must still trigger the same restart as a code change.
  if ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
      "test -f '$rhome/.px4sim-sync-restart-needed'"; then
    restart_required=1
  fi
  sync_selectors_to_client "$ip" "$rhome" || {
    [ "$?" = 2 ] && restart_required=1 || return 1
  }

  local stamp_file="$rhome/.px4sim-sync-deployed" fingerprint='' stamp=''
  if [ "${FORCE_RESTART:-0}" = 1 ]; then
    restart_required=1
  elif [ "${NO_RESTART:-0}" != 1 ] && [ "$restart_required" = 0 ]; then
    { read -r fingerprint; read -r stamp; } \
      < <(remote_stack_fingerprint "$ip" "$stamp_file" "${rdirs[@]}") || true
    [ -n "$fingerprint" ] && [ "$fingerprint" = "$stamp" ] || restart_required=1
  fi

  if [ "${NO_RESTART:-0}" = 1 ]; then
    echo "  restart: skipped (--no-restart)"
  elif [ "$restart_required" = 1 ]; then
    [ -n "${SYNC_UI:-}" ] && echo "BUILD_START"
    sync_status "$ip: REBUILDING"
    say "$ip: rebuilding and restarting through px4sim"
    if ! ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
         "cd '$rhome/px4-sim-stack' && ./px4sim restart"; then
      warn "$ip: px4sim restart failed after sync"
      return 1
    fi
    ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
      "rm -f '$rhome/.px4sim-sync-restart-needed'" || {
      warn "$ip: could not clear deferred restart marker"; return 1;
    }
    write_remote_stack_stamp "$ip" "$stamp_file" "${rdirs[@]}" \
      || warn "$ip: could not record this deployment; the next sync restarts it again"
  else
    echo "  stack already runs this deployment; left running"
  fi
  return 0
}

update_client_submodules() {
  local ip="$1" rdir="$2"
  printf '  %-18s ' "└ submodules"
  # url rewrites installed by 'remote' point these at the laptop, so this
  # resolves without wifi on the drone
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_USER@$ip" \
       "git -C '$rdir' submodule update --init --recursive" >/dev/null 2>&1; then
    echo "ok"
  else
    echo "FAILED - check manually on $ip"
  fi
}

###############################################################################
# remote - run on an Orin: point its repos at the laptop
###############################################################################
cmd_remote() {
  local restore=0
  [ "${1:-}" = "--restore" ] && restore=1

  if [ "$restore" = 1 ]; then
    say "restoring GitHub remotes"
  else
    say "pointing repos at git://$SERVER_IP"
    timeout 10 git ls-remote "git://$SERVER_IP:$GIT_PORT/chimera-deploy.git" HEAD >/dev/null 2>&1 \
      || die "cannot reach git://$SERVER_IP:$GIT_PORT - run 'local' mode on the laptop first"
  fi

  local entry name url dir old
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url dir <<< "$entry"

    if [ "$restore" = 1 ]; then
      [ -d "$dir/.git" ] || continue
      git -C "$dir" remote set-url origin "$url"
      git -C "$dir" config --unset remote.origin.pushurl || true
      echo "  $(basename "$dir") -> $url"
      continue
    fi

    # move the old checkout, do not clone a second one.
    # two directories of the same ROS package stop the colcon build
    old="$(old_checkout_for "$name")"
    if [ -n "$old" ] && [ -d "$old/.git" ] && [ ! -e "$dir" ]; then
      mv "$old" "$dir"
      echo "  renamed $(basename "$old") to $(basename "$dir")"
    elif [ -n "$old" ] && [ -d "$old/.git" ]; then
      warn "$old and $dir are both there - delete the one you do not build"
    fi

    if [ ! -d "$dir/.git" ]; then
      echo "  cloning $name -> $dir"
      mkdir -p "$(dirname "$dir")"
      git clone --quiet "git://$SERVER_IP:$GIT_PORT/$name.git" "$dir"
    fi

    # keep the original GitHub url reachable as 'github'
    git -C "$dir" remote get-url github >/dev/null 2>&1 \
      || git -C "$dir" remote add github "$url"

    git -C "$dir" remote set-url origin "git://$SERVER_IP:$GIT_PORT/$name.git"
    git -C "$dir" config remote.origin.pushurl "$SERVER_USER@$SERVER_IP:$SERVE_ROOT/$name.git"
    echo "  $(basename "$dir") -> git://$SERVER_IP/$name.git (push over ssh)"
  done

  rewrite_submodule_urls "$restore"

  if [ "$restore" = 1 ]; then
    say "restored - this machine needs internet again"
  else
    say "done - 'git pull' now comes off the laptop, no wifi needed"
  fi
}

# Exact-url rewrites so 'git submodule update --init' resolves to the laptop.
# Deliberately per-url rather than a blanket github.com prefix, so unrelated
# GitHub clones (jetson-containers, CLIP, ...) are left alone.
rewrite_submodule_urls() {
  local restore="$1" entry name url alt section u
  for entry in "${SUBMODULES[@]}"; do
    IFS='|' read -r name url <<< "$entry"
    section="url.git://$SERVER_IP:$GIT_PORT/$name.git"

    if [ "$restore" = 1 ]; then
      git config --global --remove-section "$section" 2>/dev/null || true
      continue
    fi

    # match both the https and ssh spelling of the same repo, with and without .git
    if [[ "$url" == git@github.com:* ]]; then
      alt="https://github.com/${url#git@github.com:}"
    else
      alt="git@github.com:${url#https://github.com/}"
    fi
    for u in "$url" "$alt" "${url%.git}" "${alt%.git}"; do
      git config --global --get-all "$section.insteadOf" 2>/dev/null | grep -qxF "$u" \
        || git config --global --add "$section.insteadOf" "$u"
    done
  done
  [ "$restore" = 1 ] && echo "  cleared submodule url rewrites" \
                     || echo "  submodule urls rewritten to the laptop"
}

###############################################################################
# deploy - from the laptop, configure every reachable Orin
###############################################################################
cmd_deploy() {
  systemctl is-active --quiet git-daemon.service \
    || die "git-daemon is not running - run './setup_git_server.sh local' first"

  local ip ok=0 log rc ip_index
  local -a pids=() ips=() logs=()
  for ip in "${CLIENTS[@]}"; do
    log="$(mktemp -t chimera-deploy-client.XXXXXX)"
    ips+=("$ip") logs+=("$log")
    (
      echo "$ip"
      if ! client_up "$ip"; then
        echo "unreachable - skipped"
        exit 2
      fi
      # let the Orin push back over ssh
      install_client_key "$ip"
      scp -q -o BatchMode=yes "${SSH_MUX_OPTS[@]}" "${BASH_SOURCE[0]}" "$SERVER_USER@$ip:/tmp/setup_git_server.sh"
      # shellcheck disable=SC2029
      ssh -o BatchMode=yes "$SERVER_USER@$ip" \
        "SERVER_IP=$SERVER_IP SERVE_ROOT=$SERVE_ROOT GIT_PORT=$GIT_PORT bash /tmp/setup_git_server.sh remote"
    ) >"$log" 2>&1 &
    pids+=("$!")
  done

  for ip_index in "${!pids[@]}"; do
    rc=0; wait "${pids[$ip_index]}" || rc=$?
    sed "s/^/[${ips[$ip_index]}] /" "${logs[$ip_index]}"
    rm -f "${logs[$ip_index]}"
    [ "$rc" = 0 ] && ok=$((ok + 1)) || {
      [ "$rc" = 2 ] || warn "${ips[$ip_index]}: configuration failed"
    }
  done

  say "configured $ok of ${#CLIENTS[@]} clients"
}

install_client_key() {
  local ip="$1" key
  key="$(ssh -o BatchMode=yes "$SERVER_USER@$ip" \
        'cat ~/.ssh/id_ed25519.pub 2>/dev/null || cat ~/.ssh/id_rsa.pub 2>/dev/null || \
         { ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub; }')" || {
    warn "could not read/create an ssh key on $ip - push-back will not work"
    return 0
  }
  mkdir -p "$HOME/.ssh"; touch "$HOME/.ssh/authorized_keys"; chmod 600 "$HOME/.ssh/authorized_keys"
  grep -qxF "$key" "$HOME/.ssh/authorized_keys" || {
    echo "$key" >> "$HOME/.ssh/authorized_keys"
    echo "  added $ip ssh key to authorized_keys"
  }
}

###############################################################################
# status
###############################################################################
cmd_status() {
  say "server $SERVER_IP:$GIT_PORT"
  if systemctl is-active --quiet git-daemon.service 2>/dev/null; then
    echo "  git-daemon: active"
    local d
    for d in "$SERVE_ROOT"/*.git; do
      [ -e "$d" ] || continue
      printf '    %-24s %s\n' "$(basename "$d")" \
        "$(git -C "$d" for-each-ref --count=1 --sort=-committerdate --format='%(refname:short) %(committerdate:relative)' refs/heads 2>/dev/null || echo link)"
    done
  else
    echo "  git-daemon: NOT running"
  fi

  say "clients"
  local ip
  for ip in "${CLIENTS[@]}"; do
    if ping -c1 -W1 "$ip" >/dev/null 2>&1; then
      printf '  %-16s up\n' "$ip"
    else
      printf '  %-16s down\n' "$ip"
    fi
  done
}

###############################################################################
# scenes - from the laptop, copy the built scenes into every Orin and restart
# any client whose runtime scene files changed
#
# A scene is map data: a terrain surface, the buildings, a satellite texture
# and a scenario naming where the targets stand. The ground station builds it
# with `./px4sim genscene` and is the single source, because building needs
# map downloads and a generator image no Orin carries.
#
# It is build product, so px4-sim-stack does not track it and no mirror can
# carry it. The aircraft needs the same surface the ground has: both sides cast
# the camera ray at one ground, and a vehicle left on the flat plane reports
# targets that fall outside the outline the ground station draws.
#
# Only the built files move. modules/scenegen/data holds the sources and git
# already carries those.
###############################################################################
SCENES_REL=${SCENES_REL:-px4-sim-stack/modules/sim/scenes}

cmd_scenes() {
  local src="$HOME/$SCENES_REL"
  [ -d "$src/worlds" ] || die "no scenes at $src. Build one on this machine:
  cd ~/px4-sim-stack && ./px4sim genscene --help"
  command -v rsync >/dev/null || die "rsync is not installed on this machine"

  local ip ok=0 log rc ip_index
  local -a pids=() ips=() logs=()
  for ip in "${CLIENTS[@]}"; do
    log="$(mktemp -t chimera-scenes-client.XXXXXX)"
    ips+=("$ip") logs+=("$log")
    (scenes_to_client "$ip") >"$log" 2>&1 &
    pids+=("$!")
  done
  for ip_index in "${!pids[@]}"; do
    rc=0; wait "${pids[$ip_index]}" || rc=$?
    sed "s/^/[${ips[$ip_index]}] /" "${logs[$ip_index]}"
    rm -f "${logs[$ip_index]}"
    [ "$rc" = 0 ] && ok=$((ok + 1)) || true
  done

  say "sent the scenes to $ok of ${#CLIENTS[@]} clients"
}

scenes_to_client() {
  local ip="$1" count out changed=0
  local src="$HOME/$SCENES_REL"
  local ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)
  local rsh="ssh ${ssh_opts[*]} ${SSH_MUX_OPTS[*]}"

  if ! client_up "$ip"; then
    echo "unreachable - skipped"
    return 2
  fi
  if ! ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" "[ -d ~/$SCENES_REL ]" 2>/dev/null; then
    warn "no ~/$SCENES_REL there - run deploy_onboard.sh on it first"
    return 1
  fi

  # The generated directories only. The vehicle models and spawn_scenario.py
  # are tracked, so they arrive with the checkout and must survive this.
  # --delete drops what a rebuilt scene no longer writes.
  out="$(rsync -ai --delete -e "$rsh" \
      "$src/worlds/" "$SERVER_USER@$ip:$SCENES_REL/worlds/")" || { warn "worlds failed"; return 1; }
  [ -z "$out" ] || changed=1
  out="$(rsync -ai --delete -e "$rsh" \
      "$src/scenarios/" "$SERVER_USER@$ip:$SCENES_REL/scenarios/")" || { warn "scenarios failed"; return 1; }
  [ -z "$out" ] || changed=1
  out="$(rsync -ai -e "$rsh" \
      --include='*_terrain/***' --include='*_buildings/***' --exclude='*' \
      "$src/models/" "$SERVER_USER@$ip:$SCENES_REL/models/")" || { warn "models failed"; return 1; }
  [ -z "$out" ] || changed=1

  count=$(ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
    "ls ~/$SCENES_REL/worlds/*_surface.json 2>/dev/null | wc -l")
  echo "  $count scenes"

  local rhome selectors_changed=0
  rhome="$(ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" 'echo "$HOME"' 2>/dev/null)" || {
    warn "$ip: could not read remote home for selector sync"; return 1;
  }
  if sync_selectors_to_client "$ip" "$rhome"; then
    :
  else
    local selectors_rc=$?
    [ "$selectors_rc" = 2 ] && selectors_changed=1 || return 1
  fi

  if [ "$changed" = 1 ] || [ "$selectors_changed" = 1 ]; then
    if [ "${SCENES_DEFER_RESTART:-0}" = 1 ]; then
      ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
        "touch '$rhome/.px4sim-sync-restart-needed'" || {
        warn "$ip: could not defer px4sim restart"; return 1;
      }
      echo "  restart: deferred until sync completes"
    else
      say "$ip: scene or selector changed; restarting through px4sim"
      ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
        "cd '$rhome/px4-sim-stack' && ./px4sim restart" || { warn "scene-triggered px4sim restart failed"; return 1; }
    fi
  else
    echo "  scene files unchanged; stack left running"
  fi
}

###############################################################################

case "${1:-}" in
  local)  cmd_local ;;
  scenes) ssh_mux_start; probe_clients; cmd_scenes ;;
  sync)   shift || true; cmd_sync "$@" ;;
  push)   shift || true; ssh_mux_start; probe_clients; cmd_push "$@" ;;
  remote) shift || true; cmd_remote "${1:-}" ;;
  deploy) ssh_mux_start; probe_clients; cmd_deploy ;;
  status) cmd_status ;;
  *)
    sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 1
    ;;
esac
