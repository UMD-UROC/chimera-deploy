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


def display_name(host: str) -> str:
    match = re.fullmatch(r"10\.200\.142\.6(\d+)", host)
    return f"uas{match.group(1)}" if match else host


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] != "sync":
        args = ["sync", *args]

    # Status is intentionally a plain, read-only CLI command.  Do not start
    # the Rich live dashboard for this lightweight query.
    if "--status" in args:
        return subprocess.call(
            [os.path.join(ROOT, "setup_git_server.sh"), *args], cwd=ROOT
        )

    env = os.environ.copy()
    env["SYNC_UI"] = "1"
    proc = subprocess.Popen(
        [os.path.join(ROOT, "setup_git_server.sh"), *args],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    # Keep the complete output for each process.  The renderer only shows the
    # portion that fits in a pane, and the existing scroll controls let the
    # operator inspect older lines.
    panes: dict[str, deque[str]] = defaultdict(deque)
    panes["stage"] = deque()
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
    ui = {"selected": 0, "maximized": None, "scroll": defaultdict(int), "scroll_max": defaultdict(int), "stop_input": False, "complete": False, "quit": False, "ground_column": 0}
    input_thread = threading.Thread(target=read_keys, args=(ui,), daemon=True)
    input_thread.start()
    enable_mouse()
    with Live(
        get_renderable=lambda: build(stage, panes, task_started, task_started_wall,
                                      task_finished, total_started, total_started_wall,
                                      total_finished, ui),
        refresh_per_second=12, transient=False,
    ) as live:
        for raw in proc.stdout or ():
            stored = raw.replace("\r", "").rstrip("\n")
            line = ANSI.sub("", stored)
            if not line.strip():
                continue
            event_key = active
            event_text = line
            match = re.search(r"stage (\d/5): (.*)", line)
            if match:
                panes["stage"].append(stored)
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
                panes[host].append(stored[stored.find("]") + 1:].strip())
                event_key = host
                event_text = text.strip()
            else:
                panes[active].append(stored)
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
        rc = proc.wait()
        panes["stage"].append("DONE" if rc == 0 else f"FAILED (exit {rc})")
        task_finished.setdefault("stage", time.monotonic())
        total_finished = time.monotonic()
        ui["complete"] = True
        live.refresh()
        while not ui["quit"]:
            time.sleep(0.1)
            live.refresh()
    ui["stop_input"] = True
    disable_mouse()
    input_thread.join(timeout=0.2)
    if errors:
        print("sync completed with errors:")
        print("\n".join(errors))
    else:
        print("sync completed with no errors")
    return rc


def build(stage: str, panes: dict[str, deque[str]], task_started: dict[str, float],
          task_started_wall: dict[str, float], task_finished: dict[str, float],
          total_started: float, total_started_wall: float,
          total_finished: float | None, ui: dict) -> Group:
    _, terminal_height = shutil.get_terminal_size(fallback=(120, 27))
    panel_height = max(5, (terminal_height - 2) // 4)
    raw_lines = max(1, panel_height - 4)
    for box in BOXES:
        ui["scroll_max"][box] = max(0, len(panes[box]) - raw_lines)
        ui["scroll"][box] = min(ui["scroll"][box], ui["scroll_max"][box])
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
        panels[host] = Panel(card(host, panes[host], task_started.get(host), task_started_wall.get(host), task_finished.get(host), stage, raw_lines, ui["scroll"][host]), title=display_name(host), height=panel_height, border_style="bright_white" if selected_name == host else "green")
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
            title = display_name(selected)
        return Group(progress, Panel(content, title=title, height=max_height, border_style="bright_white"), footer(ui))
    for index in range(0, len(drone_panels), 2):
        drones.add_row(drone_panels[index], drone_panels[index + 1] if index + 1 < len(drone_panels) else "")
    return Group(progress, panels["stage"], panels["ground"], drones, footer(ui))


def footer(ui: dict) -> Text:
    if ui["complete"]:
        return Text("DONE — q quit", style="bold green", no_wrap=True)
    return Text("tab/shift-tab or arrows select · pgup/pgdn scroll · enter maximize · esc restore", style="dim", no_wrap=True)


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
    header = Text()
    header.append(high_level_for(kind) + "\n", style="bold")
    header.append(f"{operation}: {state}{('  ' + timing) if timing else ''}\n",
                  style="cyan" if state == "RUNNING" else
                        "green" if state == "DONE" else
                        "red" if state == "ERROR" else "yellow")
    header.append_text(Text.from_ansi(raw_output))
    return header


def enable_mouse() -> None:
    if sys.stdout.isatty():
        # SGR mouse mode gives unambiguous coordinates and wheel events.
        sys.stdout.write("\x1b[?1000h\x1b[?1006h")
        sys.stdout.flush()


def disable_mouse() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[?1006l\x1b[?1000l")
        sys.stdout.flush()


def read_keys(ui: dict) -> None:
    if not sys.stdin.isatty():
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    pending = b""
    last_input = time.monotonic()
    try:
        tty.setcbreak(fd)
        while not ui["stop_input"]:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                pending += os.read(fd, 64)
                last_input = time.monotonic()
            while pending:
                known = {
                    b"\x1b[A": "up", b"\x1b[B": "down",
                    b"\x1b[C": "right", b"\x1b[D": "left",
                    b"\x1b[Z": "back", b"\x1b[5~": "pageup",
                    b"\x1b[6~": "pagedown",
                }
                matched = next((sequence for sequence in known if pending.startswith(sequence)), None)
                if matched is not None:
                    handle_key(known[matched], ui)
                    pending = pending[len(matched):]
                elif pending.startswith(b"\t"):
                    handle_key("tab", ui); pending = pending[1:]
                elif pending.startswith(b"\r") or pending.startswith(b"\n"):
                    handle_key("enter", ui); pending = pending[1:]
                elif pending.startswith(b"q"):
                    handle_key("q", ui); pending = pending[1:]
                elif pending.startswith(b"\x7f"):
                    handle_key("reset", ui); pending = pending[1:]
                elif pending.startswith(b"\x1b"):
                    mouse = re.match(rb"\x1b\[<([0-9]+);([0-9]+);([0-9]+)([mM])", pending)
                    if mouse:
                        end = mouse.end()
                        handle_mouse(int(mouse.group(1)), int(mouse.group(2)), int(mouse.group(3)), ui)
                        pending = pending[end:]
                        continue
                    if len(pending) == 1 and time.monotonic() - last_input < 0.12:
                        break
                    handle_key("esc", ui); pending = pending[1:]
                else:
                    pending = pending[1:]
            for box in BOXES:
                ui["scroll"][box] = max(0, ui["scroll"][box])
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def handle_key(key: str, ui: dict) -> None:
    if key == "tab":
        ui["selected"] = (ui["selected"] + 1) % len(BOXES)
    elif key == "back":
        ui["selected"] = (ui["selected"] - 1) % len(BOXES)
    elif key in ("up", "down", "left", "right"):
        move_arrow(ui, {"up": "A", "down": "B", "left": "D", "right": "C"}[key])
    elif key == "pageup":
        box = BOXES[ui["selected"]]
        ui["scroll"][box] = min(ui["scroll"][box] + 3, ui["scroll_max"].get(box, 0))
    elif key == "pagedown":
        box = BOXES[ui["selected"]]
        ui["scroll"][box] = max(0, ui["scroll"][box] - 3)
    elif key == "enter":
        ui["maximized"] = BOXES[ui["selected"]]
    elif key == "esc":
        ui["maximized"] = None
    elif key == "q" and ui.get("complete"):
        ui["quit"] = True
    elif key == "reset":
        ui["scroll"][BOXES[ui["selected"]]] = 0


def handle_mouse(button: int, x: int, y: int, ui: dict) -> None:
    box = box_at(x, y, ui)
    if box is None:
        return
    ui["selected"] = BOXES.index(box)
    if button in (64, 65):
        delta = 3 if button == 64 else -3
        ui["scroll"][box] = max(0, min(ui["scroll"][box] + delta,
                                        ui["scroll_max"].get(box, 0)))


def box_at(x: int, y: int, ui: dict) -> str | None:
    if ui["maximized"] is not None:
        return ui["maximized"]
    _, height = shutil.get_terminal_size(fallback=(120, 27))
    panel_height = max(5, (height - 2) // 4)
    if 2 <= y < 2 + panel_height:
        return "stage"
    if 2 + panel_height <= y < 2 + 2 * panel_height:
        return "ground"
    if y >= 2 + 2 * panel_height:
        col = 0 if x < max(1, shutil.get_terminal_size(fallback=(120, 27))[0] // 2) else 1
        row = 0 if y < 2 + 3 * panel_height else 1
        index = row * 2 + col
        return CLIENTS[index] if index < len(CLIENTS) else None
    return None


def move_arrow(ui: dict, direction: str) -> None:
    current = BOXES[ui["selected"]]
    left, right = CLIENTS[0], CLIENTS[1]
    lower_left, lower_right = CLIENTS[2], CLIENTS[3]

    if current == "stage":
        if direction == "B":
            ui["selected"] = BOXES.index("ground")
        return
    if current == "ground":
        if direction == "A":
            ui["selected"] = BOXES.index("stage")
        elif direction == "B":
            column = ui.get("ground_column", 0)
            ui["selected"] = BOXES.index(right if column else left)
        elif direction == "C":
            ui["ground_column"] = 1
        elif direction == "D":
            ui["ground_column"] = 0
        return

    if current in (left, right):
        column = 1 if current == right else 0
        ui["ground_column"] = column
        if direction == "A":
            ui["selected"] = BOXES.index("ground")
        elif direction == "B":
            ui["selected"] = BOXES.index(lower_right if column else lower_left)
        elif direction == "C" and current == left:
            ui["selected"] = BOXES.index(right)
        elif direction == "D" and current == right:
            ui["selected"] = BOXES.index(left)
        return

    if current in (lower_left, lower_right):
        column = 1 if current == lower_right else 0
        if direction == "A":
            ui["selected"] = BOXES.index(right if column else left)
        elif direction == "C" and current == lower_left:
            ui["selected"] = BOXES.index(lower_right)
        elif direction == "D" and current == lower_right:
            ui["selected"] = BOXES.index(lower_left)


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
