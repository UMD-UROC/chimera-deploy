"""Test mirror retries and concurrency without network access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = (ROOT / "setup_git_server.sh").read_text()
FUNCTIONS = SCRIPT[SCRIPT.index("fetch_mirror() {"):SCRIPT.index("\nsync_local_worktrees() {")]

FAKE_GIT = r'''#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import sys
import time

repo = Path(sys.argv[2]).name
state_file = Path(os.environ["TEST_STATE"])
def change(start):
    with state_file.open("r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        state = json.load(stream)
        if start:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            state["attempts"][repo] = state["attempts"].get(repo, 0) + 1
        else:
            state["active"] -= 1
            state["finished"].append(repo)
        stream.seek(0)
        json.dump(state, stream)
        stream.truncate()
        return state["attempts"][repo]

attempt = change(True)
time.sleep(0.08)
change(False)
mode = os.environ.get("TEST_MODE", "success")
if mode == "permanent" and repo == "a.git":
    print("Permission denied (publickey).", file=sys.stderr)
    sys.exit(128)
if mode == "exhausted" or mode == "transient" and attempt < 3:
    print("kex_exchange_identification: read: Connection reset by peer", file=sys.stderr)
    sys.exit(128)
'''


class SyncMirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        git = self.bin / "git"
        git.write_text(FAKE_GIT)
        git.chmod(0o755)
        sleep = self.bin / "sleep"
        sleep.write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> "$TEST_DELAYS"\n')
        sleep.chmod(0o755)
        self.state = self.root / "state.json"
        self.state.write_text(json.dumps({"active": 0, "max_active": 0,
                                          "attempts": {}, "finished": []}))
        self.env = dict(os.environ, PATH=str(self.bin) + ":" + os.environ["PATH"],
                        TEST_STATE=str(self.state), TEST_DELAYS=str(self.root / "delays"),
                        TMPDIR=str(self.root))
        self.script = self.root / "run.sh"
        self.script.write_text('set -euo pipefail\nsay() { echo "$*"; }\n'
                               'warn() { echo "$*"; }\n' + FUNCTIONS + '\n"$@"\n')

    def run_fetch(self, mode):
        return subprocess.run(["bash", str(self.script), "fetch_mirror", "a.git"],
                              env=dict(self.env, TEST_MODE=mode), capture_output=True,
                              text=True, timeout=10)

    def test_transient_failure_recovers_with_backoff(self):
        result = self.run_fetch("transient")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.state.read_text())["attempts"], {"a.git": 3})
        self.assertEqual((self.root / "delays").read_text(), "1\n2\n")
        self.assertNotIn("Connection reset by peer", result.stdout)

    def test_retry_exhaustion_preserves_error_and_status(self):
        result = self.run_fetch("exhausted")
        self.assertEqual(result.returncode, 128)
        self.assertEqual(json.loads(self.state.read_text())["attempts"], {"a.git": 3})
        self.assertIn("Connection reset by peer", result.stdout)

    def test_permanent_failure_has_no_retry(self):
        result = self.run_fetch("permanent")
        self.assertEqual(result.returncode, 128)
        self.assertEqual(json.loads(self.state.read_text())["attempts"], {"a.git": 1})
        self.assertIn("Permission denied", result.stdout)
        self.assertFalse((self.root / "delays").exists())

    def test_pool_limits_jobs_waits_after_failure_and_cleans_logs(self):
        for mode, expected in (("success", 0), ("permanent", 128)):
            with self.subTest(mode=mode):
                self.state.write_text(json.dumps({"active": 0, "max_active": 0,
                                                  "attempts": {}, "finished": []}))
                mirrors = self.root / "mirrors"
                mirrors.mkdir(exist_ok=True)
                for name in "abcdefg":
                    (mirrors / f"{name}.git").mkdir(exist_ok=True)
                link = mirrors / "link.git"
                if not link.exists():
                    link.symlink_to(mirrors / "a.git")
                result = subprocess.run(["bash", str(self.script), "sync_mirrors_parallel"],
                                        env=dict(self.env, TEST_MODE=mode, SERVE_ROOT=str(mirrors)),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                state = json.loads(self.state.read_text())
                self.assertGreater(state["max_active"], 1)
                self.assertLessEqual(state["max_active"], 3)
                self.assertEqual(state["active"], 0)
                self.assertEqual(len(state["finished"]), 7)
                self.assertFalse(list(self.root.glob("chimera-sync-mirror-*")))
                self.assertEqual("all mirrors refreshed" in result.stdout, expected == 0)


if __name__ == "__main__":
    unittest.main()
