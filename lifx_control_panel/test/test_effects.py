"""Effect selection and in-flight worker cancellation regressions."""

import logging
import gc
import threading
import tkinter
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tkinter import ttk

from lifx_control_panel.frames import LightFrame
from lifx_control_panel.ui.theme import apply_theme, THEME_PALETTES
from lifx_control_panel.utilities.color_thread import ColorThreadRunner


class EffectSelectionTests(unittest.TestCase):
    def test_each_button_replaces_the_previous_effect(self):
        root = tkinter.Tk()
        root.withdraw()
        self.addCleanup(gc.collect)
        self.addCleanup(root.destroy)
        self.addCleanup(root.update_idletasks)
        root.audio_interface = SimpleNamespace(
            initialized=True, get_music_color=lambda **kwargs: None
        )
        frame = LightFrame.__new__(LightFrame)
        ttk.Labelframe.__init__(frame, root)
        frame.target = Mock()
        frame.threads = {}
        frame.special_functions_lf = ttk.LabelFrame(frame)
        with patch(
            "lifx_control_panel.frames.color_thread.ColorThreadRunner",
            side_effect=lambda *args, **kwargs: Mock(),
        ):
            # Give every effect its own runner, as in the actual panel.
            frame._setup_special_functions()
        buttons = {
            "action": frame.action_sync_btn,
            "cycle": frame.color_cycle_btn,
            "screen": frame.avg_screen_btn,
            "dominant": frame.dominant_screen_btn,
            "audio": frame.music_button,
        }
        for mode in ("dark", "light"):
            apply_theme(root, mode)
            # Exercise every ordered pair, including selecting the same effect twice.
            for previous in buttons.values():
                for name, button in buttons.items():
                    previous.invoke()
                    for runner in frame.threads.values():
                        runner.reset_mock()
                    button.invoke()
                    for key, runner in frame.threads.items():
                        runner.stop.assert_called_once_with()
                        self.assertEqual(runner.start.call_count, int(key == name))
                    for key, other in buttons.items():
                        self.assertEqual(
                            other.cget("background"),
                            (
                                THEME_PALETTES[mode]["selection"]
                                if key == name
                                else THEME_PALETTES[mode]["button"]
                            ),
                        )
            frame.stop_threads()
            self.assertTrue(
                all(
                    button.cget("background") == THEME_PALETTES[mode]["button"]
                    for button in buttons.values()
                )
            )


class EffectWorkerTests(unittest.TestCase):
    def make_runner(self, bulb, function):
        parent = SimpleNamespace(
            logger=logging.getLogger("effect-test"),
            get_color_values_hsbk=lambda: [0, 0, 30000, 3500],
        )
        runner = ColorThreadRunner(bulb, function, parent, continuous=False)
        runner.get_duration = lambda: 0.07
        runner.get_brightness_offset = lambda: 0
        self.addCleanup(runner.stop)
        return runner

    def test_stopped_capture_cannot_overwrite_replacement(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def old_capture(**kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Capture was not released")
            return [100, 200, 300, 3500]

        bulb = Mock()
        old = self.make_runner(bulb, old_capture)
        new = self.make_runner(bulb, lambda **kw: [400, 500, 600, 3500])
        old.start()
        self.assertTrue(entered.wait(3))
        old.stop()
        new.start()
        new.thread.join(3)
        release.set()
        old.thread.join(3)
        self.assertFalse(old.thread.is_alive())
        self.assertFalse(new.thread.is_alive())
        bulb.set_color.assert_called_once_with(
            [400, 500, 600, 3500], duration=70.0, rapid=False
        )

    def test_restart_while_old_capture_is_pending(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def capture(**kwargs):
            if not entered.is_set():
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("Capture was not released")
                return [100, 200, 300, 3500]
            return [400, 500, 600, 3500]

        bulb = Mock()
        runner = self.make_runner(bulb, capture)
        runner.start()
        self.assertTrue(entered.wait(3))
        old_worker = runner.thread
        runner.stop()
        runner.start()
        runner.thread.join(3)
        release.set()
        old_worker.join(3)
        self.assertFalse(old_worker.is_alive())
        self.assertFalse(runner.thread.is_alive())
        self.assertEqual(bulb.set_color.call_count, 1)
        self.assertEqual(bulb.set_color.call_args.args[0], [400, 500, 600, 3500])


if __name__ == "__main__":
    unittest.main()
