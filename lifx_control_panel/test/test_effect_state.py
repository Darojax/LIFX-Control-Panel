"""Effect-state and Settings lifecycle tests using simulated lights only."""

from collections import deque
from contextlib import ExitStack
import threading
import tkinter as tk
from unittest.mock import Mock, patch

from lifx_control_panel.frames import LightFrame, GroupFrame, MultiZoneFrame
from lifx_control_panel.test.dummy_devices import (
    DummyBulb,
    MultiZoneDummy,
    LifxLANDummy,
)
from lifx_control_panel.test.test_maintenance import TkFixture, app_class
from lifx_control_panel.ui import settings
from lifx_control_panel.utilities.async_bulb_interface import AsyncBulbInterface
from lifx_control_panel.utilities.color_thread import ColorThreadRunner
from lifx_control_panel.utilities.device_actions import (
    CommandGate,
    capture_state,
    decode_state,
)
from lifx_control_panel.utilities.discovery import prefetch_device, group_state
from lifx_control_panel.utilities.effect_state import EffectMemory

ORIGINAL = (5000, 30000, 16000, 2900)
OTHER = (26000, 50000, 40000, 4500)
EFFECT = (47000, 65535, 65000, 3500)
MANUAL = (12000, 20000, 32000, 6000)
MODES = {
    "action": "action_sync_btn",
    "screen": "avg_screen_btn",
    "dominant": "dominant_screen_btn",
    "audio": "music_button",
    "cycle": "color_cycle_btn",
}


