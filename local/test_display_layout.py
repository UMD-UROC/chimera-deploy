import importlib.machinery
import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader(
    "display_layout", str(pathlib.Path(__file__).with_name("display-layout"))
)
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


def monitor(name, sizes, primary=False):
    modes = [
        {
            "name": f"{w}x{h}",
            "width": w,
            "height": h,
            "rate": rate,
            "preferred": i == 0,
            "current": i == 0,
        }
        for i, (w, h, rate) in enumerate(sizes)
    ]
    return {"name": name, "primary": primary, "geometry": (*sizes[0][:2], 0, 0), "modes": modes}


class Tests(unittest.TestCase):
    def test_verification_detects_laptop_refresh_rate_changes(self):
        outputs = [monitor("eDP-9", [(3840, 2400, 120)])]
        query = """Screen 0: current 3840 x 2400
eDP-9 connected primary 3840x2400+0+0 (normal)
   3840x2400 120.00+ 60.00*
"""
        with (
            patch.object(app, "run", return_value=query),
            self.assertRaisesRegex(RuntimeError, "preferred refresh rate"),
        ):
            app.verify(outputs, "mirror")

    def test_install_is_idempotent_and_preserves_existing_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            target = root / ".local/bin/display-layout"
            target.parent.mkdir(parents=True)
            target.write_text("previous command")
            with (
                patch.object(app, "STATE", root),
                patch.object(app.pathlib.Path, "home", return_value=root),
                patch.dict(
                    os.environ,
                    {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data")},
                ),
                patch.object(app.Gio, "Settings") as settings,
                patch.object(app, "execute_change") as change,
            ):
                settings.new.return_value.get_strv.return_value = ["/existing/"]
                app.install()
                app.install()
                bindings = settings.new.return_value.set_strv.call_args.args[1]
                self.assertEqual(len(bindings), 3)
                self.assertIn("/existing/", bindings)
                self.assertEqual((root / "installed-script.backup").read_text(), "previous command")
                self.assertEqual(target.read_bytes(), pathlib.Path(app.__file__).read_bytes())
                self.assertIn(
                    " auto\n", (root / "config/autostart/display-mirror.desktop").read_text()
                )
                self.assertTrue(os.access(target, os.X_OK))
                change.assert_not_called()

    def test_watchdog_restores_once_after_deadline(self):
        with (
            patch.object(
                app.sys,
                "argv",
                ["display-layout", "--recover", "/checkpoint", "--cancel", "/missing-cancel-file"],
            ),
            patch.object(app.time, "monotonic", side_effect=[0, 16]),
            patch.object(app, "recover") as restore,
        ):
            app.main()
            restore.assert_called_once_with("/checkpoint")

    def test_successful_change_cancels_watchdog(self):
        with tempfile.TemporaryDirectory() as directory:
            cancel = pathlib.Path(directory) / "cancel"
            cancel.touch()
            with (
                patch.object(
                    app.sys,
                    "argv",
                    ["display-layout", "--recover", "/checkpoint", "--cancel", str(cancel)],
                ),
                patch.object(app, "recover") as restore,
            ):
                app.main()
                restore.assert_not_called()

    def test_parse_active_and_disabled_unknown_monitors(self):
        text = """Screen 0: minimum 8 x 8, current 3840 x 2400, maximum 32767 x 32767
eDP-9 connected primary 3840x2400+0+0 (normal)
   3840x2400 120.00*+ 60.00
VGA-8 connected (normal)
   1024x768 60.00+
DP-99 disconnected (normal)
"""
        outputs = app.parse_outputs(text)
        self.assertEqual([o["name"] for o in outputs], ["eDP-9", "VGA-8"])
        self.assertEqual(outputs[1]["geometry"], ())
        self.assertEqual(app.preferred_mode(outputs[0])["rate"], 120)

    def test_renamed_laptop_selected_even_if_external_primary(self):
        outputs = [
            monitor("HDMI-37", [(1920, 1080, 60)], True),
            monitor("eDP-9", [(3840, 2400, 120)]),
        ]
        with (
            patch.object(app, "run", return_value=""),
            patch.object(app, "parse_outputs", return_value=outputs),
        ):
            self.assertEqual(app.discover()[0]["name"], "eDP-9")

    def test_new_resolution_and_aspect_ratios(self):
        for target in [
            (1920, 1080),
            (2560, 1440),
            (3840, 2160),
            (1280, 1024),
            (3440, 1440),
            (1080, 1920),
            (7680, 4320),
        ]:
            with self.subTest(target=target):
                w, h, x, y = app.aspect_fit((3840, 2400), target)
                self.assertLessEqual(w + 2 * x, target[0])
                self.assertLessEqual(h + 2 * y, target[1])
                self.assertLess(abs(w / h - 1.6), 0.005)
                self.assertTrue(w == target[0] or h == target[1])
        self.assertEqual(app.aspect_fit((3840, 2400), (1920, 1080)), (1728, 1080, 96, 0))

    def test_multiple_outputs_and_join_positions(self):
        outputs = [
            monitor("eDP-9", [(3840, 2400, 120)]),
            monitor("HDMI-37", [(2560, 1440, 60)]),
            monitor("DP-27", [(1280, 1024, 60)]),
        ]
        cmd = app.nvidia_plan(outputs, "mirror")[-1]
        self.assertIn("ViewPortOut=3840x2400+0+0", cmd)
        self.assertEqual(cmd.count("ViewPortIn=3840x2400"), 3)
        join = app.nvidia_plan(outputs, "join")[-1]
        self.assertIn("HDMI-37: nvidia-auto-select +3840+0", join)
        self.assertIn("DP-27: nvidia-auto-select +6400+0", join)

    def test_generic_plan_resets_supported_borders_without_panning(self):
        outputs = [
            monitor("eDP-9", [(3840, 2400, 120)]),
            monitor("HDMI-37", [(1920, 1080, 60)]),
            monitor("DP-27", [(2560, 1440, 60)]),
        ]
        cmd = app.randr_plan(outputs, "mirror", {"HDMI-37": {"border": "96,0,96,0"}})
        self.assertIn("--nograb", cmd)
        self.assertEqual(cmd.count("--set"), 1)
        self.assertIn("0,0,0,0", cmd)
        self.assertNotIn("--panning", cmd)
        self.assertEqual(cmd.count("--scale-from"), 2)
        self.assertEqual(cmd[cmd.index("--fb") + 1], "3840x2400")
        join = app.randr_plan(outputs, "join", {})
        self.assertEqual(join[join.index("--fb") + 1], "8320x2400")
        self.assertIn("5760x0", join)

    def test_failure_restores_known_layout_without_resolution_search(self):
        outputs = [
            monitor("eDP-9", [(3840, 2400, 120)]),
            monitor("HDMI-37", [(3840, 2160, 60), (1920, 1080, 60)]),
        ]
        known = ["nvidia-settings", "--assign", "CurrentMetaMode=known-working"]
        for backend in ["nvidia", "xrandr"]:
            with (
                self.subTest(backend=backend),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = pathlib.Path(directory)
                preference = root / "preference"
                preference.write_text("join\n")
                with (
                    patch.object(app, "STATE", root),
                    patch.object(app, "PREFERENCE", preference),
                    patch.object(app, "discover", return_value=outputs),
                    patch.object(app, "nvidia_outputs", return_value={o["name"] for o in outputs}),
                    patch.object(app, "run", return_value=""),
                    patch.object(app, "checkpoint", return_value={"restore": known}),
                    patch.object(
                        app,
                        "execute_change",
                        side_effect=[RuntimeError("driver rejected layout"), None],
                    ) as writes,
                    patch.object(app.subprocess, "Popen") as watchdog,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "restored the previous working layout"
                    ):
                        app.apply("mirror", backend=backend)
                    self.assertEqual(writes.call_count, 2)
                    self.assertEqual(writes.call_args_list[1].args[0], known)
                    self.assertEqual(preference.read_text(), "join\n")
                    watchdog.assert_called_once()
                    watchdog.return_value.wait.assert_called_once()

    def test_success_verifies_twice_and_cancels_recovery(self):
        outputs = [
            monitor("eDP-9", [(3840, 2400, 120)]),
            monitor("HDMI-37", [(1920, 1080, 60)]),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with (
                patch.object(app, "STATE", root),
                patch.object(app, "PREFERENCE", root / "preference"),
                patch.object(app, "discover", return_value=outputs),
                patch.object(app, "nvidia_outputs", return_value=set()),
                patch.object(app, "run", return_value=""),
                patch.object(app, "checkpoint", return_value={"restore": ["restore-known"]}),
                patch.object(app, "execute_change") as writes,
                patch.object(app, "verify") as checks,
                patch.object(app.time, "sleep"),
                patch.object(app.subprocess, "Popen") as watchdog,
            ):
                app.apply("mirror")
                self.assertEqual(writes.call_count, 1)
                self.assertEqual(checks.call_count, 2)
                self.assertEqual((root / "preference").read_text(), "mirror\n")
                watchdog.return_value.wait.assert_called_once()
                self.assertEqual(list(root.glob("recovery-cancel-*")), [])


if __name__ == "__main__":
    unittest.main()
