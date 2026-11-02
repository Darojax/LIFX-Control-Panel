"""Regressions for the selectively adapted upstream discovery and screen fixes."""

from dataclasses import replace
import logging
import socket
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import lifxlan
from PIL import Image

from lifx_control_panel.frames import LightFrame
from lifx_control_panel.ui.settings import config
from lifx_control_panel.ui import settings
from lifx_control_panel.utilities import color_thread as effects
from lifx_control_panel.utilities.async_bulb_interface import AsyncBulbInterface
from lifx_control_panel.utilities.discovery import (
    prefetch_device,
    group_state,
    receive_with_resets,
    prefetch_devices,
    SCAN_WORKERS,
)
from lifx_control_panel.test.dummy_devices import DummyBulb
from lifx_control_panel.test.test_maintenance import TkFixture, app_class


class SliderAndPanelTests(TkFixture):
    def test_screen_settings_save_percentages_and_reject_invalid_cutoff(self):
        import tkinter

        saved = {section: dict(config[section]) for section in config.sections()}

        def restore():
            config.clear()
            config.read_dict(saved)

        self.addCleanup(restore)
        dialog = settings.SettingsDisplay.__new__(settings.SettingsDisplay)
        tkinter.Toplevel.__init__(dialog, self.master)
        dialog.withdraw()
        dialog.body(tkinter.Frame(dialog))
        dialog.max_brightness.set(50)
        dialog.min_brightness_cutoff.set(10)
        dialog.near_black_threshold.set(4)
        with patch.object(settings, "save_config") as save:
            self.assertEqual(dialog.validate(), 1)
            save.assert_called_once()
        self.assertEqual(config.getint("AverageColor", "maxbrightness"), 32768)
        self.assertEqual(config.getint("AverageColor", "minbrightnesscutoff"), 6554)
        self.assertEqual(config.getint("AverageColor", "nearblackthreshold"), 4)
        before = dict(config["AverageColor"])
        dialog.min_brightness_cutoff.set(60)
        with patch.object(settings, "save_config") as save, patch.object(
            settings.messagebox, "showerror"
        ) as error:
            self.assertEqual(dialog.validate(), 0)
            save.assert_not_called()
            error.assert_called_once()
        self.assertEqual(dict(config["AverageColor"]), before)

    def test_rapid_updates_send_only_latest_value_each_tick(self):
        frame = self.make_frame("Desk", 100)
        with patch.object(
            frame, "after", return_value="queued"
        ) as schedule, patch.object(frame, "after_cancel"):
            for hue in range(100):
                frame.set_color([hue, 200, 300, 3500], rapid=True)
            schedule.assert_called_once()
            frame.target.set_color.assert_not_called()
            frame._flush_color()
            frame.target.set_color.assert_called_once_with(
                (99, 200, 300, 3500), duration=0, rapid=True
            )

    def test_new_control_actions_cancel_pending_slider_colour(self):
        for action in ("preset", "power", "effect", "stop"):
            with self.subTest(action=action):
                frame = self.make_frame("Desk", 100)
                with patch.object(frame, "after", return_value="queued"), patch.object(
                    frame, "after_cancel"
                ) as cancel:
                    frame.set_color([100, 200, 300, 3500], rapid=True)
                    if action == "preset":
                        frame.set_color([400, 500, 600, 3500])
                    elif action == "power":
                        frame.update_power()
                    elif action == "effect":
                        with patch.object(frame.threads["cycle"], "start"):
                            frame._start_effect("cycle", frame.color_cycle_btn)
                    else:
                        frame.stop_threads()
                    cancel.assert_called_once_with("queued")
                    sent = frame.target.set_color.call_count
                    frame._flush_color()
                    self.assertEqual(frame.target.set_color.call_count, sent)

    def test_group_action_cancels_member_pending_update(self):
        member = self.make_frame("Desk", 100)
        group = SimpleNamespace(
            target=lifxlan.Group([member.target]),
            master=self.master,
            stop_threads=Mock(),
        )
        self.master.frame_map["Room"] = group
        with patch.object(member, "after", return_value="queued"), patch.object(
            member, "after_cancel"
        ) as cancel:
            member.set_color([100, 200, 300, 3500], rapid=True)
            LightFrame._stop_conflicting_effects(group)
            cancel.assert_called_once_with("queued")
            member._flush_color()
            member.target.set_color.assert_not_called()

    def test_prefetched_panel_build_does_not_refetch_state(self):
        bulb = DummyBulb(label="Desk")
        state = prefetch_device(bulb)
        with patch.object(
            bulb, "get_color", side_effect=AssertionError("Repeated colour read")
        ), patch.object(
            bulb, "get_power", side_effect=AssertionError("Repeated power read")
        ), patch.object(
            bulb, "get_label", side_effect=AssertionError("Repeated label read")
        ):
            frame = LightFrame(self.master, bulb, initial_state=state)
            self.assertEqual(frame.label, "Desk")

    def test_bad_device_does_not_leave_an_icon_or_close_the_app(self):
        app = app_class()
        bad, good = DummyBulb(label="Offline"), DummyBulb(label="Desk")
        bad.get_color = Mock(side_effect=lifxlan.WorkflowException("No reply"))
        network = SimpleNamespace(get_devices=lambda: [bad, good])
        parent = app.__new__(app)
        # Use a real widget parent so the actual panel construction is exercised.
        from tkinter import ttk

        ttk.Frame.__init__(parent, self.root)
        parent.frame_map, parent.device_map = {}, {}
        parent.logger = logging.getLogger("discovery-test")
        parent.lifx = network
        parent.bulb_interface = AsyncBulbInterface(threading.Event(), 3000)
        parent.audio_interface = self.master.audio_interface
        from lifx_control_panel.ui.icon_list import BulbIconList
        import tkinter

        parent.bulb_icons = BulbIconList(parent)
        parent.group_icons = BulbIconList(parent, is_group=True)
        parent.tk_light_name = tkinter.StringVar(parent)
        parent._unmap_bind_id = None
        parent._closing = False
        try:
            with self.assertLogs(parent.logger, "WARNING"):
                parent.scan_for_lights()
            self.assertIn("Desk", parent.frame_map)
            self.assertNotIn("Offline", parent.frame_map)
            self.assertNotIn("Offline", parent.bulb_icons.bulb_dict)
            self.assertEqual(bad.get_color.call_count, 3)
            self.assertFalse(parent._closing)
        finally:
            parent.bulb_interface.stopped.set()
            parent.bulb_interface.join(3)


