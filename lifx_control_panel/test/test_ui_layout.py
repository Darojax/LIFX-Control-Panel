"""Native widget geometry and scrolling checks with simulated devices only."""

import tkinter as tk
from tkinter import font
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lifx_control_panel.test.test_maintenance import TkFixture, app_class
from lifx_control_panel.test.dummy_devices import (
    LifxLANDummy,
    DummyBulb,
    MultiZoneDummy,
)
from lifx_control_panel.utilities.async_bulb_interface import AsyncBulbInterface
import threading
from lifx_control_panel.ui.icon_list import BulbIconList
from lifx_control_panel.ui.settings import MultiListbox, SettingsDisplay
from lifx_control_panel.ui.theme import THEME_PALETTES, apply_theme


class CompactLayoutTests(TkFixture):
    def setUp(self):
        super().setUp()
        # Let Tk calculate mapped list/canvas viewports without displaying a
        # test window or injecting operating-system input.
        self.root.attributes("-alpha", 0)
        if self.root.tk.call("tk", "windowingsystem") == "win32":
            self.root.attributes("-disabled", True)
        self.root.overrideredirect(True)
        self.root.deiconify()
        self.callback_errors = []
        self.root.report_callback_exception = (
            lambda kind, value, trace: self.callback_errors.append(
                (kind.__name__, str(value))
            )
        )

    def tearDown(self):
        super().tearDown()
        self.assertEqual(self.callback_errors, [])

    def layout(self):
        self.master.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.root.geometry(
            f"{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}"
        )
        self.root.update()

    def test_actions_are_balanced_equal_sized_and_labels_fit_both_themes(self):
        frame = self.make_frame("Living room", 100)
        preview = frame.current_color.cget("background")
        for mode in ("light", "dark"):
            apply_theme(self.root, mode)
            self.layout()
            buttons = frame.action_buttons
            self.assertEqual(len(buttons), 8)
            widths = [button.winfo_width() for button in buttons]
            self.assertLessEqual(max(widths) - min(widths), 1)
            self.assertEqual(
                {button.winfo_height() for button in buttons},
                {buttons[0].winfo_height()},
            )
            for column in (0, 1):
                self.assertEqual(
                    sum(
                        int(button.grid_info()["column"]) == column
                        for button in buttons
                    ),
                    4,
                )
            for button in buttons:
                text = font.Font(font=button.cget("font")).measure(button.cget("text"))
                padding = sum(
                    button.winfo_pixels(button.cget(option))
                    for option in ("padx", "borderwidth", "highlightthickness")
                )
                self.assertLessEqual(
                    text + 2 * padding, button.winfo_width(), button.cget("text")
                )
                self.assertEqual(
                    button.cget("foreground"), THEME_PALETTES[mode]["foreground"]
                )
                self.assertEqual(
                    button.cget("activeforeground"), THEME_PALETTES[mode]["foreground"]
                )
            self.assertEqual(frame.current_color.cget("background"), preview)

    def test_screen_region_expands_without_losing_the_capture_values(self):
        frame = self.make_frame("Living room", 100)
        self.layout()
        original = frame.get_monitor_bounds()
        collapsed = frame.winfo_reqheight()
        self.assertFalse(frame.screen_region_lf.winfo_manager())
        frame._toggle_screen_region()
        self.root.update()
        self.assertEqual(frame.screen_region_lf.winfo_manager(), "grid")
        self.assertGreater(frame.winfo_reqheight(), collapsed)
        frame._toggle_screen_region()
        self.root.update()
        self.assertEqual(frame.winfo_reqheight(), collapsed)
        self.assertEqual(frame.get_monitor_bounds(), original)

    def test_preset_dropdowns_match_sizes_and_wheel_cannot_change_the_lamp(self):
        frame = self.make_frame("Living room", 100)
        frame.set_color = Mock()
        for mode in ("light", "dark"):
            apply_theme(self.root, mode)
            self.layout()
            first, second = frame.preset_dropdown, frame.user_dropdown
            self.assertLessEqual(abs(first.winfo_width() - second.winfo_width()), 1)
            self.assertEqual(first.winfo_height(), second.winfo_height())
            for dropdown in (first, second):
                label = font.nametofont("TkDefaultFont").measure(dropdown.get())
                self.assertLessEqual(label + 25, dropdown.winfo_width())
            frame.color_var.set("COLD_WHITE")
            frame.set_color.reset_mock()
            for delta in (-120, 120):
                first.event_generate("<MouseWheel>", delta=delta)
                self.root.update()
            self.assertEqual(frame.color_var.get(), "COLD_WHITE")
            frame.set_color.assert_not_called()

    def test_device_navigation_scrolls_only_when_its_rows_overflow(self):
        self.master.pack(fill="both", expand=True)
        icons = BulbIconList(self.master, is_group=True)
        icons.pack(fill="both", expand=True)
        icons.draw_bulb_icon(None, "A room name long enough to wrap fully")
        self.root.geometry("260x220")
        self.root.update()
        self.assertFalse(icons._overflow)
        self.assertFalse(icons.scrollbar.winfo_manager())
        icons.canvas.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertEqual(icons.canvas.yview(), (0.0, 1.0))
        for index in range(10):
            icons.draw_bulb_icon(None, f"Room {index}")
        self.root.update()
        self.assertTrue(icons._overflow)
        icons.canvas.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(icons.canvas.yview()[0], 0)
        self.root.geometry("260x900")
        self.root.update()
        self.assertFalse(icons._overflow)
        self.assertEqual(icons.canvas.yview(), (0.0, 1.0))

    def test_shortcut_table_cannot_scroll_past_short_content(self):
        table = MultiListbox(
            self.master, (("Light", 16), ("Shortcut", 16), ("Action", 16))
        )
        table.pack()
        for index in range(2):
            table.insert("end", (f"Lamp {index}", "ctrl+a", "RED"))
        self.layout()
        table._scroll("moveto", 0.8)
        self.root.update()
        self.assertTrue(all(column.yview() == (0.0, 1.0) for column in table.lists))
        self.assertFalse(table.scroll_frame.winfo_manager())
        for index in range(12):
            table.insert("end", (f"Lamp {index}", "ctrl+a", "BLUE"))
        self.root.update()
        self.assertEqual(table.scroll_frame.winfo_manager(), "pack")
        table._scroll("scroll", 2, "units")
        self.root.update()
        self.assertTrue(all(column.yview()[0] > 0 for column in table.lists))

    def test_settings_tabs_keep_the_dialog_compact_and_controls_available(self):
        dialog = SettingsDisplay.__new__(SettingsDisplay)
        tk.Toplevel.__init__(dialog, self.master)
        dialog.withdraw()
        dialog.parent = self.master
        body = tk.Frame(dialog)
        dialog.body(body)
        body.pack()
        dialog.buttonbox()
        for mode in ("light", "dark"):
            apply_theme(self.root, mode)
            dialog.update_idletasks()
            self.assertEqual(len(dialog.notebook.tabs()), 5)
            self.assertLess(dialog.winfo_reqheight(), 500)
            for key in ("impact", "response", "decay_ms", "brightness"):
                self.assertTrue(dialog.action_controls[key].winfo_exists())
        dialog.attributes("-alpha", 0)
        if self.root.tk.call("tk", "windowingsystem") == "win32":
            dialog.attributes("-disabled", True)
        dialog.overrideredirect(True)
        dialog.deiconify()
        heights = {}
        for name, page in dialog.pages.items():
            dialog.notebook.select(page)
            dialog.update()
            heights[name] = dialog.winfo_reqheight()
            self.assertLess(heights[name], 500)
        self.assertLess(heights["General"], heights["Screen"])
        self.assertLess(heights["Cinema Sync"], heights["Screen"])
        dialog.cancel()

    def test_destroyed_panels_release_polling_and_pending_slider_timers(self):
        frame = self.make_frame("Living room", 100)
        frame.set_color((100, 200, 300, 3500), rapid=True)
        timers = (frame._poll_after_id, frame._color_send_job)
        self.assertTrue(all(timers))
        frame.destroy()
        remaining = self.root.tk.call("after", "info")
        self.assertTrue(all(timer not in remaining for timer in timers))

    def test_main_window_stays_within_pre_refresh_width_for_lights_and_strips(self):
        audio = SimpleNamespace(
            initialized=False,
            init_audio=lambda config: None,
            get_music_color=lambda **kwargs: None,
            get_device_names=lambda: {},
            close=lambda: None,
        )
        network = LifxLANDummy()
        network.add_dummy_light(DummyBulb(label="Living room main light"))
        network.add_dummy_light(
            MultiZoneDummy(label="Movie screen strip", num_zones=16)
        )
        with patch(
            "lifx_control_panel.__main__.audio.AudioInterface", return_value=audio
        ), patch("lifx_control_panel.__main__.pystray.Icon"), patch(
            "lifx_control_panel.__main__.KeybindManager"
        ):
            app = app_class()(
                self.root, network, AsyncBulbInterface(threading.Event(), 3000)
            )
            try:
                for mode in ("light", "dark"):
                    app.apply_theme(mode)
                    for label in app.frame_map:
                        app.tk_light_name.set(label)
                        self.root.update()
                        # Keep the accepted 293 px footprint at 96 DPI, including
                        # the outer border and frame margins.
                        maximum = round(274 * self.root.winfo_fpixels("1i") / 96) + 19
                        self.assertLessEqual(
                            self.root.winfo_reqwidth(), maximum, (mode, label)
                        )
            finally:
                with patch.object(self.root, "destroy"):
                    app.on_closing()
                app.bulb_interface.join(3)
