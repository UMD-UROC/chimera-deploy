#!/usr/bin/env python3
"""Curses-like live front end for setup_git_server.sh sync."""
from __future__ import annotations

import os
import re
import shutil
import select
import subprocess
import sys
import threading
import termios
import time
import tty
from collections import defaultdict, deque

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

ROOT = os.path.dirname(os.path.abspath(__file__))
CLIENTS = os.environ.get("CLIENTS", "10.200.142.61 10.200.142.62 10.200.142.63 10.200.142.64").split()
BOXES = ("stage", "ground", *CLIENTS)
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
    panes: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=40))
    panes["stage"] = deque(maxlen=40)
    stage = "starting"
    active = "stage"
    total_started = time.monotonic()
    total_started_wall = time.time()
    total_finished: float | None = None
    task_started: dict[str, float] = {"stage": total_started}
    task_started_wall: dict[str, float] = {"stage": total_started_wall}
    task_finished: dict[str, float] = {}
    stage_started: dict[str, float] = {}
    errors: list[str] = []
    ui = {"selected": 0, "maximized": None, "scroll": defaultdict(int), "stop_input": False}
    input_thread = threading.Thread(target=read_keys, args=(ui,), daemon=True)
    input_thread.start()
    with Live(
        get_renderable=lambda: build(stage, panes, task_started, task_started_wall,
                                      task_finished, total_started, total_started_wall,
                                      total_finished, ui),
        refresh_per_second=8, transient=True,
    ) as live:
        for raw in proc.stdout or ():
            line = ANSI.sub("", raw.replace("\r", "")).rstrip()
            if not line:
                continue
            event_key = active
            event_text = line
            match = re.search(r"stage (\d/5): (.*)", line)
            if match:
                now = time.monotonic()
                stage_key = match.group(1)
                if stage_key == "5/5":
                    task_finished["stage"] = now
                    panes["stage"].append("DONE")
                if stage in stage_started and stage_started[stage] < 0:
                    stage_started[stage] = time.monotonic()
                stage_started.setdefault(stage_key, time.monotonic())
                stage = f"{match.group(1)} {match.group(2)}"
                active = "stage"
                event_key = "stage"
            elif line.strip() == "ground":
                active = "ground"
                event_key = "ground"
            elif line.strip() in CLIENTS:
                active = line.strip()
                event_key = active
            elif line.strip().startswith("-" ):
                active = "stage"
                event_key = "stage"
            elif line.startswith("[") and "]" in line:
                host, text = line[1:].split("]", 1)
                panes[host].append(text.strip())
                event_key = host
                event_text = text.strip()
            else:
                panes[active].append(line)
                event_key = active
            machine_event = event_key == "ground" or event_key in CLIENTS
            task_start = "_START" in line.upper()
            if event_key == "stage" and event_key not in task_started:
                task_started[event_key] = time.monotonic()
                task_started_wall[event_key] = time.time()
            elif machine_event and task_start and event_key not in task_started:
                task_started[event_key] = time.monotonic()
                task_started_wall[event_key] = time.time()
                task_finished.pop(event_key, None)
            event_upper = event_text.upper()
            if event_upper.startswith("OFFLINE"):
                task_started.pop(event_key, None)
                task_started_wall.pop(event_key, None)
                task_finished.pop(event_key, None)
            elif event_upper in ("DONE", "ERROR") or event_upper.startswith("ERROR "):
                task_finished.setdefault(event_key, time.monotonic())
            if "ERROR" in line.upper() or "FAILED" in line.upper():
                errors.append(line)
            live.refresh()
        rc = proc.wait()
        panes["stage"].append("DONE" if rc == 0 else f"FAILED (exit {rc})")
        task_finished.setdefault("stage", time.monotonic())
        total_finished = time.monotonic()
        live.refresh()
    ui["stop_input"] = True
    input_thread.join(timeout=0.2)
    if errors:
        print("sync errors:")
        print("\n".join(errors))
    return rc


