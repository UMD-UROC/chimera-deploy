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
#                                 Dependabot branches
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
  "px4_msgs|git@github.com:PX4/px4_msgs.git|$WS_SRC/px4_msgs"
  "px4-sim-stack|git@github.com:UMD-CDCL/px4-sim-stack.git|$HOME/px4-sim-stack"
  "chimera-deploy|git@github.com:UMD-UROC/chimera-deploy.git|$HOME/chimera-deploy"
)

# chimera-deploy submodules, mirrored so 'git submodule update' works offline
SUBMODULES=(
  "rtw88|https://github.com/lwfinger/rtw88"
  "EchoTherm-Daemon|https://github.com/EchoMAV/EchoTherm-Daemon.git"
  "echopilot_deploy|https://github.com/echomav/echopilot_deploy.git"
  "Camera_Modules|git@github.com:EchoMAV/Camera_Modules.git"
  "echopilot_ai_bsp|https://github.com/EchoMAV/echopilot_ai_bsp"
  "mavros|https://github.com/mavlink/mavros.git"
  "angles|https://github.com/ros/angles.git"
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
    px4-sim-stack)  echo "$HOME/px4-sim-stack" ;;
    *)              echo "$WS_SRC/$name" ;;
  esac
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
  local do_push=1 subs=0 upstream=1 push_new=0 do_local=1 clean_dependabot=0 arg
  for arg in "$@"; do
    case "$arg" in
      --no-push)     do_push=0 ;;
      --submodules)  subs=1 ;;
      --no-upstream) upstream=0 ;;
      --push-new)    push_new=1 ;;
      --no-local)    do_local=0 ;;
      --clean-dependabot) clean_dependabot=1 ;;
      *) die "unknown option for sync: $arg" ;;
    esac
  done

  # drone commits -> GitHub, laptop commits -> GitHub, GitHub -> laptop,
  # GitHub -> mirrors, mirrors -> drones. Every step before the refresh has to
  # land first, or the forced mirror fetch overwrites what it has not seen.
  if github_up; then
    if [ "$upstream" = 1 ]; then
      push_mirrors_upstream "$push_new" "$clean_dependabot"
    fi

    if [ "$do_local" = 1 ]; then
      sync_local_worktrees 1 "$push_new"
    fi

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
  elif [ "$do_push" = 1 ]; then
    warn "GitHub unreachable - skipping the mirror refresh, pushing what we have"
    # the mirrors still hold whatever the drones pushed over the LAN, so the
    # laptop can pick those up without wifi
    if [ "$do_local" = 1 ]; then
      sync_local_worktrees 0 "$push_new"
    fi
  else
    die "GitHub unreachable - connect to wifi first"
  fi

  local clients_pid='' ground_pid='' clients_log='' ground_log='' rc=0
  if [ "$do_push" = 1 ]; then
    # The ground image has no dependency on an aircraft image.  Start both
    # sides now; each side still waits for and reports all of its own jobs.
    clients_log="$(mktemp -t chimera-sync-clients.XXXXXX)"
    (cmd_push $([ "$subs" = 1 ] && echo --submodules)) >"$clients_log" 2>&1 &
    clients_pid=$!
  else
    echo
    echo "Mirrors updated. Send them to the Orins with:"
    echo "  ./setup_git_server.sh push"
  fi

  if [ "$do_local" = 1 ]; then
    ground_log="$(mktemp -t chimera-sync-ground.XXXXXX)"
    refresh_local_stack >"$ground_log" 2>&1 &
    ground_pid=$!
  fi

  if [ -n "$clients_pid" ]; then
    wait "$clients_pid" || rc=1
    cat "$clients_log"
    rm -f "$clients_log"
  fi
  if [ -n "$ground_pid" ]; then
    wait "$ground_pid" || rc=1
    cat "$ground_log"
    rm -f "$ground_log"
  fi
  if [ "$rc" != 0 ]; then
    warn "one or more parallel sync jobs failed"
    return "$rc"
  fi

  if [ "$upstream" = 0 ]; then
    echo
    echo "Note: --no-upstream was given, so branches the Orins pushed here have"
    echo "not been sent to GitHub. Send one on with:"
    echo "  git -C $SERVE_ROOT/<repo>.git -c remote.origin.mirror=false \\"
    echo "      push origin <branch>"
  fi
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

  local d name url remote_heads sha ref branch gh out rc pushed=0 held=0 cleaned=0
  for d in "$SERVE_ROOT"/*.git; do
    [ -d "$d" ] || continue
    [ -L "$d" ] && continue
    name="$(basename "$d" .git)"

    url="$(git -C "$d" config --get remote.origin.url 2>/dev/null || true)"
    [ -n "$url" ] || continue

    remote_heads="$(timeout 30 git ls-remote --heads "$url" 2>/dev/null)" || {
      warn "  $name: cannot reach $url - skipped"
      continue
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
  done

  if [ "$pushed" = 0 ] && [ "$held" = 0 ] && [ "$cleaned" = 0 ]; then
    echo "  nothing to send - GitHub already has every mirror branch"
  else
    echo "  sent $pushed branch(es) to GitHub, $held held back, $cleaned obsolete Dependabot branch(es) removed"
  fi
  return 0
}

###############################################################################
# push - from the laptop, shove the mirrors into every Orin's working copy
#
# Each Orin repo gets receive.denyCurrentBranch=updateInstead, so a push to the
# branch it has checked out updates the working tree too - no 'git pull' on the
# drone. A dirty tree makes git refuse that ref, so local edits are never lost.
###############################################################################
cmd_push() {
  local subs=0 arg
  for arg in "$@"; do
    case "$arg" in
      --submodules) subs=1 ;;
      *) die "unknown option for push: $arg" ;;
    esac
  done

  # Each aircraft has its own checkout, Docker daemon and GPU, so rebuilding
  # them serially only burns operator time.  Keep the ground refresh outside
  # this function (cmd_sync calls it after us): it must see the completed
  # fleet, but the aircraft jobs themselves are independent.
  local ip ok=0 index rc
  local -a clients=() jobs=() logs=()
  for ip in "${CLIENTS[@]}"; do
    if ! ping -c1 -W1 "$ip" >/dev/null 2>&1; then
      say "$ip"
      warn "unreachable - skipped"
      continue
    fi
    clients+=("$ip")
    logs+=("$(mktemp -t chimera-sync-client.XXXXXX)")
    # Redirect each job rather than letting parallel SSH/Docker output splice
    # together.  The completed log is printed under its aircraft heading.
    (push_to_client "$ip" "$subs") >"${logs[-1]}" 2>&1 &
    jobs+=("$!")
  done

  for index in "${!jobs[@]}"; do
    say "${clients[$index]}"
    rc=0
    wait "${jobs[$index]}" || rc=$?
    cat "${logs[$index]}"
    rm -f "${logs[$index]}"
    if [ "$rc" = 0 ]; then
      ok=$((ok + 1))
    else
      warn "${clients[$index]}: update or restart failed"
    fi
  done

  say "pushed to $ok of ${#CLIENTS[@]} clients"
}

refresh_local_stack() {
  local stack="$HOME/px4-sim-stack"
  [ -x "$stack/px4sim" ] || { warn "local px4-sim-stack is missing - skipped build"; return 1; }
  say "building and restarting the local stack"
  # A sync can change a Docker build context, configuration, or a bind-mounted
  # runtime input outside the set of files Git reports as updated. Always use
  # the disruptive front door here; `start` deliberately no-ops when running.
  (cd "$stack" && ./px4sim restart)
}

push_to_client() {
  local ip="$1" subs="$2"
  local ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)

  local rhome
  rhome="$(ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" 'echo "$HOME"' 2>/dev/null)" || {
    warn "ssh failed - skipped"
    return 1
  }

  # A successful push is deliberately sufficient to restart. Git may say a
  # ref is up to date while a generated input, image context, or a previous
  # partial deployment still warrants recreating the runtime stack. Err toward
  # a safe restart; dirty/rejected trees are still left untouched.
  local entry name url dir rdir mirror state branch tree out restart_required=0
  for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url dir <<< "$entry"
    # REPOS paths are laptop-side; the Orin's home may sit elsewhere
    rdir="${dir/#$HOME/$rhome}"
    mirror="$SERVE_ROOT/$name.git"

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
    export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=5"

    # no force here: a rejected ref means the Orin has commits we would destroy
    out="$(git -C "$mirror" push --quiet "$target" \
             'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' 2>&1)" || rc=$?

    # second pass on purpose - git maps each local ref to a single destination
    # per push, so the tracking refs are silently dropped if bundled above.
    # Forced, otherwise the Orin's 'git status' reports a phantom divergence.
    git -C "$mirror" push --quiet "$target" \
        '+refs/heads/*:refs/remotes/origin/*' >/dev/null 2>&1 || true

    if [ "$rc" = 0 ]; then
      echo "ok ($branch)"
      restart_required=1
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

    if [ "$subs" = 1 ] && [ "$name" = chimera-deploy ]; then
      update_client_submodules "$ip" "$rdir"
    fi
  done

  if [ "$restart_required" = 1 ]; then
    say "$ip: rebuilding and restarting through px4sim"
    if ! ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
         "cd '$rhome/px4-sim-stack' && ./px4sim restart"; then
      warn "$ip: px4sim restart failed after sync"
      return 1
    fi
  else
    echo "  no repository updates; stack left running"
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

  local ip ok=0
  for ip in "${CLIENTS[@]}"; do
    say "$ip"
    if ! ping -c1 -W1 "$ip" >/dev/null 2>&1; then
      warn "unreachable - skipped"
      continue
    fi
    scenes_to_client "$ip" && ok=$((ok + 1))
  done

  say "sent the scenes to $ok of ${#CLIENTS[@]} clients"
}

scenes_to_client() {
  local ip="$1" count out changed=0
  local src="$HOME/$SCENES_REL"
  local ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)

  if ! ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" "[ -d ~/$SCENES_REL ]" 2>/dev/null; then
    warn "no ~/$SCENES_REL there - run deploy_onboard.sh on it first"
    return 1
  fi

  # The generated directories only. The vehicle models and spawn_scenario.py
  # are tracked, so they arrive with the checkout and must survive this.
  # --delete drops what a rebuilt scene no longer writes.
  out="$(rsync -ai --delete -e "ssh ${ssh_opts[*]}" \
      "$src/worlds/" "$SERVER_USER@$ip:$SCENES_REL/worlds/")" || { warn "worlds failed"; return 1; }
  [ -z "$out" ] || changed=1
  out="$(rsync -ai --delete -e "ssh ${ssh_opts[*]}" \
      "$src/scenarios/" "$SERVER_USER@$ip:$SCENES_REL/scenarios/")" || { warn "scenarios failed"; return 1; }
  [ -z "$out" ] || changed=1
  out="$(rsync -ai -e "ssh ${ssh_opts[*]}" \
      --include='*_terrain/***' --include='*_buildings/***' --exclude='*' \
      "$src/models/" "$SERVER_USER@$ip:$SCENES_REL/models/")" || { warn "models failed"; return 1; }
  [ -z "$out" ] || changed=1

  count=$(ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
    "ls ~/$SCENES_REL/worlds/*_surface.json 2>/dev/null | wc -l")
  echo "  $count scenes"

  if [ "$changed" = 1 ]; then
    say "$ip: scene files changed; rebuilding and restarting through px4sim"
    ssh "${ssh_opts[@]}" "$SERVER_USER@$ip" \
      "cd ~/px4-sim-stack && ./px4sim restart" || { warn "scene-triggered px4sim restart failed"; return 1; }
  else
    echo "  scene files unchanged; stack left running"
  fi
}

###############################################################################

case "${1:-}" in
  local)  cmd_local ;;
  scenes) cmd_scenes ;;
  sync)   shift || true; cmd_sync "$@" ;;
  push)   shift || true; cmd_push "$@" ;;
  remote) shift || true; cmd_remote "${1:-}" ;;
  deploy) cmd_deploy ;;
  status) cmd_status ;;
  *)
    sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 1
    ;;
esac
