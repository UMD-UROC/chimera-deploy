"""Resolve machine-local sync paths; never execute the configuration file."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parent
ROS_REPOS = ("cdcl_umd_msgs", "MAVInsight", "5g_drone", "tracking_test_5g", "px4_msgs")


def path_value(value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\n\r\0|"):
        raise ValueError("paths must be nonempty strings without newlines or '|'")
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():
        raise ValueError(f"use an absolute path or ~/ path: {value}")
    return path.resolve()


def load_config() -> dict:
    config_path = path_value(os.environ.get("CHIMERA_SYNC_CONFIG", str(
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "chimera-deploy/config.toml")))
    data = {}
    if config_path.exists():
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError as exc:
                raise ValueError("install sync dependencies: python3 -m pip install --user -r requirements-sync.txt") from exc
        with config_path.open("rb") as stream:
            data = tomllib.load(stream)
    unknown = set(data) - {"ground", "repos"}
    if unknown:
        raise ValueError(f"unknown config sections: {', '.join(sorted(unknown))}")
    ground = data.get("ground", {})
    overrides = data.get("repos", {})
    if not isinstance(ground, dict) or not isinstance(overrides, dict):
        raise ValueError("ground and repos must be tables")
    unknown = set(ground) - {"ros_workspace", "px4_msgs_repo", "px4_sim_stack"}
    if unknown:
        raise ValueError(f"unknown ground settings: {', '.join(sorted(unknown))}")
    ws = path_value(os.environ.get("CHIMERA_ROS_WORKSPACE", ground.get("ros_workspace", "~/ros2_ws")))
    repos = {name: ws / "src" / name for name in ROS_REPOS}
    repos.update({"px4-sim-stack": Path.home() / "px4-sim-stack", "chimera-deploy": ROOT})
    if "px4_msgs_repo" in ground:
        repos["px4_msgs"] = path_value(ground["px4_msgs_repo"])
    if "px4_sim_stack" in ground:
        repos["px4-sim-stack"] = path_value(ground["px4_sim_stack"])
    for name, value in overrides.items():
        if name not in repos:
            raise ValueError(f"unknown repository: {name}")
        repos[name] = path_value(value)
    for name in repos:
        env_name = "CHIMERA_REPO_" + name.upper().replace("-", "_")
        if env_name in os.environ:
            repos[name] = path_value(os.environ[env_name])
    custom_paths = bool(ground or overrides or "CHIMERA_ROS_WORKSPACE" in os.environ
                        or any("CHIMERA_REPO_" + name.upper().replace("-", "_") in os.environ for name in repos))
    return {"file": config_path, "workspace": ws, "repos": repos, "custom_paths": custom_paths}


def stack_alignment(config: dict) -> str:
    """Compare against PX4Sim's existing .env without sourcing or rewriting it."""
    # Existing installations keep their behavior until they opt into path
    # configuration. A new guard must not block an unchanged default setup.
    if not config["custom_paths"]:
        return ""
    stack = config["repos"]["px4-sim-stack"]
    env_file = stack / ".env"
    value = os.environ.get("ROS2_WS_DIR", "../ros2_ws")
    if "ROS2_WS_DIR" not in os.environ and env_file.is_file():
        for line in env_file.read_text().splitlines():
            key, sep, candidate = line.strip().removeprefix("export ").partition("=")
            if sep and key.strip() == "ROS2_WS_DIR":
                tokens = shlex.split(candidate, comments=True)
                if len(tokens) != 1:
                    return f"cannot resolve ROS2_WS_DIR in {env_file}"
                value = tokens[0]
    expanded = os.path.expandvars(os.path.expanduser(value))
    if "$" in expanded:
        return f"cannot resolve ROS2_WS_DIR={value} in {env_file}"
    actual = (stack / expanded).resolve()
    if actual != config["workspace"]:
        return f"PX4Sim ROS2_WS_DIR resolves to {actual}, but sync workspace is {config['workspace']}; update your local config or {env_file}"
    # PX4Sim stages these sources from the workspace, not individual overrides.
    for name in ("cdcl_umd_msgs", "MAVInsight", "5g_drone", "tracking_test_5g"):
        if config["repos"][name].resolve() != (actual / "src" / name).resolve():
            return f"PX4Sim expects {name} at {actual / 'src' / name}, but sync uses {config['repos'][name]}"
    return ""


def shell_config() -> None:
    config = load_config()
    for key, value in {"SYNC_CONFIG_FILE": config["file"], "GROUND_WS": config["workspace"],
                       "GROUND_STACK": config["repos"]["px4-sim-stack"],
                       "STACK_ALIGNMENT_ERROR": stack_alignment(config)}.items():
        print(f"{key}={shlex.quote(str(value))}")
    print("declare -A GROUND_REPOS=(")
    for name, path in config["repos"].items():
        print(f"[{shlex.quote(name)}]={shlex.quote(str(path))}")
    print(")")


if __name__ == "__main__":
    try:
        shell_config()
    except (ValueError, OSError) as exc:
        print(f"sync configuration: {exc}", file=sys.stderr)
        sys.exit(1)