def build(stage: str, panes: dict[str, deque[str]], task_started: dict[str, float],
          task_started_wall: dict[str, float], task_finished: dict[str, float],
          total_started: float, total_started_wall: float,
          total_finished: float | None, ui: dict) -> Group:
    _, terminal_height = shutil.get_terminal_size(fallback=(120, 27))
    panel_height = max(5, (terminal_height - 1) // 4)
    raw_lines = max(1, panel_height - 4)
    selected_name = BOXES[ui["selected"]]
    total_end = total_finished if total_finished is not None else time.monotonic()
    total_failed = bool(panes["stage"] and "FAILED" in panes["stage"][-1].upper())
    total_state = "ERROR" if total_failed else ("DONE" if total_finished is not None else "RUNNING")
    progress = Text(
        f"sync: {total_state}  {time.strftime('%H:%M:%S', time.localtime(total_started_wall))}"
        f"  +{format_elapsed(total_end - total_started)}  {stage}",
        style="bold cyan", no_wrap=True)
    panels = {
        "stage": Panel(card("setup", panes["stage"], task_started.get("stage"), task_started_wall.get("stage"), task_finished.get("stage"), stage, raw_lines, ui["scroll"]["stage"]), title="setup", height=panel_height, border_style="bright_white" if selected_name == "stage" else "cyan"),
        "ground": Panel(card("ground", panes["ground"], task_started.get("ground"), task_started_wall.get("ground"), task_finished.get("ground"), stage, raw_lines, ui["scroll"]["ground"]), title="ground", height=panel_height, border_style="bright_white" if selected_name == "ground" else "yellow"),
    }
    drones = Table.grid(expand=True)
    drones.add_column(ratio=1)
    drones.add_column(ratio=1)
    drone_panels = []
    for host in CLIENTS:
        panels[host] = Panel(card(host, panes[host], task_started.get(host), task_started_wall.get(host), task_finished.get(host), stage, raw_lines, ui["scroll"][host]), title=host, height=panel_height, border_style="bright_white" if selected_name == host else "green")
        drone_panels.append(panels[host])
    selected = ui["maximized"] if ui["maximized"] is not None else None
    if selected is not None:
        max_height = max(5, terminal_height - 3)
        max_raw = max(1, max_height - 4)
        if selected == "stage":
            content = card("setup", panes[selected], task_started.get(selected), task_started_wall.get(selected), task_finished.get(selected), stage, max_raw, ui["scroll"][selected])
            title = "setup"
        else:
            content = card(selected, panes[selected], task_started.get(selected), task_started_wall.get(selected), task_finished.get(selected), stage, max_raw, ui["scroll"][selected])
            title = selected
        return Group(progress, Panel(content, title=title, height=max_height, border_style="bright_white"))
    for index in range(0, len(drone_panels), 2):
        drones.add_row(drone_panels[index], drone_panels[index + 1] if index + 1 < len(drone_panels) else "")
    return Group(progress, panels["stage"], panels["ground"], drones)


def card(kind: str, lines: deque[str], started: float | None,
         started_wall: float | None, finished: float | None, stage: str,
         raw_lines: int, scroll: int) -> str:
    raw = lines[-1] if lines else "waiting"
    upper = raw.upper()
    if upper.startswith("OFFLINE"):
        state = "OFFLINE"
    elif "FAILED" in upper or "ERROR" in upper:
        state = "ERROR"
    elif upper in ("DONE", "SUCCESS", "COMPLETE"):
        state = "DONE"
    elif raw == "waiting":
        state = "WAITING"
    else:
        state = "RUNNING"
    timing = ""
    if not upper.startswith("OFFLINE") and started is not None and started_wall is not None:
        end = finished if finished is not None else time.monotonic()
        timing = f"{time.strftime('%H:%M:%S', time.localtime(started_wall))}  +{format_elapsed(end - started)}"
    operation = operation_for(kind, stage, raw)
    all_lines = list(lines)
    if all_lines:
        end = max(0, len(all_lines) - scroll)
        raw_output = "\n".join(all_lines[max(0, end - raw_lines):end])
    else:
        raw_output = "waiting"
    return f"{high_level_for(kind)}\n{operation}: {state}{('  ' + timing) if timing else ''}\n{raw_output}"


def read_keys(ui: dict) -> None:
    if not sys.stdin.isatty():
        return
    old = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while not ui["stop_input"]:
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not ready:
                continue
            key = sys.stdin.read(1)
            if key == "\t":
                ui["selected"] = (ui["selected"] + 1) % len(BOXES)
            elif key == "\x1b":
                sequence = ""
                while select.select([sys.stdin], [], [], 0.03)[0]:
                    sequence += sys.stdin.read(1)
                if sequence == "[Z":
                    ui["selected"] = (ui["selected"] - 1) % len(BOXES)
                elif sequence.endswith("~"):
                    ui["scroll"][BOXES[ui["selected"]]] += 3 if sequence.startswith("[5") else -3
                elif sequence in ("[A", "[D"):
                    ui["selected"] = (ui["selected"] - 1) % len(BOXES)
                elif sequence in ("[B", "[C"):
                    ui["selected"] = (ui["selected"] + 1) % len(BOXES)
                else:
                    ui["maximized"] = None
            elif key in ("\r", "\n"):
                ui["maximized"] = BOXES[ui["selected"]]
            elif key == "q" and ui.get("complete"):
                ui["stop_input"] = True
            elif key == "\x7f":
                ui["scroll"][BOXES[ui["selected"]]] = 0
            for box in BOXES:
                ui["scroll"][box] = max(0, ui["scroll"][box])
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


def high_level_for(kind: str) -> str:
    if kind == "setup":
        return "Synchronize setup and source state"
    if kind == "ground":
        return "Update ground px4sim stack"
    return "Update drone from ground"


def operation_for(kind: str, stage: str, raw: str) -> str:
    if raw == "waiting":
        return "waiting"
    if raw.upper().startswith("OFFLINE"):
        return "offline"
    if raw.upper() in ("DONE", "SUCCESS", "COMPLETE"):
        return "complete"
    text = f"{stage} {raw}".lower() if kind == "setup" else raw.lower()
    for word, purpose in (
        ("error", "failed"),
        ("failed", "failed"),
        ("restart", "restarting"),
        ("stopping", "stopping"),
        ("building", "rebuilding"),
        ("rebuilding", "rebuilding"),
        ("build_start", "rebuilding"),
        ("sync_start", "syncing source"),
        ("sync", "synchronizing"),
        ("refresh", "refreshing mirrors"),
        ("publish", "publishing branches"),
        ("scene", "synchronizing scenes"),
        ("config", "configuring drones"),
        ("flight_testing", "synchronizing source"),
    ):
        if word in text:
            return purpose
    return "working"


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
