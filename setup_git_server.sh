#!/usr/bin/env bash
# setup_git_server.sh
#
# Turns the ground laptop (10.200.142.60) into a git host for the UAS Orins so
# they can clone/pull the flight repos over the silvus/wired LAN instead of
# needing to be on wifi with GitHub access.
#
#   local    run on the laptop  - build bare mirrors in /srv/git + git-daemon service
#   sync     run on the laptop  - refresh the mirrors from GitHub (do this on wifi)
#   remote   run on an Orin     - point its repos at the laptop instead of GitHub
#   deploy   run on the laptop  - copy this script to each Orin and run 'remote' there
#   status   run anywhere       - show what is being served / what is reachable
#
# Fetch is anonymous over git:// (port 9418, read-only). Push goes back over ssh
# to /srv/git, which is why 'deploy' also installs each Orin's key on the laptop.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

SERVER_IP="${SERVER_IP:-10.200.142.60}"
SERVER_USER="${SERVER_USER:-user}"
SERVE_ROOT="${SERVE_ROOT:-/srv/git}"
GIT_PORT="${GIT_PORT:-9418}"
CLIENTS=(${CLIENTS:-10.200.142.61 10.200.142.62 10.200.142.63 10.200.142.64})

WS_SRC="$HOME/ros2_ws/src"

# repos to serve: <mirror name>|<upstream url>|<checkout dir on the Orin>
# the Orin calls 5g_drone "umd_uas", so the mirror is symlinked under both names
REPOS=(
  "cdcl_umd_msgs|git@github.com:UMD-CDCL/cdcl_umd_msgs.git|$WS_SRC/cdcl_umd_msgs"
  "MAVInsight|git@github.com:UMD-UROC/MAVInsight.git|$WS_SRC/MAVInsight"
  "5g_drone|git@github.com:UMD-CDCL/5g_drone.git|$WS_SRC/umd_uas"
  "chimera-deploy|git@github.com:UMD-UROC/chimera-deploy.git|$HOME/chimera-deploy"
)

# chimera-deploy submodules, mirrored so 'git submodule update' works offline
SUBMODULES=(
  "rtw88|https://github.com/lwfinger/rtw88"
  "EchoTherm-Daemon|https://github.com/EchoMAV/EchoTherm-Daemon.git"
  "echopilot_deploy|https://github.com/echomav/echopilot_deploy.git"
  "Camera_Modules|git@github.com:EchoMAV/Camera_Modules.git"
  "echopilot_ai_bsp|https://github.com/EchoMAV/echopilot_ai_bsp"
)

say()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[error]\033[0m $*" >&2; exit 1; }

# the local working copy a mirror can be seeded from when GitHub is unreachable
local_source_for() {
  local name="$1"
  case "$name" in
    chimera-deploy) echo "$SCRIPT_DIR" ;;
    5g_drone)       echo "$WS_SRC/5g_drone" ;;
    *)              echo "$WS_SRC/$name" ;;
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

  # the Orins check this out as umd_uas
  ln -sfn "$SERVE_ROOT/5g_drone.git" "$SERVE_ROOT/umd_uas.git"
  echo "  linked umd_uas.git -> 5g_drone.git"

  install_daemon
  open_firewall

  say "serving on git://$SERVER_IP:$GIT_PORT/"
  ls -1 "$SERVE_ROOT" | sed 's/^/  /'
  cat <<EOF

Next:
  ./setup_git_server.sh deploy    # push the client config out to the Orins
  ./setup_git_server.sh sync      # refresh mirrors from GitHub (while on wifi)
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
# sync - refresh the mirrors from GitHub (laptop on wifi)
###############################################################################
cmd_sync() {
  github_up || die "GitHub unreachable - connect to wifi first"
  say "refreshing mirrors in $SERVE_ROOT"
  local d
  for d in "$SERVE_ROOT"/*.git; do
    [ -d "$d" ] || continue
    [ -L "$d" ] && continue
    printf '  %-22s ' "$(basename "$d")"
    if git -C "$d" remote update >/dev/null 2>&1; then
      echo "ok"
    else
      echo "FAILED"
    fi
  done
  echo
  echo "Orins can now pull. Note: branches pushed to this server by an Orin are"
  echo "kept (no prune) but are not sent to GitHub - push those on from a mirror:"
  echo "  git -C $SERVE_ROOT/<repo>.git push origin <branch>"
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

  local entry name url dir
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url dir <<< "$entry"

    if [ "$restore" = 1 ]; then
      [ -d "$dir/.git" ] || continue
      git -C "$dir" remote set-url origin "$url"
      git -C "$dir" config --unset remote.origin.pushurl || true
      echo "  $(basename "$dir") -> $url"
      continue
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

  local ip ok=0
  for ip in "${CLIENTS[@]}"; do
    say "$ip"
    if ! ping -c1 -W1 "$ip" >/dev/null 2>&1; then
      warn "unreachable - skipped"
      continue
    fi

    # let the Orin push back over ssh
    install_client_key "$ip"

    scp -q -o BatchMode=yes "${BASH_SOURCE[0]}" "$SERVER_USER@$ip:/tmp/setup_git_server.sh"
    # shellcheck disable=SC2029
    ssh -o BatchMode=yes "$SERVER_USER@$ip" \
      "SERVER_IP=$SERVER_IP SERVE_ROOT=$SERVE_ROOT GIT_PORT=$GIT_PORT bash /tmp/setup_git_server.sh remote"
    ok=$((ok + 1))
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

case "${1:-}" in
  local)  cmd_local ;;
  sync)   cmd_sync ;;
  remote) shift || true; cmd_remote "${1:-}" ;;
  deploy) cmd_deploy ;;
  status) cmd_status ;;
  *)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 1
    ;;
esac
