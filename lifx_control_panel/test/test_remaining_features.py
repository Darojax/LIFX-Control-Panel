"""Offline checks for saved states, ordered actions, zone packets and desktop UI."""

import json
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import lifxlan

from lifx_control_panel.frames import LightFrame, MultiZoneFrame, GroupFrame
from lifx_control_panel.test.test_maintenance import TkFixture, app_class
from lifx_control_panel.test.dummy_devices import DummyBulb, MultiZoneDummy
from lifx_control_panel.utilities.audio import pcm_rms
from lifx_control_panel.utilities.device_actions import (
    CommandGate,
    capture_state,
    decode_state,
    device_key,
    restore_device,
)
from lifx_control_panel.utilities.discovery import prefetch_device, group_state
from lifx_control_panel.utilities.multizone import (
    SetExtendedColorZones,
    set_zone_colors,
)
from lifx_control_panel.utilities import desktop
from lifx_control_panel.ui.settings import config

RED, BLUE = (0, 65535, 40000, 3500), (43690, 65535, 40000, 3500)


class CommandTests(unittest.TestCase):
    def test_new_action_invalidates_old_work_for_overlapping_group(self):
        first, second = DummyBulb(label="Desk"), DummyBulb(label="Wall")
        gate = CommandGate()
        group = lifxlan.Group([first, second])
        old = gate.ticket(group)
        gate.invalidate(first)
        sent = []
        gate.write(group, lambda device: sent.append(device), old)
        self.assertEqual(sent, [second])

    def test_inflight_write_finishes_before_newer_write(self):
        bulb, gate = DummyBulb(), CommandGate()
        entered, release = threading.Event(), threading.Event()
        sent = []
        ticket = gate.ticket(bulb)

        def old(device):
            entered.set()
            release.wait(3)
            sent.append("old")

        thread = threading.Thread(target=lambda: gate.write(bulb, old, ticket))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            gate.invalidate(bulb)
            release.set()
            gate.write(bulb, lambda device: sent.append("new"))
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(sent, ["old", "new"])


