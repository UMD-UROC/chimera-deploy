#!/usr/bin/env python3
"""Curses-like live front end for setup_git_server.sh sync."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict, deque

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

ROOT = os.path.dirname(os.path.abspath(__file__))
CLIENTS = os.environ.get("CLIENTS", "10.200.142.61 10.200.142.62 10.200.142.63 10.200.142.64").split()
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>]")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] != "sync":
        args = ["sync", *args]
    env = os.environ.copy()
    env["SYNC_UI"] = "1"
    proc = subprocess.Popen(
        [os.path.join(ROOT, "setup_git_server.sh"), *args],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    panes: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=5))
    panes["stage"] = deque(maxlen=20)
    stage = "starting"
    with Live(build(stage, panes), refresh_per_second=8, transient=False) as live:
        for raw in proc.stdout or ():
            line = ANSI.sub("", raw.replace("\r", "")).rstrip()
            if not line:
                continue
            match = re.search(r"stage (\d/5): (.*)", line)
            if match:
                stage = f"{match.group(1)} {match.group(2)}"
            elif line.startswith("[") and "]" in line:
                host, text = line[1:].split("]", 1)
                panes[host].append(text.strip())
            else:
                panes["stage"].append(line)
            live.update(build(stage, panes))
        rc = proc.wait()
        panes["stage"].append("DONE" if rc == 0 else f"FAILED (exit {rc})")
        live.update(build(stage, panes))
    return rc


def build(stage: str, panes: dict[str, deque[str]]) -> Group:
    blocks = [Panel("\n".join(panes["stage"]) or "waiting", title=f"SYNC  {stage}", border_style="cyan")]
    for host in CLIENTS:
        blocks.append(Panel("\n".join(panes[host]) or "waiting", title=host, border_style="green"))
    blocks.append(Panel("\n".join(panes["ground"]) or "waiting", title="ground", border_style="yellow"))
    return Group(*blocks)


if __name__ == "__main__":
    raise SystemExit(main())