class DiscoveryTests(unittest.TestCase):
    def test_prefetch_is_parallel_and_bounded(self):
        lock, release = threading.Lock(), threading.Event()
        active = peak = entered = 0
        devices = [object() for _ in range(20)]

        def read(device, logger=None):
            nonlocal active, peak, entered
            with lock:
                active += 1
                entered += 1
                peak = max(peak, active)
                if entered == SCAN_WORKERS:
                    release.set()
            if not release.wait(3):
                raise TimeoutError("Prefetch did not overlap device reads")
            with lock:
                active -= 1
            return device

        with patch(
            "lifx_control_panel.utilities.discovery.prefetch_device", side_effect=read
        ):
            self.assertEqual(prefetch_devices(devices), devices)
        self.assertEqual(peak, SCAN_WORKERS)

    def test_failed_discovery_preserves_working_interface(self):
        interface = AsyncBulbInterface(threading.Event(), 3000)
        parent = SimpleNamespace(
            lifx=SimpleNamespace(get_devices=Mock(side_effect=OSError("No network"))),
            bulb_interface=interface,
            logger=logging.getLogger("scan-test"),
        )
        with self.assertLogs(parent.logger, "WARNING"):
            app_class().scan_for_lights(parent)
        self.assertIs(parent.bulb_interface, interface)
        self.assertFalse(interface.stopped.is_set())
        self.assertEqual(parent.lifx.get_devices.call_count, 3)

    def test_transient_state_read_retries_then_succeeds(self):
        bulb = DummyBulb(label="Desk")
        color = bulb.color
        bulb.get_color = Mock(
            side_effect=[lifxlan.WorkflowException("No reply"), color]
        )
        with self.assertLogs(level="WARNING"):
            state = prefetch_device(bulb)
        self.assertEqual(state.color, tuple(color))
        self.assertEqual(bulb.get_color.call_count, 2)

    def test_off_state_is_cached_without_a_power_query(self):
        bulb = DummyBulb(label="Desk")
        bulb.power_level = 0
        bulb.get_power = Mock(
            side_effect=AssertionError("Zero is a valid cached power")
        )
        state = prefetch_device(bulb)
        interface = AsyncBulbInterface(threading.Event(), 3000)
        interface.set_device_list([bulb], states=[state])
        self.assertEqual(interface.power_cache["Desk"], 0)

    def test_groups_use_prefetched_members(self):
        first = prefetch_device(DummyBulb(label="Desk"))
        second = replace(
            prefetch_device(DummyBulb(label="Wall")),
            features={"min_kelvin": 2000, "max_kelvin": 7000},
        )
        state = group_state("Room", [first, second])
        self.assertEqual(state.device.get_device_list(), [first.device, second.device])
        self.assertEqual(state.features, {"min_kelvin": 1500, "max_kelvin": 9000})

    def test_misclassified_multizone_light_is_rebuilt(self):
        bulb = lifxlan.Light("00:16:3e:00:00:01", "127.0.0.1")
        bulb.supports_multizone = lambda: True
        strip = DummyBulb(label="Strip")
        strip.get_color_zones = lambda: [strip.color]

        class Strip(lifxlan.MultiZoneLight):
            def __init__(self, *args):
                self.__dict__.update(strip.__dict__)
                self.power_level = strip.power

            def get_color_zones(self):
                return [self.color]

            def get_group_label(self):
                return "Room"

        with patch(
            "lifx_control_panel.utilities.discovery.lifxlan.MultiZoneLight", Strip
        ):
            state = prefetch_device(bulb)
        self.assertIsInstance(state.device, Strip)

    def test_connection_resets_do_not_extend_receive_timeout(self):
        sock = Mock()
        sock.gettimeout.return_value = 1.0
        receive = Mock(
            side_effect=[ConnectionResetError(), (b"reply", ("127.0.0.1", 56700))]
        )
        with patch(
            "lifx_control_panel.utilities.discovery.time.monotonic",
            side_effect=[10.0, 10.4],
        ):
            self.assertEqual(
                receive_with_resets(sock, receive), (b"reply", ("127.0.0.1", 56700))
            )
        self.assertAlmostEqual(sock.settimeout.call_args_list[0].args[0], 0.6)
        sock.settimeout.assert_called_with(1.0)

    def test_endless_connection_resets_are_bounded(self):
        sock = Mock()
        sock.gettimeout.return_value = None
        receive = Mock(side_effect=ConnectionResetError())
        with self.assertRaises(socket.timeout):
            receive_with_resets(sock, receive)
        self.assertEqual(receive.call_count, 8)


