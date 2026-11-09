"""Dropdown regressions in withdrawn windows, without desktop input or grabs."""

from contextlib import contextmanager
from types import SimpleNamespace
import tkinter as tk
from tkinter import font, ttk
from unittest.mock import Mock, patch

from lifx_control_panel.test.test_maintenance import TkFixture
from lifx_control_panel.ui.dropdown import ChoiceDropdown, MenuPopup
from lifx_control_panel.ui.settings import SettingsDisplay
from lifx_control_panel.ui.theme import THEME_PALETTES, apply_theme


class DropdownFixture(TkFixture):
    def setUp(self):
        super().setUp()
        self.callback_errors = []
        self.root.report_callback_exception = (
            lambda kind, value, trace: self.callback_errors.append(str(value))
        )

    def tearDown(self):
        super().tearDown()
        self.assertEqual(self.callback_errors, [])


class DropdownTests(DropdownFixture):
    def test_native_selection_round_trips_labels_and_can_reapply_a_preset(self):
        value = tk.StringVar(self.root, "COLD_WHITE")
        dropdown = ChoiceDropdown(
            self.master, value, {"COLD_WHITE": "Cold white", "RED": "Red"}
        )
        writes = []
        value.trace_add("write", lambda *_: writes.append(value.get()))
        self.assertEqual(dropdown.get(), "Cold white")
        dropdown._prepare_popup()
        self.root.tk.call("ttk::combobox::ConfigureListbox", str(dropdown))
        listbox = f"{dropdown}.popdown.f.l"
        for _ in range(2):
            self.root.tk.call(listbox, "selection", "clear", 0, "end")
            self.root.tk.call(listbox, "selection", "set", 1)
            # Exercise Tk's selection path without posting, focusing, or grabbing.
            self.root.tk.call("ttk::combobox::LBSelect", listbox)
            self.root.update()
        self.assertEqual(writes, ["RED", "RED"])
        self.assertEqual(value.get(), "RED")
        self.assertEqual(dropdown.get(), "Red")
        value.set("COLD_WHITE")
        self.assertEqual(dropdown.get(), "Cold white")

    def test_empty_and_refreshed_choices_do_not_fire_actions_or_keep_traces(self):
        value = tk.StringVar(self.root, "Saved")
        observer = Mock()
        value.trace_add("write", observer)
        dropdown = ChoiceDropdown(self.master, value, [], placeholder="User presets")
        self.assertTrue(dropdown.instate(["disabled"]))
        self.assertEqual(dropdown.get(), "User presets")
        dropdown.set_choices(["Saved", "Another preset"])
        self.assertTrue(dropdown.instate(["readonly", "!disabled"]))
        self.assertEqual(dropdown.get(), "Saved")
        dropdown.set_choices([])
        observer.assert_not_called()
        self.assertEqual(value.get(), "Saved")
        self.assertEqual(len(value.trace_info()), 2)
        dropdown.destroy()
        self.assertEqual(len(value.trace_info()), 1)
        value.set("Still usable")
        observer.assert_called_once()

    def test_new_controls_inherit_the_current_app_theme_instead_of_windows_theme(self):
        apply_theme(self.root, "dark")
        with patch(
            "lifx_control_panel.ui.dropdown.resolve_theme_mode", return_value="light"
        ):
            dropdown = ChoiceDropdown(
                self.master, tk.StringVar(self.root, "Red"), ["Red"]
            )
            dropdown._prepare_popup()
            menu = MenuPopup(self.master, ttk.Button(self.master))
            row = menu.add_command("Settings", lambda: None)
        self.assertEqual(
            self.root.tk.call(f"{dropdown}.popdown.f.l", "cget", "-background"),
            THEME_PALETTES["dark"]["field"],
        )
        self.assertEqual(row.cget("background"), THEME_PALETTES["dark"]["field"])

    def test_popup_colors_and_overflow_update_across_repeated_theme_changes(self):
        value = tk.StringVar(self.root, "Red")
        dropdown = ChoiceDropdown(self.master, value, ["Red", "Blue"])
        style = ttk.Style(self.root)
        for mode in ("dark", "light", "dark"):
            palette = THEME_PALETTES[mode]
            apply_theme(self.root, mode)
            dropdown._prepare_popup()
            self.root.tk.call("ttk::combobox::ConfigureListbox", str(dropdown))
            popup = f"{dropdown}.popdown"
            for option, expected in (
                ("background", palette["field"]),
                ("foreground", palette["foreground"]),
                ("selectbackground", palette["selection"]),
                ("selectforeground", palette["selection_fg"]),
            ):
                self.assertEqual(
                    self.root.tk.call(f"{popup}.f.l", "cget", f"-{option}"), expected
                )
            self.assertEqual(
                style.lookup(dropdown.cget("style"), "foreground", ["readonly"]),
                palette["foreground"],
            )
            self.assertEqual(
                style.lookup(
                    dropdown.cget("style"), "foreground", ["disabled", "readonly"]
                ),
                palette["disabled"],
            )
            self.assertFalse(self.root.tk.call("winfo", "manager", f"{popup}.f.sb"))
            dropdown.set_choices([f"Choice {i}" for i in range(20)])
            self.root.tk.call("ttk::combobox::ConfigureListbox", str(dropdown))
            self.assertEqual(
                self.root.tk.call("winfo", "manager", f"{popup}.f.sb"), "grid"
            )
            dropdown.set_choices(["Red", "Blue"])
            self.root.tk.call("ttk::combobox::ConfigureListbox", str(dropdown))
            self.assertFalse(self.root.tk.call("winfo", "manager", f"{popup}.f.sb"))
            self.assertEqual(self.root.tk.call("wm", "state", popup), "withdrawn")

    def test_long_labels_fit_the_popup_without_changing_the_closed_width(self):
        label = "Stereo Mix — Realtek High Definition Audio input device"
        value = tk.StringVar(self.root, label)
        dropdown = ChoiceDropdown(self.master, value, [label], width=12)
        dropdown.pack()
        apply_theme(self.root, "dark")
        self.root.update_idletasks()
        before = dropdown.winfo_reqwidth()
        with patch.object(dropdown, "winfo_width", return_value=136), patch.object(
            dropdown, "winfo_rootx", return_value=980
        ), patch(
            "lifx_control_panel.ui.dropdown._work_area", return_value=(0, 0, 1080, 1040)
        ):
            dropdown._prepare_popup()
        offset = tuple(
            map(
                int,
                self.root.tk.splitlist(
                    ttk.Style(self.root).lookup(dropdown.cget("style"), "postoffset")
                ),
            )
        )
        self.assertGreaterEqual(
            136 + offset[2], font.nametofont("TkDefaultFont").measure(label) + 24
        )
        self.assertLessEqual(980 + offset[0] + 136 + offset[2], 1072)
        self.assertEqual(dropdown.winfo_reqwidth(), before)

    def test_popup_stays_on_a_monitor_left_of_and_below_the_primary_display(self):
        value = tk.StringVar(self.root, "Red")
        dropdown = ChoiceDropdown(self.master, value, ["Red", "Blue"])
        coordinates = {"rootx": -1800, "rooty": 2450, "width": 136, "height": 28}

        def simulated_winfo(option, *args):
            if args == (str(dropdown),) and option in coordinates:
                return coordinates[option]
            return self.root.tk.call("test_actual_winfo", option, *args)

        # Feed the same simulated monitor position to Python and Tk's actual
        # placement routine without mapping a window on the user's desktop.
        self.root.tk.call("rename", "winfo", "test_actual_winfo")
        self.root.tk.createcommand("winfo", simulated_winfo)
        try:
            with patch(
                "lifx_control_panel.ui.dropdown._work_area",
                return_value=(-1920, 1440, 0, 2480),
            ):
                dropdown._prepare_popup()
                self.root.tk.call(
                    "ttk::combobox::PlacePopdown", str(dropdown), f"{dropdown}.popdown"
                )
                self.root.update_idletasks()
        finally:
            self.root.tk.deletecommand("winfo")
            self.root.tk.call("rename", "test_actual_winfo", "winfo")
        geometry = self.root.tk.call("wm", "geometry", f"{dropdown}.popdown")
        self.assertIn("-1800+", geometry)
        y = int(geometry.rsplit("+", 1)[1])
        self.assertGreaterEqual(y, 1448)
        self.assertLess(y, 2450)

    def test_display_labels_keep_saved_monitor_coordinates_and_custom_regions(self):
        dialog = SettingsDisplay.__new__(SettingsDisplay)
        tk.Toplevel.__init__(dialog, self.master)
        dialog.withdraw()
        body = tk.Frame(dialog)
        dialog.body(body)
        dialog.after_cancel(dialog._monitor_load_after_id)
        dialog._monitor_load_after_id = None
        custom = "(100, 50, 1280, 720)"
        dialog.avg_monitor.set(custom)
        dialog._monitor_options_queue.put(
            ["full", "get_primary_monitor", (-1920, 0, 5360, 1440), (0, 0, 3440, 1440)]
        )
        dialog._poll_monitor_options()
        dropdown = dialog.avg_monitor_dropdown
        self.assertEqual(dialog.avg_monitor.get(), custom)
        self.assertEqual(dropdown.get(), f"Custom region · {custom}")
        self.assertIn("Display 1 · 3440 × 1440 (0, 0)", dropdown.cget("values"))
        dropdown.current(1)
        dropdown.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(dialog.avg_monitor.get(), "get_primary_monitor")
        dialog.destroy()