class EffectStateTests(TkFixture):
    def setUp(self):
        super().setUp()
        self.callback_errors = []
        self.root.report_callback_exception = (
            lambda kind, value, trace: self.callback_errors.append(str(value))
        )
        self.master.commands = CommandGate()
        self.master.effect_states = EffectMemory(self.master.commands)
        self.master.audio_interface.initialized = True
        self.master._closing = False
        self.jobs = deque()
        self.master.run_device_job = lambda function, completed=None: self.jobs.append(
            (function, completed)
        )
        self.master.restore_effect_states = (
            lambda leases: app_class().restore_effect_states(self.master, leases)
        )

    def tearDown(self):
        super().tearDown()
        self.assertEqual(self.callback_errors, [])

    def drain(self):
        while self.jobs:
            function, completed = self.jobs.popleft()
            result = function()
            if completed:
                completed(result)

    def panel(self, bulb):
        kind = MultiZoneFrame if isinstance(bulb, MultiZoneDummy) else LightFrame
        return self.register(kind(self.master, bulb, prefetch_device(bulb)))

    def register(self, frame):
        self.master.frame_map[frame.label] = frame
        for runner in frame.threads.values():
            runner.stop()
        frame.threads = {
            mode: Mock(start=Mock(side_effect=lambda: frame.target.set_color(EFFECT)))
            for mode in MODES
        }
        return frame

    def group(self, label, *bulbs):
        state = group_state(label, [prefetch_device(bulb) for bulb in bulbs])
        return self.register(GroupFrame(self.master, state.device, state))

    def start(self, frame, mode="action"):
        frame._start_effect(mode, getattr(frame, MODES[mode]))

    def test_every_mode_restores_colour_brightness_kelvin_and_power(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        for index, mode in enumerate(MODES):
            bulb.set_color(ORIGINAL)
            bulb.set_power(65535 if index % 2 else 0)
            original = decode_state(capture_state(bulb))
            self.start(frame, mode)
            self.drain()
            self.assertEqual(tuple(bulb.get_color()), EFFECT)
            frame.action_buttons[1].invoke()  # Stop effects.
            self.drain()
            self.assertEqual(decode_state(capture_state(bulb)), original)
            self.assertEqual(tuple(frame.get_color_values_hsbk()), ORIGINAL)
            self.assertEqual(frame.tk_power_var.get(), bool(original["power"]))

    def test_switching_and_reselecting_modes_keeps_the_first_original(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        with patch(
            "lifx_control_panel.utilities.effect_state.capture_state",
            wraps=capture_state,
        ) as capture:
            for mode in (*MODES, "cycle"):
                self.start(frame, mode)
                self.drain()
            self.assertEqual(capture.call_count, 1)
            frame.stop_effects()
            self.drain()
        self.assertEqual(tuple(bulb.get_color()), ORIGINAL)

    def test_stop_then_immediate_restart_keeps_original_until_restore_completes(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        self.start(frame)
        self.drain()
        frame.stop_effects()
        self.start(frame, "screen")
        self.drain()
        frame.stop_effects()
        self.drain()
        self.assertEqual(tuple(bulb.get_color()), ORIGINAL)

    def test_stop_cancels_capture_and_a_completed_but_undelivered_start(self):
        for deliver_capture in (False, True):
            bulb = DummyBulb(color=ORIGINAL, label=f"Desk {deliver_capture}")
            frame = self.panel(bulb)
            self.start(frame)
            if deliver_capture:
                capture, completed = self.jobs.popleft()
                result = capture()
            frame.stop_effects()
            if deliver_capture:
                completed(result)
            self.drain()
            frame.threads["action"].start.assert_not_called()
            self.assertEqual(tuple(bulb.get_color()), ORIGINAL)

    def test_manual_colour_supersedes_pending_restore_and_becomes_next_original(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        self.start(frame)
        self.drain()
        frame.stop_effects()
        frame.set_color(MANUAL)
        self.drain()
        self.assertEqual(tuple(bulb.get_color()), MANUAL)
        self.start(frame, "cycle")
        self.drain()
        frame.stop_effects()
        self.drain()
        self.assertEqual(tuple(bulb.get_color()), MANUAL)

    def test_delayed_restore_preview_cannot_overwrite_newer_manual_controls(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        self.start(frame)
        self.drain()
        frame.stop_effects()
        restore, completed = self.jobs.popleft()
        result = restore()
        frame.set_color(MANUAL)
        completed(result)
        self.assertEqual(tuple(frame.get_color_values_hsbk()), MANUAL)
        self.assertEqual(tuple(bulb.get_color()), MANUAL)

    def test_old_finish_notification_does_not_clear_a_pending_replacement(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        self.start(frame)
        frame.threads["action"].is_running.return_value = False
        frame.effect_finished(frame.threads["action"])
        self.assertEqual(frame._active_effect, "action")
        self.drain()
        self.assertEqual(tuple(bulb.get_color()), EFFECT)

    def test_destroying_a_panel_cancels_its_pending_start(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        self.start(frame)
        frame.destroy()
        self.drain()
        frame.threads["action"].start.assert_not_called()
        self.assertEqual(tuple(bulb.get_color()), ORIGINAL)

    def test_stopping_a_group_from_one_member_restores_individual_states_and_zones(
        self,
    ):
        first = DummyBulb(color=ORIGINAL, label="Desk")
        strip = MultiZoneDummy(label="Strip", num_zones=3)
        strip.set_zone_colors([ORIGINAL, OTHER, MANUAL])
        strip.set_power(65535)
        unrelated = DummyBulb(color=OTHER, label="Other room")
        for bulb in (first, strip, unrelated):
            self.panel(bulb)
        originals = [decode_state(capture_state(bulb)) for bulb in (first, strip)]
        group = self.group("Room", first, strip)
        self.start(self.master.frame_map["Other room"], "cycle")
        self.start(group)
        self.drain()
        self.master.frame_map["Desk"].stop_effects()
        self.drain()
        self.assertEqual(
            [decode_state(capture_state(bulb)) for bulb in (first, strip)], originals
        )
        self.assertEqual(
            self.master.frame_map["Strip"].zone_colors, [ORIGINAL, OTHER, MANUAL]
        )
        self.assertEqual(tuple(unrelated.get_color()), EFFECT)
        group.threads["action"].stop.assert_called()

    def test_group_to_member_handoff_restores_unused_member_and_retains_original(self):
        first = DummyBulb(color=ORIGINAL, label="Desk")
        second = DummyBulb(color=OTHER, label="Wall")
        left, right = self.panel(first), self.panel(second)
        group = self.group("Room", first, second)
        self.start(group)
        self.drain()
        self.start(left, "screen")
        self.drain()
        self.assertEqual(tuple(first.get_color()), EFFECT)
        self.assertEqual(tuple(second.get_color()), OTHER)
        left.stop_effects()
        self.drain()
        self.assertEqual(tuple(first.get_color()), ORIGINAL)
        self.assertIsNone(getattr(right, "_active_effect", None))

    def test_failed_restore_can_be_retried_without_recapturing_effect_colour(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        self.start(frame)
        self.drain()
        with patch.object(bulb, "set_color", side_effect=OSError("Offline")), patch(
            "lifx_control_panel.__main__.messagebox.showerror"
        ) as error:
            frame.stop_effects()
            self.drain()
            error.assert_called_once()
        frame.stop_effects()
        self.drain()
        self.assertEqual(tuple(bulb.get_color()), ORIGINAL)

    def test_failed_snapshot_does_not_start_an_effect(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        with patch.object(bulb, "get_color", side_effect=OSError("Offline")), patch(
            "lifx_control_panel.frames.messagebox.showerror"
        ) as error:
            self.start(frame)
            self.drain()
            error.assert_called_once()
        frame.threads["action"].start.assert_not_called()
        self.assertIsNone(frame._active_effect)
        self.assertEqual(tuple(bulb.get_color()), ORIGINAL)

    def test_same_member_stop_retries_an_unreachable_group_peer(self):
        first = DummyBulb(color=ORIGINAL, label="Desk")
        second = DummyBulb(color=OTHER, label="Wall")
        left = self.panel(first)
        self.panel(second)
        group = self.group("Room", first, second)
        self.start(group)
        self.drain()
        with patch.object(second, "set_color", side_effect=OSError("Offline")), patch(
            "lifx_control_panel.__main__.messagebox.showerror"
        ) as error:
            left.stop_effects()
            self.drain()
            error.assert_called_once()
        self.assertEqual(tuple(first.get_color()), ORIGINAL)
        self.assertEqual(tuple(second.get_color()), EFFECT)
        left.stop_effects()
        self.drain()
        self.assertEqual(tuple(second.get_color()), OTHER)

    def test_inflight_effect_calculation_cannot_overwrite_restored_state(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        frame = self.panel(bulb)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def calculate(**kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Effect was not released")
            return EFFECT

        runner = frame.threads["cycle"] = ColorThreadRunner(
            bulb, calculate, frame, continuous=False
        )
        self.start(frame, "cycle")
        self.drain()
        self.assertTrue(entered.wait(3))
        frame.stop_effects()
        self.drain()
        release.set()
        runner.thread.join(3)
        self.assertFalse(runner.thread.is_alive())
        self.assertEqual(tuple(bulb.get_color()), ORIGINAL)

    def test_inflight_snapshot_cannot_reappear_after_a_manual_override(self):
        bulb = DummyBulb(color=ORIGINAL, label="Desk")
        memory, gate = self.master.effect_states, self.master.commands
        claims, _ = memory.begin(bulb, self, [])
        ticket = gate.ticket(bulb)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def read():
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Snapshot was not released")
            return ORIGINAL

        with patch.object(bulb, "get_color", side_effect=read):
            worker = threading.Thread(target=lambda: memory.capture(claims, ticket))
            worker.start()
            self.assertTrue(entered.wait(3))
            gate.invalidate(bulb)
            memory.release(bulb, [self], discard_target=True)
            next_claims, _ = memory.begin(bulb, self, [])
            release.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
        bulb.set_color(MANUAL)
        self.assertTrue(memory.capture(next_claims, gate.ticket(bulb)))
        self.assertEqual(memory.snapshot(next_claims[0])["color"], MANUAL)


class SettingsToggleTests(TkFixture):
    def setUp(self):
        super().setUp()
        self.callback_errors = []
        self.root.report_callback_exception = (
            lambda kind, value, trace: self.callback_errors.append(str(value))
        )
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Construct real Settings widgets while keeping all windows withdrawn.
        for method in ("deiconify", "focus_set", "grab_set", "wait_window"):
            self.stack.enter_context(patch.object(settings.Dialog, method))
        self.stack.enter_context(patch.object(self.master, "focus_set"))
        self.stack.enter_context(
            patch.object(settings.SettingsDisplay, "_load_monitor_options_async")
        )
        module = __import__(app_class().__module__, fromlist=["audio"])
        audio = Mock(initialized=True)
        audio.get_music_color = lambda **kwargs: None
        audio.get_device_names.return_value = {}
        self.stack.enter_context(
            patch.object(module.audio, "AudioInterface", return_value=audio)
        )
        self.stack.enter_context(patch.object(module.pystray, "Icon"))
        self.stack.enter_context(patch.object(module, "KeybindManager"))
        network = LifxLANDummy()
        network.add_dummy_light(DummyBulb(color=ORIGINAL, label="Desk"))
        self.app = app_class()(
            self.root, network, AsyncBulbInterface(threading.Event(), 3000)
        )
        self.stack.enter_context(patch.object(self.app, "focus_set"))

    def tearDown(self):
        with patch.object(self.root, "destroy"):
            self.app.on_closing()
        self.app.bulb_interface.join(3)
        super().tearDown()
        self.assertEqual(self.callback_errors, [])

    def test_toolbar_and_file_menu_toggle_one_nonmodal_window_and_cancel_preview(self):
        for button in (self.app.settings_button, self.app.file_settings_button):
            saved = settings.get_action_sync_value("brightness", 100)
            with patch.object(settings, "save_config") as save:
                button.invoke()
                dialog = self.app._settings_window
                self.assertIsNotNone(dialog)
                self.assertEqual(
                    self.root.tk.call("wm", "state", str(dialog)), "withdrawn"
                )
                settings.Dialog.grab_set.assert_not_called()
                settings.Dialog.wait_window.assert_not_called()
                dialog.action_controls["brightness"].set(37)
                self.assertEqual(settings.get_action_sync_value("brightness", 100), 37)
                button.invoke()
                self.assertIsNone(self.app._settings_window)
                self.assertFalse(dialog.winfo_exists())
                self.assertEqual(
                    settings.get_action_sync_value("brightness", 100), saved
                )
                save.assert_not_called()
        self.assertEqual(self.app.key_listener.shutdown.call_count, 2)
        self.assertEqual(self.app.key_listener.restart.call_count, 2)

    def test_destroy_and_reopen_release_owned_timers_without_duplicate_dialogs(self):
        self.app.show_settings()
        dialog = self.app._settings_window
        timer = dialog._show_after_id
        dialog.destroy()
        self.assertIsNone(self.app._settings_window)
        self.assertNotIn(timer, self.root.tk.call("after", "info"))
        self.app.show_settings()
        self.assertIsNot(self.app._settings_window, dialog)
        self.app.show_settings()
        self.assertIsNone(self.app._settings_window)

    def test_ok_saves_then_closes_the_tracked_window(self):
        saved = {
            section: dict(settings.config[section])
            for section in settings.config.sections()
        }

        def restore_config():
            settings.config.clear()
            settings.config.read_dict(saved)

        self.addCleanup(restore_config)
        self.app.show_settings()
        dialog = self.app._settings_window
        dialog.action_controls["brightness"].set(23)
        with patch.object(settings, "save_config") as save, patch.object(
            self.app, "apply_logging"
        ):
            dialog.ok()
        save.assert_called_once()
        self.assertIsNone(self.app._settings_window)
        self.assertEqual(settings.config.getint("ActionSync", "brightness"), 23)
        self.assertEqual(settings.get_action_sync_value("brightness", 100), 23)