class ScreenControlsTests(unittest.TestCase):
    def setUp(self):
        saved = dict(config["AverageColor"])
        self.addCleanup(
            lambda: (
                config["AverageColor"].clear(),
                config["AverageColor"].update(saved),
            )
        )

    def test_near_black_filter_can_be_disabled(self):
        config["AverageColor"]["nearblackthreshold"] = "10"
        self.assertEqual(effects.screen_rgb_to_hsbk((1, 0, 1), 3500)[1], 0)
        self.assertEqual(effects.screen_rgb_to_hsbk((255, 0, 0), 3500)[1], 65535)
        config["AverageColor"]["nearblackthreshold"] = "0"
        self.assertEqual(effects.screen_rgb_to_hsbk((1, 0, 1), 3500)[1], 65535)

    def test_brightness_limits_and_boundaries(self):
        config["AverageColor"].update(
            maxbrightness="30000", minbrightnesscutoff="10000"
        )
        for value, expected in [(-1, 0), (9999, 0), (10000, 10000), (50000, 30000)]:
            self.assertEqual(effects.limit_screen_brightness(value), expected)
        config["AverageColor"].update(maxbrightness="65535", minbrightnesscutoff="0")
        self.assertEqual(effects.limit_screen_brightness(12345), 12345)

    def test_both_screen_modes_use_near_black_filter(self):
        config["AverageColor"]["nearblackthreshold"] = "10"
        with patch.object(
            effects,
            "get_rect_as_image",
            return_value=Image.new("RGB", (4, 4), (1, 0, 1)),
        ):
            for function in (effects.avg_screen_color, effects.dominant_screen_color):
                self.assertEqual(function([0, 0, 0, 3500], lambda: "[0,0,4,4]")[1], 0)

    def test_screen_cap_does_not_change_other_effects(self):
        config["AverageColor"].update(
            maxbrightness="30000", minbrightnesscutoff="0", brightnessoffset="0"
        )
        parent = SimpleNamespace(
            logger=logging.getLogger("screen-limit-test"),
            get_color_values_hsbk=lambda: [0, 65535, 40000, 3500],
        )
        for function, expected, kwargs in (
            (effects.avg_screen_color, 30000, {"func_bounds": lambda: "[0,0,4,4]"}),
            (lambda initial_color: initial_color, 40000, {}),
        ):
            bulb = Mock()
            runner = effects.ColorThreadRunner(
                bulb, function, parent, continuous=False, **kwargs
            )
            with patch.object(
                effects,
                "get_rect_as_image",
                return_value=Image.new("RGB", (4, 4), "white"),
            ), patch.object(effects.mss, "mss"):
                runner.start()
                runner.thread.join(3)
            self.assertFalse(runner.thread.is_alive())
            self.assertEqual(bulb.set_color.call_args.args[0][2], expected)


if __name__ == "__main__":
    unittest.main()
