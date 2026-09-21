#!/usr/bin/env python3
"""Curses-like live front end for setup_git_server.sh sync."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections import defaultdict, deque

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

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
    panes["stage"] = deque(maxlen=3)
    stage = "starting"
    active = "stage"
    with Live(build(stage, panes), refresh_per_second=8, transient=False) as live:
        for raw in proc.stdout or ():
            line = ANSI.sub("", raw.replace("\r", "")).rstrip()
            if not line:
                continue
            match = re.search(r"stage (\d/5): (.*)", line)
            if match:
                stage = f"{match.group(1)} {match.group(2)}"
                active = "stage"
            elif line.strip() == "ground":
                active = "ground"
            elif line.strip() in CLIENTS:
                active = line.strip()
            elif line.strip().startswith("-" ):
                active = "stage"
            elif line.startswith("[") and "]" in line:
                host, text = line[1:].split("]", 1)
                panes[host].append(text.strip())
            else:
                panes[active].append(line)
            live.update(build(stage, panes))
        rc = proc.wait()
        panes["stage"].append("DONE" if rc == 0 else f"FAILED (exit {rc})")
        live.update(build(stage, panes))
    return rc


def build(stage: str, panes: dict[str, deque[str]]) -> Group:
    progress = Text(f"sync: {stage}", style="bold cyan", no_wrap=True)
    stage_panel = Panel(card("overall sync progress", panes["stage"]), title="stages", height=5, border_style="cyan")
    ground_panel = Panel(card("ground build and restart", panes["ground"]), title="ground", height=5, border_style="yellow")
    drones = Table.grid(expand=True)
    drones.add_column(ratio=1)
    drones.add_column(ratio=1)
    drone_panels = []
    for host in CLIENTS:
        drone_panels.append(Panel(card("source sync and rebuild", panes[host]), title=host, height=5, border_style="green"))
    for index in range(0, len(drone_panels), 2):
        drones.add_row(drone_panels[index], drone_panels[index + 1] if index + 1 < len(drone_panels) else "")
    return Group(progress, stage_panel, ground_panel, drones)


def card(purpose: str, lines: deque[str]) -> str:
    raw = lines[-1] if lines else "waiting"
    upper = raw.upper()
    if "OFFLINE" in upper:
        state = "OFFLINE"
    elif "FAILED" in upper or "ERROR" in upper:
        state = "ERROR"
    elif upper == "DONE" or "SUCCESS" in upper or "COMPLETE" in upper:
        state = "DONE"
    elif raw == "waiting":
        state = "WAITING"
    else:
        state = "RUNNING"
    return f"{purpose}\n{state}  {time.strftime('%H:%M:%S')}\n{raw}"


if __name__ == "__main__":
    raise SystemExit(main())
