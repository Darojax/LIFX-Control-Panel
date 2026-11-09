"""Offline regressions for device polling, UI state and app lifecycle."""

import concurrent.futures
import configparser
import gc
import logging
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import lifxlan
from PIL import Image

from lifx_control_panel.frames import LightFrame
from lifx_control_panel.ui import settings
from lifx_control_panel.utilities import color_thread as effects
from lifx_control_panel.utilities.async_bulb_interface import AsyncBulbInterface
from lifx_control_panel.utilities.audio import AudioInterface
from lifx_control_panel.utilities.keypress import KeybindManager
from lifx_control_panel.test.dummy_devices import DummyBulb, LifxLANDummy


def app_class():
    from lifx_control_panel.__main__ import LifxFrame

    return LifxFrame


class TkFixture(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.master = ttk.Frame(self.root)
        self.master.logger = logging.getLogger("ui-test")
        self.master.audio_interface = SimpleNamespace(
            initialized=False,
            get_music_color=lambda **kwargs: None,
            get_device_names=lambda: {},
        )
        self.master.bulb_interface = SimpleNamespace(power_queue={}, color_queue={})
        self.master.frame_map = {}
        self.master.device_map = {}

    def tearDown(self):
        self.root.update_idletasks()
        self.root.destroy()
        del self.master
        del self.root
        gc.collect()

    def make_frame(self, label, hue):
        bulb = Mock(spec=lifxlan.Light)
        bulb.get_label.return_value = label
        bulb.mac_addr = label
        bulb.get_power.return_value = 65535
        bulb.get_color.return_value = [hue, 30000, 30000, 3500]
        bulb.supports_multizone.return_value = False
        bulb.product_features = {}
        frame = LightFrame(self.master, bulb)
        self.master.frame_map[label] = frame
        return frame


class TkStateTests(TkFixture):
    def test_panels_have_independent_sliders_and_one_polling_timer(self):
        first = self.make_frame("First", 100)
        second = self.make_frame("Second", 200)
        first.hsbk[0].set(1000)
        self.assertEqual(second.hsbk[0].get(), 200)
        timers = self.root.tk.call("after", "info")
        for _ in range(10):
            first.restart()
        self.assertEqual(self.root.tk.call("after", "info"), timers)

    def test_group_stops_member_effects_but_keeps_unrelated_lights(self):
        first = self.make_frame("First", 100)
        second = self.make_frame("Second", 200)
        group = SimpleNamespace(
            target=lifxlan.Group([first.target]), stop_threads=Mock()
        )
        self.master.frame_map["Group"] = group
        first.stop_threads = Mock()
        second.stop_threads = Mock()
        first._stop_conflicting_effects()
        first.stop_threads.assert_called_once()
        group.stop_threads.assert_called_once()
        second.stop_threads.assert_not_called()

    def test_polling_drains_stale_states(self):
        frame = self.make_frame("First", 100)
        colors = queue.Queue()
        for hue in (200, 300, 400):
            colors.put([hue, 30000, 30000, 3500])
        self.master.bulb_interface.color_queue["First"] = colors
        frame.update_status_from_bulb(run_once=True)
        self.assertEqual(frame.hsbk[0].get(), 400)
        self.assertTrue(colors.empty())

    def test_white_preset_keeps_readable_text_in_dark_mode(self):
        frame = self.make_frame("First", 100)
        from lifx_control_panel.ui.theme import THEME_PALETTES, apply_theme

        apply_theme(self.root, "dark")
        frame.color_var.set("WHITE")
        dropdown = frame.preset_dropdown
        self.assertEqual(dropdown.get(), "White")
        self.assertEqual(
            ttk.Style(self.root).lookup(
                dropdown.cget("style"), "foreground", ["readonly"]
            ),
            THEME_PALETTES["dark"]["foreground"],
        )

    def test_eyedropper_can_be_cancelled_without_a_worker(self):
        frame = self.make_frame("First", 100)
        frame.eyedropper()
        self.assertIsNotNone(frame._eyedropper_after_id)
        frame.after_cancel(frame._eyedropper_after_id)
        with patch(
            "lifx_control_panel.frames.win32api.GetAsyncKeyState", return_value=0x8000
        ):
            frame._poll_eyedropper()
        self.assertIsNone(frame._eyedropper_after_id)
        self.assertIsNone(frame._eyedropper_root)

    def test_settings_body_opens_with_no_lights(self):
        dialog = settings.SettingsDisplay.__new__(settings.SettingsDisplay)
        tk.Toplevel.__init__(dialog, self.master)
        dialog.withdraw()
        body = tk.Frame(dialog)
        dialog.body(body)
        self.assertEqual(dialog.keybind_add_button.cget("state"), "disabled")

    def test_full_app_rescan_and_shutdown_with_simulated_devices(self):
        app_type = app_class()
        module = __import__(app_type.__module__, fromlist=["audio"])
        network = LifxLANDummy()
        for label in ("Desk", "Wall"):
            network.add_dummy_light(DummyBulb(label=label))
        with patch.object(
            module.audio, "AudioInterface"
        ) as audio_factory, patch.object(module, "KeybindManager"), patch.object(
            module.pystray, "Icon"
        ):
            audio_factory.return_value.initialized = False
            audio_factory.return_value.get_music_color = lambda **kwargs: None
            app = app_type(
                self.root, network, AsyncBulbInterface(threading.Event(), 3000)
            )
            self.assertEqual(app.current_lightframe.label, "Desk")
            self.assertEqual(len(app.frame_map), 3)  # two lights plus their group
            old_interface = app.bulb_interface
            app.scan_for_lights()
            self.assertTrue(old_interface.stopped.is_set())
            self.assertIsNot(old_interface.stopped, app.bulb_interface.stopped)
            with patch.object(self.root, "destroy"):
                app.on_closing()
            self.assertTrue(app.bulb_interface.stopped.is_set())
            app.audio_interface.close.assert_called_once()
            app.key_listener.shutdown.assert_called_once()


class CaptureAndWorkerTests(unittest.TestCase):
    def setUp(self):
        gc.collect()

    def test_region_edits_are_not_cached_and_invalid_sizes_are_rejected(self):
        bounds = ["[0, 0, 100, 100]"]
        callback = lambda: bounds[0]
        self.assertEqual(effects.get_monitor_bounds(callback), (0, 0, 100, 100))
        bounds[0] = "[-100, 0, 20, 30]"
        self.assertEqual(effects.get_monitor_bounds(callback), (-100, 0, 20, 30))
        for value in ("[0,0,0,10]", "[0,0,-1,10]", "[a,0,10,10]", "[full,0,1,1]"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                effects.validate_monitor_bounds(value)

    def test_dominant_colour_handles_single_pixel_and_correct_rgb_order(self):
        with patch.object(
            effects,
            "get_rect_as_image",
            return_value=Image.new("RGB", (1, 1), (255, 255, 255)),
        ):
            result = effects.dominant_screen_color([0, 0, 0, 3500], lambda: "[0,0,1,1]")
        self.assertEqual(
            result, list(lifxlan.utils.RGBtoHSBK((255, 255, 255), temperature=3500))
        )

    def test_worker_reads_tk_inputs_only_on_start_and_limits_command_rate(self):
        gui_thread = threading.get_ident()
        calls = []
        enough = threading.Event()

        def read_color():
            self.assertEqual(threading.get_ident(), gui_thread)
            return [100, 200, 300, 3500]

        def send(*args, **kwargs):
            calls.append(time.monotonic())
            if len(calls) >= 3:
                enough.set()

        bulb = Mock()
        bulb.set_color.side_effect = send
        parent = SimpleNamespace(
            logger=logging.getLogger("worker-test"), get_color_values_hsbk=read_color
        )
        runner = effects.ColorThreadRunner(
            bulb, lambda initial_color: initial_color, parent
        )
        runner.start()
        try:
            self.assertTrue(enough.wait(3))
        finally:
            runner.stop()
            runner.thread.join(3)
        self.assertTrue(all(b - a >= 0.04 for a, b in zip(calls, calls[1:])))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        gc.collect()

    def test_hotkeys_keep_original_callbacks_across_settings_and_deletion(self):
        with patch("lifx_control_panel.utilities.keypress.keyboard") as keyboard:
            keyboard.add_hotkey.side_effect = lambda key, callback: Mock()
            manager = KeybindManager(
                SimpleNamespace(logger=logging.getLogger("keys-test"))
            )
            callback = Mock(__name__="colour")
            manager.register_function("ctrl+a", callback)
            manager.shutdown()
            manager.restart()
            self.assertIs(keyboard.add_hotkey.call_args.args[1], callback)
            manager.unregister_function("ctrl+a")
            keyboard.add_hotkey.reset_mock()
            manager.restart()
            keyboard.add_hotkey.assert_not_called()
            keyboard.unhook_all.assert_not_called()
            manager.shutdown()

    def test_audio_switch_closes_old_stream_and_supports_mono_inputs(self):
        with patch("lifx_control_panel.utilities.audio.pyaudio") as pyaudio:
            interface = pyaudio.PyAudio.return_value
            interface.get_device_count.return_value = 2
            interface.get_device_info_by_index.side_effect = lambda index: {
                "name": "Microphone" if index else "Speakers",
                "maxInputChannels": int(index == 1),
            }
            interface.open.side_effect = [Mock(), Mock()]
            audio = AudioInterface()
            config = configparser.ConfigParser()
            config.read_dict({"Audio": {"InputIndex": "1"}})
            audio.init_audio(config)
            old_stream = audio.stream
            audio.init_audio(config)
            old_stream.close.assert_called_once()
            self.assertEqual(interface.open.call_args.kwargs["channels"], 1)
            self.assertEqual(audio.get_device_names(), {1: "Microphone"})
            audio.stream.get_read_available.return_value = 2048
            audio.stream.read.return_value = bytes(4096)
            audio.get_music_color([100, 200, 300, 3500])
            audio.stream.read.assert_called_once_with(2048, exception_on_overflow=False)
            audio.close()
            interface.terminate.assert_called_once()

    def test_slow_poll_does_not_queue_more_batches(self):
        entered, release = threading.Event(), threading.Event()
        original = concurrent.futures.ThreadPoolExecutor
        batches = []

        class Executor(original):
            def map(self, *args, **kwargs):
                batches.append(1)
                return super().map(*args, **kwargs)

        interface = AsyncBulbInterface(threading.Event(), 1)
        interface.device_list = [object()]

        def query(device):
            entered.set()
            release.wait(3)

        interface.query_device = query
        with patch(
            "lifx_control_panel.utilities.async_bulb_interface.concurrent.futures.ThreadPoolExecutor",
            Executor,
        ):
            interface.start()
            try:
                self.assertTrue(entered.wait(3))
                time.sleep(0.04)
                self.assertEqual(len(batches), 1)
            finally:
                interface.stopped.set()
                release.set()
                interface.join(3)
        self.assertFalse(interface.is_alive())

    def test_latest_state_queue_stays_bounded(self):
        values = queue.Queue(maxsize=1)
        for value in range(100):
            AsyncBulbInterface._publish_latest(values, value)
        self.assertEqual(values.qsize(), 1)
        self.assertEqual(values.get_nowait(), 99)

    def test_strip_poll_reads_representative_colour_without_fetching_palette(self):
        from lifx_control_panel.test.dummy_devices import MultiZoneDummy

        strip = MultiZoneDummy(label="Strip", num_zones=16)
        interface = AsyncBulbInterface(threading.Event(), 3000)
        interface.set_device_list([strip])
        colour = (1234, 45000, 28000, 3500)
        strip.set_zone_color(0, 0, colour)
        strip.get_color_zones = Mock(
            side_effect=AssertionError("Polling must not download every zone")
        )
        interface.query_device(strip)
        self.assertEqual(interface.color_queue["Strip"].get_nowait(), colour)
        strip.get_color_zones.assert_not_called()

    def test_shortcuts_use_ui_queue_and_frame_set_color(self):
        app = app_class()
        frame = Mock()
        parent = SimpleNamespace(
            frame_map={"Desk": frame},
            key_listener=Mock(),
            post_ui=Mock(),
            logger=Mock(),
        )
        color = [100, 200, 300, 3500]
        app.save_keybind(parent, "Desk", "ctrl+a", color)
        parent.key_listener.register_function.call_args.args[1]()
        frame.set_color.assert_not_called()
        parent.post_ui.call_args.args[0]()
        frame.set_color.assert_called_once_with(color)

    def test_portable_config_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "config.ini"
            with patch.object(settings, "CONFIG_PATH", destination):
                settings.save_config()
            result = configparser.ConfigParser(interpolation=None)
            result.read(destination)
            self.assertEqual(
                result["AppSettings"]["theme"], settings.config["AppSettings"]["theme"]
            )
            self.assertEqual(
                [path.name for path in Path(directory).iterdir()], ["config.ini"]
            )


if __name__ == "__main__":
    unittest.main()