class StateAndAudioTests(unittest.TestCase):
    def test_saved_state_survives_light_renaming(self):
        original = DummyBulb(label="Old name")
        original.set_color(RED)
        original.set_power(65535)
        saved = {device_key(original): capture_state(original)}
        original.label = "New name"
        original.set_color(BLUE)
        original.set_power(0)
        restore_device(original, decode_state(saved[device_key(original)]))
        self.assertEqual(tuple(original.get_color()), RED)
        self.assertEqual(original.get_power(), 65535)

    def test_saved_multizone_state_restores_each_zone(self):
        strip = MultiZoneDummy(num_zones=4)
        strip.set_zone_colors([RED, RED, BLUE, BLUE])
        state = decode_state(capture_state(strip))
        strip.set_color((0, 0, 0, 3500))
        with patch("lifx_control_panel.utilities.multizone.time.sleep"):
            restore_device(strip, state)
        self.assertEqual(strip.get_color_zones(), [RED, RED, BLUE, BLUE])

    def test_invalid_saved_values_are_rejected(self):
        for value in (
            "[]",
            "null",
            "{}",
            json.dumps({"version": 1, "power": 65535, "color": [-1, 0, 0, 3500]}),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_state(value)

    def test_cancelled_restore_does_not_change_lights(self):
        bulb = Mock()
        restore_device(
            bulb, {"zones": None, "color": RED, "power": 65535}, cancelled=lambda: True
        )
        bulb.set_color.assert_not_called()
        bulb.set_power.assert_not_called()

    def test_pcm_rms_matches_known_sixteen_bit_samples(self):
        for samples, expected in (
            ([], 0),
            ([0, 0], 0),
            ([12000, -12000], 12000),
            ([-32768, 32767], 32767),
        ):
            self.assertEqual(
                pcm_rms(struct.pack("<" + "h" * len(samples), *samples)), expected
            )


class ZoneProtocolTests(unittest.TestCase):
    def test_extended_wire_payload_and_padding(self):
        packet = SetExtendedColorZones(
            "00:16:3e:00:00:01",
            123,
            1,
            {"duration": 25, "apply": 1, "zone_index": 82, "colors": [RED, BLUE]},
        )
        self.assertEqual(len(packet.payload), 664)
        self.assertEqual(struct.unpack_from("<IBHB", packet.payload), (25, 1, 82, 2))
        self.assertEqual(struct.unpack_from("<4H", packet.payload, 8), RED)
        self.assertEqual(struct.unpack_from("<4H", packet.payload, 16), BLUE)
        self.assertEqual(packet.payload[24:], bytes(640))
        self.assertEqual(packet.message_type, 510)

    def test_long_strip_uses_multiple_extended_packets(self):
        strip = SimpleNamespace(supports_extended_multizone=True, req_with_ack=Mock())
        set_zone_colors(strip, [RED] * 85)
        payloads = [call.args[1] for call in strip.req_with_ack.call_args_list]
        self.assertEqual(
            [(payload["zone_index"], len(payload["colors"])) for payload in payloads],
            [(0, 82), (82, 3)],
        )

    def test_successful_legacy_retry_is_not_reported_as_failure(self):
        strip = SimpleNamespace(
            supports_extended_multizone=False,
            set_zone_color=Mock(
                side_effect=[lifxlan.WorkflowException("Lost ACK"), None, None]
            ),
        )
        with patch("lifx_control_panel.utilities.multizone.time.sleep"):
            set_zone_colors(strip, [RED, RED, BLUE])
        self.assertEqual(
            [
                (call.args[0], call.args[1])
                for call in strip.set_zone_color.call_args_list
            ],
            [(0, 1), (0, 1), (2, 2)],
        )

    def test_cancelled_zone_retry_stops_before_more_packets(self):
        cancelled = False

        def fail(*args, **kwargs):
            nonlocal cancelled
            cancelled = True
            raise lifxlan.WorkflowException("Lost ACK")

        strip = SimpleNamespace(
            supports_extended_multizone=False, set_zone_color=Mock(side_effect=fail)
        )
        with patch("lifx_control_panel.utilities.multizone.time.sleep"):
            set_zone_colors(strip, [RED, BLUE], cancelled=lambda: cancelled)
        self.assertEqual(strip.set_zone_color.call_count, 1)

    def test_failed_capability_probe_does_not_guess_or_flood(self):
        strip = lifxlan.MultiZoneLight("00:16:3e:00:00:01", "127.0.0.1")
        strip.req_with_resp = Mock(
            side_effect=lifxlan.WorkflowException("No firmware reply")
        )
        strip.req_with_ack, strip.set_zone_color = Mock(), Mock()
        with self.assertRaises(lifxlan.WorkflowException):
            set_zone_colors(strip, [RED, BLUE])
        strip.req_with_ack.assert_not_called()
        strip.set_zone_color.assert_not_called()


class RemainingUiTests(TkFixture):
    def test_all_power_keeps_both_queued_writes_with_overlapping_group(self):
        gate = self.master.commands = CommandGate()
        bulbs = [DummyBulb(label="Desk"), DummyBulb(label="Wall")]
        states = [prefetch_device(bulb) for bulb in bulbs]
        for state in states:
            self.master.frame_map[state.label] = LightFrame(
                self.master, state.device, state
            )
        combined = group_state("Room", states)
        self.master.frame_map["Room"] = GroupFrame(
            self.master, combined.device, combined
        )
        queued = []
        app = app_class()
        parent = SimpleNamespace(
            frame_map=self.master.frame_map, commands=gate, run_device_job=queued.append
        )
        parent.apply_action = lambda label, action: app.apply_action(
            parent, label, action
        )
        app.all_power(parent, True)
        for function in queued:
            function()
        self.assertEqual([bulb.get_power() for bulb in bulbs], [65535, 65535])
        saved = {section: dict(config[section]) for section in config.sections()}

        def restore_config():
            config.clear()
            config.read_dict(saved)

        self.addCleanup(restore_config)
        if not config.has_section("SavedState"):
            config.add_section("SavedState")
        for bulb in bulbs:
            config["SavedState"][device_key(bulb)] = capture_state(bulb)
            bulb.set_power(0)
        queued.clear()
        parent.logger = Mock()
        parent.run_device_job = lambda function, completed=None: queued.append(
            (function, completed)
        )
        app.restore_state(parent)
        for function, completed in queued:
            result = function()
            if completed:
                completed(result)
        self.assertEqual([bulb.get_power() for bulb in bulbs], [65535, 65535])

    def test_file_save_and_restore_uses_mac_keys_and_atomic_config_writer(self):
        saved = {section: dict(config[section]) for section in config.sections()}

        def restore_config():
            config.clear()
            config.read_dict(saved)

        self.addCleanup(restore_config)
        app = app_class()
        bulb = DummyBulb(label="Desk")
        bulb.set_color(RED)
        gate = self.master.commands = CommandGate()
        frame = LightFrame(self.master, bulb, prefetch_device(bulb))
        self.master.frame_map["Desk"] = frame

        def run(function, completed=None):
            result = function()
            if completed:
                completed(result)

        parent = SimpleNamespace(
            bulb_interface=SimpleNamespace(device_list=[bulb]),
            commands=gate,
            logger=Mock(),
            frame_map={"Desk": frame},
            run_device_job=run,
        )
        with patch("lifx_control_panel.__main__.save_config") as write:
            app.save_state(parent)
            write.assert_called_once()
        self.assertIn(device_key(bulb), config["SavedState"])
        bulb.set_color(BLUE)
        app.restore_state(parent)
        self.assertEqual(tuple(bulb.get_color()), RED)

    def test_tray_callbacks_enqueue_actions_before_touching_lights(self):
        app = app_class()
        parent = SimpleNamespace(
            _tray_targets=("Desk",),
            post_ui=Mock(),
            all_power=Mock(),
            apply_action=Mock(),
            on_closing=Mock(),
            _root_window=lambda: self.root,
        )
        menu = app.build_tray_menu(parent)
        all_on = list(menu)[1]
        all_on(None)
        parent.all_power.assert_not_called()
        parent.post_ui.call_args.args[0]()
        parent.all_power.assert_called_once_with(True)
        self.assertEqual(list(list(menu)[3].submenu)[0].text, "Desk")

    def test_group_toggle_turns_mixed_group_off_together(self):
        first, second = DummyBulb(label="Desk"), DummyBulb(label="Wall")
        first.set_power(65535)
        second.set_power(0)
        frame = SimpleNamespace(
            target=lifxlan.Group([first, second]), _stop_conflicting_effects=Mock()
        )
        parent = SimpleNamespace(
            frame_map={"Room": frame},
            commands=CommandGate(),
            run_device_job=lambda function: function(),
        )
        app_class().apply_action(parent, "Room", "Toggle Power")
        self.assertEqual([first.get_power(), second.get_power()], [0, 0])

    def test_numeric_entries_use_degrees_percentages_and_kelvin_limits(self):
        frame = self.make_frame("Desk", 100)
        frame.hsbk_entry_vars[2].set("50")
        frame.commit_entry(2)
        self.assertEqual(frame.hsbk[2].get(), 32768)
        frame.hsbk_entry_vars[3].set("50000")
        frame.commit_entry(3)
        self.assertEqual(frame.hsbk[3].get(), 9000)
        frame.hsbk_entry_vars[0].set("nan")
        frame.commit_entry(0)
        self.assertEqual(frame.hsbk[0].get(), 100)

    def test_zone_stroke_sends_only_on_release(self):
        strip = MultiZoneDummy(num_zones=8)
        self.master.commands = CommandGate()
        self.master.run_device_job = lambda function, completed=None: function()
        frame = MultiZoneFrame(self.master, strip, prefetch_device(strip))
        self.master.frame_map["Strip"] = frame
        frame.apply_color_preview(RED, update_zones=False)
        with patch.object(
            strip, "set_zone_color", wraps=strip.set_zone_color
        ) as send, patch("lifx_control_panel.utilities.multizone.time.sleep"):
            frame.paint_zone(SimpleNamespace(x=frame.zone_width * 1.5))
            frame.paint_zone(SimpleNamespace(x=frame.zone_width * 2.5))
            send.assert_not_called()
            frame.commit_zones()
        self.assertEqual(strip.get_color_zones()[1:3], [RED, RED])

    def test_power_shortcut_stops_effects_and_runs_queued_action(self):
        frame = self.make_frame("Desk", 100)
        app = app_class()
        parent = SimpleNamespace(
            frame_map={"Desk": frame},
            commands=CommandGate(),
            run_device_job=lambda function: function(),
        )
        frame.target.get_power.return_value = 65535
        app.apply_action(parent, "Desk", "Toggle Power")
        frame.target.set_power.assert_called_once_with(0, rapid=False)

    def test_complete_device_label_is_wrapped_without_truncation(self):
        from lifx_control_panel.ui.icon_list import BulbIconList

        icons = BulbIconList(self.master, is_group=True)
        label = "A long room name beyond eight characters"
        icons.draw_bulb_icon(None, label)
        self.assertEqual(
            icons.canvas.itemcget(icons.bulb_dict[label][2], "text"), label
        )
        bounds = icons.canvas.bbox(icons.bulb_dict[label][2])
        self.assertLessEqual(bounds[3], icons.scroll_y)


class StartupTests(unittest.TestCase):
    @unittest.skipUnless(
        __import__("sys").platform == "win32", "Windows shortcut integration"
    )
    def test_shortcut_with_spaces_and_apostrophe_in_a_temporary_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "A user's startup shortcut.lnk"
            with patch.object(desktop, "startup_path", return_value=path):
                self.assertFalse(desktop.get_launch_on_startup())
                desktop.set_launch_on_startup(True)
                self.assertTrue(desktop.get_launch_on_startup())
                desktop.set_launch_on_startup(False)
                self.assertFalse(desktop.get_launch_on_startup())


if __name__ == "__main__":
    unittest.main()
