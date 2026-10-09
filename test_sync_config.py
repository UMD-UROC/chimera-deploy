"""Configuration and shell integration tests; no network, Docker or ROS builds."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import sync_config

ROOT = Path(__file__).resolve().parent
SCRIPT = (ROOT / "setup_git_server.sh").read_text()
FUNCTIONS = SCRIPT[:SCRIPT.rindex('\ncase "${1:-}" in')]


class SyncConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / "config.toml"
        env = {"HOME": str(self.home), "PATH": os.environ["PATH"],
               "CHIMERA_SYNC_CONFIG": str(self.config), "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
               "GIT_OPTIONAL_LOCKS": "0"}
        self.env_patch = patch.dict(os.environ, env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def shell(self, command, standalone=False):
        # Execute only definitions and the requested function, never sync dispatch.
        script = self.home / "setup_git_server.sh"
        script.write_text(FUNCTIONS + "\n" + command + "\n")
        if not standalone:
            (self.home / "sync_config.py").write_text((ROOT / "sync_config.py").read_text())
        return subprocess.run(["bash", str(script)], capture_output=True, text=True)

    def test_defaults_and_xdg_config(self):
        del os.environ["CHIMERA_SYNC_CONFIG"]
        os.environ["XDG_CONFIG_HOME"] = str(self.home / "user config")
        result = sync_config.load_config()
        self.assertEqual(result["file"], self.home / "user config/chimera-deploy/config.toml")
        self.assertEqual(result["workspace"], self.home / "ros2_ws")
        self.assertEqual(result["repos"]["px4_msgs"], self.home / "ros2_ws/src/px4_msgs")
        self.assertEqual(sync_config.stack_alignment(result), "")

    def test_default_host_build_cache_is_preserved(self):
        workspace = self.home / "ros2_ws"
        (workspace / "src/cdcl_umd_msgs/.git").mkdir(parents=True)
        install = workspace / "install/cdcl_umd_msgs/share/cdcl_umd_msgs"
        install.mkdir(parents=True)
        (install / "package.xml").touch()
        stamp = self.home / ".px4sim-sync-host-msgs"
        stamp.write_text("cdcl_umd_msgs=commit123 \n")
        stubs = self.home / "bin"
        stubs.mkdir()
        git = stubs / "git"
        git.write_text('#!/bin/bash\nprintf "commit123\\n"\n')
        git.chmod(0o755)
        os.environ["PATH"] = str(stubs) + ":" + os.environ["PATH"]
        result = self.shell('refresh_local_host_messages')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("current", result.stdout)
        self.assertEqual(stamp.read_text(), "cdcl_umd_msgs=commit123 \n")

    def test_overrides_environment_precedence_and_shell_quoting(self):
        self.config.write_text('[ground]\nros_workspace="~/flight ws"\npx4_msgs_repo="~/other ws/src/px4_msgs"\n')
        os.environ["CHIMERA_REPO_PX4_MSGS"] = str(self.home / "special ' $(false) repo")
        result = sync_config.load_config()
        self.assertEqual(result["repos"]["5g_drone"], self.home / "flight ws/src/5g_drone")
        self.assertEqual(result["repos"]["px4_msgs"], self.home / "special ' $(false) repo")
        output = self.shell('local_source_for px4_msgs; printf "%s\\n" "$GROUND_WS"; printf "%s\\n" "${REPOS[0]}"')
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(output.stdout.splitlines()[:2], [str(result["repos"]["px4_msgs"]), str(result["workspace"])])
        self.assertIn(str(self.home / "ros2_ws/src/cdcl_umd_msgs"), output.stdout.splitlines()[2])
        os.environ["CHIMERA_ROS_WORKSPACE"] = str(self.home / "environment ws")
        self.assertEqual(sync_config.load_config()["workspace"], self.home / "environment ws")

    def test_stack_alignment_and_individual_repo_override(self):
        stack = self.home / "px4-sim-stack"
        stack.mkdir()
        self.config.write_text('[ground]\nros_workspace="~/flight ws"\n')
        (stack / ".env").write_text('ROS2_WS_DIR="../flight ws" # machine path\n')
        config = sync_config.load_config()
        self.assertEqual(sync_config.stack_alignment(config), "")
        (stack / ".env").write_text('ROS2_WS_DIR=../wrong\n')
        self.assertIn("but sync workspace", sync_config.stack_alignment(config))
        os.environ["ROS2_WS_DIR"] = "../flight ws"
        self.assertEqual(sync_config.stack_alignment(config), "")
        config["repos"]["5g_drone"] = self.home / "another checkout"
        self.assertIn("PX4Sim expects 5g_drone", sync_config.stack_alignment(config))

    def test_invalid_config_fails_before_shell_command(self):
        for contents in ('[ground]\nros_workspace="relative"\n', '[repos]\ntypo="~/repo"\n',
                         '[ground]\nros_workspce="~/ws"\n', '[ground]\nros_workspace=42\n', 'broken=['):
            with self.subTest(contents=contents):
                self.config.write_text(contents)
                result = self.shell('echo SHOULD_NOT_RUN')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("SHOULD_NOT_RUN", result.stdout)
                self.assertIn("sync configuration:", result.stderr)

    def test_ui_read_only_status_uses_overrides(self):
        self.config.write_text('[ground]\nros_workspace="~/flight ws"\npx4_msgs_repo="~/other ws/px4_msgs"\n')
        result = subprocess.run(["python3", "-B", str(ROOT / "sync_ui.py"), "sync", "--status"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.home / "flight ws/src/5g_drone"), result.stdout)
        self.assertIn(str(self.home / "other ws/px4_msgs"), result.stdout)

    def test_host_build_receives_workspace_and_repository_override(self):
        workspace = self.home / "flight ws"
        (workspace / "src").mkdir(parents=True)
        repo = self.home / "messages elsewhere"
        (repo / ".git").mkdir(parents=True)
        self.config.write_text('[ground]\nros_workspace="~/flight ws"\n[repos]\ncdcl_umd_msgs="~/messages elsewhere"\n')
        # Exercise argument passing and generated script, with build tools stubbed.
        stubs = self.home / "bin"
        stubs.mkdir()
        for name, body in {"git": 'printf "commit123\\n"', "colcon": 'printf "%s\\n" "$PWD" "$@" > "$HOME/build-args"'}.items():
            target = stubs / name
            target.write_text("#!/bin/bash\n" + body + "\n")
            target.chmod(0o755)
        os.environ["PATH"] = str(stubs) + ":" + os.environ["PATH"]
        # Avoid requiring a ROS installation in this test environment.
        script = self.home / "setup_git_server.sh"
        script.write_text(FUNCTIONS.replace('. /opt/ros/humble/setup.bash', ':') + '\nrefresh_local_host_messages\n')
        (self.home / "sync_config.py").write_text((ROOT / "sync_config.py").read_text())
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.home / "build-args").read_text().splitlines()
        self.assertEqual(args[0], str(workspace))
        self.assertEqual(args[args.index("--base-paths") + 1], str(repo))
        self.assertTrue((self.home / ".px4sim-sync-host-msgs").is_file())

    def test_standalone_remote_retains_default_checkout_paths(self):
        for name in (*sync_config.ROS_REPOS, "chimera-deploy", "px4-sim-stack"):
            parent = self.home if name in ("chimera-deploy", "px4-sim-stack") else self.home / "ros2_ws/src"
            (parent / name / ".git").mkdir(parents=True)
        stubs = self.home / "bin"
        stubs.mkdir()
        git = stubs / "git"
        git.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$HOME/git-calls"\n')
        git.chmod(0o755)
        os.environ["PATH"] = str(stubs) + ":" + os.environ["PATH"]
        result = self.shell('cmd_remote --restore', standalone=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.home / "git-calls").read_text()
        self.assertIn(str(self.home / "chimera-deploy"), calls)
        self.assertIn(str(self.home / "ros2_ws/src/5g_drone"), calls)


if __name__ == "__main__":
    unittest.main()
