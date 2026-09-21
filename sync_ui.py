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
    total_started = time.monotonic()
    task_started: dict[str, float] = {}
    task_finished: dict[str, float] = {}
    stage_started: dict[str, float] = {}
    errors: list[str] = []
    with Live(build(stage, panes, task_started, task_finished), refresh_per_second=8, transient=False) as live:
        for raw in proc.stdout or ():
            line = ANSI.sub("", raw.replace("\r", "")).rstrip()
            if not line:
                continue
            match = re.search(r"stage (\d/5): (.*)", line)
            if match:
                now = time.monotonic()
                if stage != "starting":
                    task_finished["stage"] = now
                task_started["stage"] = now
                task_finished.pop("stage", None)
                if stage in stage_started and stage_started[stage] < 0:
                    stage_started[stage] = time.monotonic()
                stage_key = match.group(1)
                stage_started.setdefault(stage_key, time.monotonic())
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
                active = host
                panes[host].append(text.strip())
            else:
                panes[active].append(line)
            task_started.setdefault(active, time.monotonic())
            if "OFFLINE" in line.upper():
                task_started.pop(active, None)
                task_finished.pop(active, None)
            elif any(word in line.upper() for word in ("DONE", "ERROR", "FAILED")):
                task_finished.setdefault(active, time.monotonic())
            if "ERROR" in line.upper() or "FAILED" in line.upper():
                errors.append(line)
            live.update(build(stage, panes, task_started, task_finished))
        rc = proc.wait()
        panes["stage"].append("DONE" if rc == 0 else f"FAILED (exit {rc})")
        live.update(build(stage, panes, task_started, task_finished))
    if errors:
        print("sync errors:")
        print("\n".join(errors))
    return rc


def build(stage: str, panes: dict[str, deque[str]], task_started: dict[str, float], task_finished: dict[str, float]) -> Group:
    progress = Text(f"sync: {stage}", style="bold cyan", no_wrap=True)
    stage_panel = Panel(card("setup", panes["stage"], task_started.get("stage"), task_finished.get("stage"), stage), title="setup", height=5, border_style="cyan")
    ground_panel = Panel(card("ground", panes["ground"], task_started.get("ground"), task_finished.get("ground"), stage), title="ground", height=5, border_style="yellow")
    drones = Table.grid(expand=True)
    drones.add_column(ratio=1)
    drones.add_column(ratio=1)
    drone_panels = []
    for host in CLIENTS:
        drone_panels.append(Panel(card(host, panes[host], task_started.get(host), task_finished.get(host), stage), title=host, height=5, border_style="green"))
    for index in range(0, len(drone_panels), 2):
        drones.add_row(drone_panels[index], drone_panels[index + 1] if index + 1 < len(drone_panels) else "")
    return Group(progress, stage_panel, ground_panel, drones)


def card(kind: str, lines: deque[str], started: float | None, finished: float | None, stage: str) -> str:
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
    timing = ""
    if "OFFLINE" not in upper and started is not None:
        end = finished if finished is not None else time.monotonic()
        timing = f"{time.strftime('%H:%M:%S')}  +{format_elapsed(end - started)}"
    return f"{purpose_for(kind, stage, raw)}\n{state}{('  ' + timing) if timing else ''}\n{raw}"


def purpose_for(kind: str, stage: str, raw: str) -> str:
    if raw == "waiting" and kind != "setup":
        return "waiting"
    text = f"{stage} {raw}".lower()
    for word, purpose in (
        ("offline", "offline"),
        ("stopping", "stopping"),
        ("building", "rebuilding"),
        ("rebuilding", "rebuilding"),
        ("restarting", "restarting"),
        ("starting", "starting"),
        ("sync", "synchronizing"),
        ("refresh", "refreshing mirrors"),
        ("publish", "publishing branches"),
        ("scene", "synchronizing scenes"),
        ("config", "configuring drones"),
    ):
        if word in text:
            return purpose
    return "setup" if kind == "setup" else "working"


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