class MenuPopupTests(DropdownFixture):
    def make_menu(self):
        anchor = ttk.Button(self.master, text="File")
        menu = MenuPopup(self.master, anchor, mnemonic="f")
        self.actions = []
        for label in ("Rescan lights", "Settings", "Restore saved state"):
            menu.add_command(
                label, lambda name=label: self.actions.append((name, menu.is_open))
            )
        menu.add_separator()
        return menu

    @contextmanager
    def opened(self, menu):
        # No test maps the popup, changes real focus, or takes a desktop grab.
        with patch.object(
            menu.anchor, "winfo_viewable", return_value=True
        ), patch.object(menu.anchor, "focus_set"), patch.object(
            menu, "deiconify"
        ), patch.object(
            menu, "lift"
        ), patch.object(
            menu, "grab_set"
        ), patch.object(
            menu, "focus_get", return_value=None
        ), patch.object(
            menu, "grab_current", return_value=None
        ), patch.object(
            tk.Button, "focus_set"
        ):
            menu.show()
            yield
            menu.hide(restore_focus=False)

    def test_keyboard_navigation_invokes_only_the_selected_command_after_closing(self):
        menu = self.make_menu()
        with self.opened(menu):
            self.assertEqual(menu._selected, 0)
            self.assertEqual(menu._move(-1), "break")
            self.assertEqual(menu._selected, 2)
            menu._move(1)
            self.assertEqual(menu._selected, 0)
            menu._select_key(1)
            self.assertEqual(menu._invoke_selected(), "break")
            self.assertFalse(menu.is_open)
            self.assertEqual(self.actions, [("Settings", False)])
            self.assertFalse(menu.anchor.instate(["selected"]))

    def test_escape_outside_click_focus_loss_and_owner_unmap_dismiss_without_action(
        self,
    ):
        menu = self.make_menu()
        dismissals = (
            menu._cancel,
            lambda: menu._outside_click(SimpleNamespace(x_root=-1000, y_root=-1000)),
            menu._check_focus,
            lambda: menu._owner_unmapped(SimpleNamespace(widget=self.root)),
        )
        for dismiss in dismissals:
            with self.opened(menu):
                dismiss()
                self.assertFalse(menu.is_open)
        self.assertEqual(self.actions, [])

    def test_menu_theme_geometry_and_destroy_release_owned_bindings_and_timer(self):
        original_bindings = {
            sequence: self.root.bind(sequence)
            for sequence in ("<Configure>", "<Unmap>", "<Alt-f>")
        }
        menu = self.make_menu()
        for mode in ("light", "dark"):
            apply_theme(self.root, mode)
            palette = THEME_PALETTES[mode]
            with self.opened(menu):
                self.assertEqual(menu.cget("highlightbackground"), palette["border"])
                self.assertEqual(
                    menu._items[0].cget("foreground"), palette["selection_fg"]
                )
                self.assertEqual(
                    menu._items[1].cget("foreground"), palette["foreground"]
                )
                menu.update_idletasks()
                text = font.nametofont("TkMenuFont").measure("Restore saved state")
                self.assertGreaterEqual(menu.winfo_reqwidth(), text + 32)
        with self.opened(menu):
            menu._defer_focus_check()
            timer = menu._focus_job
            self.assertIsNotNone(timer)
            menu.destroy()
        self.assertNotIn(timer, self.root.tk.call("after", "info"))
        for sequence, original in original_bindings.items():
            self.assertEqual(self.root.bind(sequence), original)
