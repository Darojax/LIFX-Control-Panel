# -*- coding: utf-8 -*-
"""UI Logic and Interface Elements for Settings

This module contains several ugly God-classes that control the settings GUI functions and reactions.

Notes
-----
    Uses a really funky design pattern for a dialog that I copied from an old project. It's bad and I should probably
    ript it out
"""

import configparser
import logging
import os
import queue
import sys
import tempfile
from pathlib import Path
import threading
from tkinter import ttk
from tkinter import (
    Toplevel,
    Frame,
    Button,
    ACTIVE,
    LEFT,
    YES,
    Label,
    Listbox,
    FLAT,
    X,
    BOTH,
    RAISED,
    FALSE,
    VERTICAL,
    Y,
    END,
    BooleanVar,
    DoubleVar,
    Checkbutton,
    StringVar,
    OptionMenu,
    Scale,
    HORIZONTAL,
    Entry,
    messagebox,
)
from tkinter.colorchooser import askcolor

import mss
from lifxlan.utils import RGBtoHSBK
from lifxlan import WHITE
from .. import RED

from ..utilities.keypress import KeybindManager
from ..utilities.device_actions import KEYBIND_ACTIONS
from ..utilities.desktop import get_launch_on_startup, set_launch_on_startup
from ..utilities.utils import resource_path, str2list
from .theme import (
    THEME_LABEL_TO_VALUE,
    apply_theme as apply_ui_theme,
    apply_window_chrome,
    normalize_theme_preference,
    theme_label_from_value,
    theme_value_from_label,
)

CONFIG_PATH = (
    Path(sys.executable).parent / "config.ini"
    if getattr(sys, "frozen", False)
    else Path(resource_path("default.ini")).parent / "config.ini"
)
config = configparser.ConfigParser(interpolation=None)  # pylint: disable=invalid-name
# Preserve legacy settings on the first portable run, then save beside the exe.
legacy_config = Path.cwd() / "config.ini"
config.read(
    [
        resource_path("default.ini"),
        str(legacy_config if not CONFIG_PATH.exists() else CONFIG_PATH),
        str(CONFIG_PATH),
    ]
)
if not config.has_section("AppSettings"):
    config.add_section("AppSettings")
if not config.has_option("AppSettings", "theme"):
    config["AppSettings"]["theme"] = "system"

# Replace this snapshot on the GUI thread; effect workers only read plain values.
# Keeping it separate from config prevents unrelated saves from committing a
# temporary slider preview. The token prevents an older dialog clearing a new one.
_action_sync_preview = None


def get_action_sync_value(option, fallback):
    """Read a live preview value, or the saved setting when no preview is active."""
    preview = _action_sync_preview
    if preview is not None and option in preview[1]:
        return preview[1][option]
    return config.getfloat("ActionSync", option, fallback=fallback)


def save_config():
    """Replace the portable settings file atomically to avoid partial writes."""
    descriptor, temporary = tempfile.mkstemp(
        dir=CONFIG_PATH.parent, prefix="config-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            config.write(output)
        os.replace(temporary, CONFIG_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# Compare datetimes
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


# boilerplate code from http://effbot.org/tkinterbook/tkinter-dialog-windows.htm
class Dialog(Toplevel):
    """Template for dialogs that include an Ok and Cancel button, and return validated user input data."""

    def __init__(self, parent: ttk.Frame, title=None):
        Toplevel.__init__(self, parent)
        self.withdraw()
        self._alpha_hidden = False
        try:
            # Keep the dialog fully invisible while widgets/layout/style settle.
            self.attributes("-alpha", 0.0)
            self._alpha_hidden = True
        except Exception:  # pylint: disable=broad-except
            self._alpha_hidden = False
        if title:
            self.title(title)
        self.parent = parent
        self.result = None
        body = Frame(self)
        self.initial_focus = self.body(body)
        body.pack(padx=5, pady=5)
        self.buttonbox()
        preference = config.get("AppSettings", "theme", fallback="system")
        apply_ui_theme(self, preference)
        self.grab_set()
        if not self.initial_focus:
            self.initial_focus = self
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Map>", self._refresh_theme, add="+")

        # Build final geometry while still hidden so the first paint is complete.
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x_pos = parent.winfo_rootx() + 50
        y_pos = parent.winfo_rooty() + 50
        self.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

        self.deiconify()
        self.after_idle(self._show_when_ready)
        self.initial_focus.focus_set()
        self.wait_window(self)

    def _show_when_ready(self):
        """Finalize visibility after the dialog and native chrome are fully styled."""
        self._refresh_theme()
        if self._alpha_hidden:
            try:
                self.attributes("-alpha", 1.0)
            except Exception:  # pylint: disable=broad-except
                pass

    def _refresh_theme(self, *_):
        """Refresh native window chrome for this dialog."""
        preference = config.get("AppSettings", "theme", fallback="system")
        apply_window_chrome(self, preference)

    # construction hooks
    def body(self, master):
        """create dialog body.  return widget that should have initial focus. This method should be overridden"""

    def buttonbox(self):
        """add standard button box. override if you don't want the standard buttons"""
        box = Frame(self)
        # pylint: disable=invalid-name
        ok = Button(box, text="OK", width=10, command=self.ok, default=ACTIVE)
        ok.pack(side=LEFT, padx=5, pady=5)
        cancel = Button(box, text="Cancel", width=10, command=self.cancel)
        cancel.pack(side=LEFT, padx=5, pady=5)

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

        box.pack()

    def ok(self, _=None):  # pylint: disable=invalid-name
        """Standard ok semantics"""
        if not self.validate():
            self.initial_focus.focus_set()  # put focus back
            return
        self.withdraw()
        self.update_idletasks()
        self.apply()
        self.cancel()

    def cancel(self, _=None):
        """put focus back to the parent window"""
        self.parent.focus_set()
        self.destroy()
        return 0

    # command hooks
    def validate(self):  # pylint: disable=no-self-use
        """Override"""
        return 1  # override

    def apply(self):
        """Override"""


class MultiListbox(Frame):  # pylint: disable=too-many-ancestors
    """Shows information about items in a column-format
    https://www.safaribooksonline.com/library/view/python-cookbook/0596001673/ch09s05.html
    """

    def __init__(self, master, lists):
        Frame.__init__(self, master)
        self.lists = []
        for list_, widget in lists:
            frame = Frame(self)
            frame.pack(side=LEFT, expand=YES, fill=BOTH)
            Label(frame, text=list_, borderwidth=1, relief=RAISED).pack(fill=X)
            list_box = Listbox(
                frame,
                width=widget,
                borderwidth=0,
                selectborderwidth=0,
                relief=FLAT,
                exportselection=FALSE,
            )
            list_box.pack(expand=YES, fill=BOTH)
            self.lists.append(list_box)
            list_box.bind("<B1-Motion>", lambda e, s=self: s._select(e.y))
            list_box.bind("<Button-1>", lambda e, s=self: s._select(e.y))
            list_box.bind("<Leave>", lambda e: "break")
            list_box.bind("<B2-Motion>", lambda e, s=self: s._b2motion(e.x, e.y))
            list_box.bind("<Button-2>", lambda e, s=self: s._button2(e.x, e.y))
        frame = Frame(self)
        frame.pack(side=LEFT, fill=Y)
        Label(frame, borderwidth=1, relief=RAISED).pack(fill=X)
        scroll = ttk.Scrollbar(
            frame, orient=VERTICAL, command=self._scroll, style="Vertical.TScrollbar"
        )
        scroll.pack(expand=YES, fill=Y)
        self.lists[0]["yscrollcommand"] = scroll.set

    def _select(self, y):  # pylint: disable=invalid-name
        """Select a row when clicked"""
        row = self.lists[0].nearest(y)
        self.selection_clear(0, END)
        self.selection_set(row)
        return "break"

    def _button2(self, x, y):  # pylint: disable=invalid-name
        for list_ in self.lists:
            list_.scan_mark(x, y)
        return "break"

    def _b2motion(self, x, y):  # pylint: disable=invalid-name
        for list_ in self.lists:
            list_.scan_dragto(x, y)
        return "break"

    def _scroll(self, *args):
        """Move the list down"""
        for list_ in self.lists:
            list_.yview(*args)

    def curselection(self):
        """Return currently selected list item"""
        return self.lists[0].curselection()

    def delete(self, first, last=None):
        """Remove an item from the list and GUI"""
        for list_ in self.lists:
            list_.delete(first, last)

    def get(self, first, last=None):
        """Get specific item from the list"""
        result = [list_.get(first, last) for list_ in self.lists]
        if last:
            return map(*([None] + result))
        return result

    def index(self, index):
        """Get index of item at index"""
        self.lists[0].index(index)

    def insert(self, index, *elements):
        """Insert element into list"""
        for elm in elements:
            for i, list_ in enumerate(self.lists):
                list_.insert(index, elm[i])

    def size(self):
        """Size of internal list at call time"""
        return self.lists[0].size()

    def see(self, index):
        """Wrapper for see function that calls on each list"""
        for list_ in self.lists:
            list_.see(index)

    def selection_anchor(self, index):
        for list_ in self.lists:
            list_.selection_anchor(index)

    def selection_clear(self, first, last=None):
        """Clear selection highlight"""
        for list_ in self.lists:
            list_.selection_clear(first, last)

    def selection_includes(self, index):
        """Check if item at index is in user selection"""
        return self.lists[0].selection_includes(index)

    def selection_set(self, first, last=None):
        """Manually change the selection"""
        for list_ in self.lists:
            list_.selection_set(first, last)


class SettingsDisplay(Dialog):
    """Settings form User Interface"""

    def body(self, master):
        self.root_window = master.master.master  # This is really gross. I'm sorry.
        root_logger = getattr(self.root_window, "logger", logging.getLogger("root"))
        self.logger = logging.getLogger(root_logger.name + ".SettingsDisplay")
        self.key_listener = None
        self._key_capture_after_id = None
        self._monitor_options_queue = queue.Queue(maxsize=1)
        self._action_preview_token = object()
        self._action_preview_closed = False
        self.bind("<Destroy>", self._end_action_preview, add="+")
        # Labels
        Label(master, text="Start Minimized?: ").grid(row=0, column=0, sticky="w")
        Label(master, text="Theme: ").grid(row=1, column=0, sticky="w")
        Label(master, text="Avg. Monitor Default: ").grid(row=2, column=0, sticky="w")
        Label(master, text="Smooth Transition Time (sec): ").grid(
            row=3, column=0, sticky="w"
        )
        Label(master, text="Brightness Offset: ").grid(row=4, column=0, sticky="w")
        Label(master, text="Add Preset Color: ").grid(row=5, column=0, sticky="w")
        Label(master, text="Audio Input Source: ").grid(row=6, column=0, sticky="w")
        Label(master, text="Add keyboard shortcut").grid(row=7, column=0, sticky="w")

        # Widgets
        # Starting minimized
        self.start_mini = BooleanVar(
            master, value=config.getboolean("AppSettings", "start_minimized")
        )
        self.start_mini_check = Checkbutton(master, variable=self.start_mini)
        selected_theme = normalize_theme_preference(
            config.get("AppSettings", "theme", fallback="system")
        )
        self.theme_selection = StringVar(
            master, value=theme_label_from_value(selected_theme)
        )
        self.theme_dropdown = OptionMenu(
            master, self.theme_selection, *THEME_LABEL_TO_VALUE.keys()
        )

        # Avg monitor color match
        self.avg_monitor = StringVar(
            master, value=config["AverageColor"]["DefaultMonitor"]
        )
        self.avg_monitor_dropdown = OptionMenu(
            master, self.avg_monitor, self.avg_monitor.get()
        )

        self.duration_scale = Scale(
            master, from_=0, to_=2, resolution=1 / 15, orient=HORIZONTAL
        )
        self.duration_scale.set(float(config["AverageColor"]["Duration"]))

        self.brightness_offset = Scale(
            master, from_=0, to_=65535, resolution=1, orient=HORIZONTAL
        )
        self.brightness_offset.set(int(config["AverageColor"]["brightnessoffset"]))

        # Custom preset color
        self.preset_color_name = Entry(master)
        self.preset_color_name.insert(END, "Enter color name...")
        self.preset_color_button = Button(
            master, text="Choose and add!", command=self.get_color
        )

        # Audio dropdown
        device_names = self.master.audio_interface.get_device_names()
        self.audio_choices = {}
        for index, name in device_names.items():
            self.audio_choices[f"{index} {name}"] = str(index)
        configured_input = config.get("Audio", "InputIndex", fallback="")
        init_string = next(
            (
                choice
                for choice, index in self.audio_choices.items()
                if index == configured_input
            ),
            next(iter(self.audio_choices), "None"),
        )
        self.audio_source = StringVar(master, init_string)
        self.as_dropdown = OptionMenu(
            master, self.audio_source, *(self.audio_choices.keys() or ["None"])
        )

        # Add keybindings
        light_names = list(self.root_window.device_map.keys())
        self.keybind_bulb_selection = StringVar(
            master, value=light_names[0] if light_names else "No lights found"
        )
        self.keybind_bulb_dropdown = OptionMenu(
            master, self.keybind_bulb_selection, *(light_names or ["No lights found"])
        )
        self.keybind_keys_select = Entry(master)
        self.keybind_keys_select.insert(END, "Add key-combo...")
        self.keybind_keys_select.config(state="readonly")
        self.keybind_keys_select.bind("<FocusIn>", self.on_keybind_keys_click)
        self.keybind_keys_select.bind("<FocusOut>", self.on_keybind_keys_focus_out)
        self.keybind_color_selection = StringVar(master, value="Color")
        first_frame = next(iter(self.root_window.frame_map.values()), None)
        self._default_colors = (
            first_frame.default_colors if first_frame else {"RED": RED, "WHITE": WHITE}
        )
        self.keybind_color_dropdown = OptionMenu(
            master,
            self.keybind_color_selection,
            *KEYBIND_ACTIONS,
            *self._default_colors,
            *(
                [*config["PresetColors"].keys()]
                if any(config["PresetColors"].keys())
                else [None]
            ),
        )
        self.keybind_add_button = Button(
            master,
            text="Add keybind",
            command=lambda *_: self.register_keybinding(
                self.keybind_bulb_selection.get(),
                self.keybind_keys_select.get(),
                self.keybind_color_selection.get(),
            ),
        )
        self.keybind_delete_button = Button(
            master, text="Delete keybind", command=self.delete_keybind
        )
        if not light_names:
            self.keybind_add_button.config(state="disabled")

        # Insert
        self.start_mini_check.grid(row=0, column=1, sticky="w")
        self.theme_dropdown.grid(row=1, column=1, sticky="w")
        ttk.Separator(master, orient=HORIZONTAL).grid(
            row=1, sticky="esw", columnspan=100
        )
        self.avg_monitor_dropdown.grid(row=2, column=1)
        self.duration_scale.grid(row=3, column=1)
        self.brightness_offset.grid(row=4, column=1)
        ttk.Separator(master, orient=HORIZONTAL).grid(
            row=4, sticky="esw", columnspan=100
        )
        self.preset_color_name.grid(row=5, column=1)
        self.preset_color_button.grid(row=5, column=2)
        ttk.Separator(master, orient=HORIZONTAL).grid(
            row=5, sticky="esw", columnspan=100
        )
        self.as_dropdown.grid(row=6, column=1)
        ttk.Separator(master, orient=HORIZONTAL).grid(
            row=6, sticky="esw", columnspan=100
        )
        self.keybind_bulb_dropdown.grid(row=7, column=1)
        self.keybind_keys_select.grid(row=7, column=2)
        self.keybind_color_dropdown.grid(row=7, column=3)
        self.keybind_add_button.grid(row=7, column=4)
        self.mlb = MultiListbox(master, (("Bulb", 5), ("Keybind", 5), ("Color", 5)))
        for keypress, fnx in dict(config["Keybinds"]).items():
            if ":" not in fnx:
                continue
            label, color = fnx.rsplit(":", 1)
            self.mlb.insert(END, (label, keypress, color))
        self.mlb.grid(row=8, columnspan=100, sticky="esw")
        self.keybind_delete_button.grid(row=9, column=0)

        Label(master, text="Screen max brightness (%):").grid(
            row=10, column=0, sticky="w"
        )
        Label(master, text="Screen dark cutoff (%):").grid(row=11, column=0, sticky="w")
        Label(master, text="Near-black threshold (0–255):").grid(
            row=12, column=0, sticky="w"
        )
        self.max_brightness = Scale(
            master, from_=0, to_=100, resolution=0.1, orient=HORIZONTAL
        )
        self.max_brightness.set(
            config.getint("AverageColor", "maxbrightness", fallback=65535) * 100 / 65535
        )
        self.min_brightness_cutoff = Scale(
            master, from_=0, to_=100, resolution=0.1, orient=HORIZONTAL
        )
        self.min_brightness_cutoff.set(
            config.getint("AverageColor", "minbrightnesscutoff", fallback=0)
            * 100
            / 65535
        )
        self.near_black_threshold = Scale(
            master, from_=0, to_=255, resolution=1, orient=HORIZONTAL
        )
        self.near_black_threshold.set(
            config.getint("AverageColor", "nearblackthreshold", fallback=10)
        )
        self.max_brightness.grid(row=10, column=1, sticky="w")
        self.min_brightness_cutoff.grid(row=11, column=1, sticky="w")
        self.near_black_threshold.grid(row=12, column=1, sticky="w")
        Label(master, text="0 disables near-black filtering").grid(
            row=12, column=2, columnspan=3, sticky="w"
        )

        self.launch_startup = BooleanVar(master, value=get_launch_on_startup())
        self.restore_startup = BooleanVar(
            master,
            value=config.getboolean(
                "AppSettings", "restore_state_on_startup", fallback=False
            ),
        )
        Checkbutton(
            master,
            text="Launch with Windows",
            variable=self.launch_startup,
            state="normal" if sys.platform == "win32" else "disabled",
        ).grid(row=13, column=0, sticky="w")
        Checkbutton(
            master,
            text="Restore saved lights on startup",
            variable=self.restore_startup,
        ).grid(row=13, column=1, columnspan=3, sticky="w")

        action_group = ttk.LabelFrame(
            master, text="Cinema Sync (movie room light)", padding=4
        )
        action_group.grid(row=14, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        self.action_controls = {}
        self._action_variables = {}
        for column, (key, label, minimum, maximum, default) in enumerate(
            (
                ("impact", "Impact (%)", 0, 100, 80),
                ("response", "Response (%)", 0, 100, 90),
                ("decay_ms", "Decay (ms)", 50, 1000, 180),
                ("brightness", "Brightness (%)", 0, 100, 100),
            )
        ):
            Label(action_group, text=label).grid(row=0, column=column, sticky="w")
            variable = DoubleVar(
                action_group, value=config.getfloat("ActionSync", key, fallback=default)
            )
            control = Scale(
                action_group,
                from_=minimum,
                to_=maximum,
                resolution=1,
                orient=HORIZONTAL,
                length=160,
                variable=variable,
            )
            control.grid(row=1, column=column, sticky="w", padx=(0, 12))
            self.action_controls[key] = control
            self._action_variables[key] = variable
        for variable in self._action_variables.values():
            variable.trace_add("write", self._preview_action_sync)
        self.after_idle(self._load_monitor_options_async)

    def _preview_action_sync(self, *_):
        """Publish numeric values without exposing Tk variables to effect workers."""
        if self._action_preview_closed:
            return
        global _action_sync_preview
        _action_sync_preview = (
            self._action_preview_token,
            {key: variable.get() for key, variable in self._action_variables.items()},
        )

    def _end_action_preview(self, event=None):
        """Drop unsaved overrides on Cancel, close, destruction, or successful OK."""
        if event is not None and event.widget is not self:
            return
        global _action_sync_preview
        if (
            _action_sync_preview is not None
            and _action_sync_preview[0] is self._action_preview_token
        ):
            _action_sync_preview = None
        self._action_preview_closed = True

    def validate(self) -> int:
        if self.min_brightness_cutoff.get() > self.max_brightness.get():
            messagebox.showerror(
                "Invalid screen brightness",
                "The dark cutoff must not exceed maximum brightness.",
                parent=self,
            )
            return 0
        if self.launch_startup.get() != get_launch_on_startup():
            try:
                set_launch_on_startup(self.launch_startup.get())
            except Exception as exc:
                messagebox.showerror(
                    "Unable to update Windows startup", str(exc), parent=self
                )
                return 0
        config["AverageColor"]["maxbrightness"] = str(
            round(self.max_brightness.get() * 65535 / 100)
        )
        config["AverageColor"]["minbrightnesscutoff"] = str(
            round(self.min_brightness_cutoff.get() * 65535 / 100)
        )
        config["AverageColor"]["nearblackthreshold"] = str(
            self.near_black_threshold.get()
        )
        if not config.has_section("ActionSync"):
            config.add_section("ActionSync")
        for key, control in self.action_controls.items():
            config["ActionSync"][key] = str(control.get())
        config["AppSettings"]["restore_state_on_startup"] = str(
            self.restore_startup.get()
        )
        config["AppSettings"]["start_minimized"] = str(self.start_mini.get())
        config["AppSettings"]["theme"] = theme_value_from_label(
            self.theme_selection.get()
        )
        config["AverageColor"]["DefaultMonitor"] = str(self.avg_monitor.get())
        config["AverageColor"]["Duration"] = str(self.duration_scale.get())
        config["AverageColor"]["BrightnessOffset"] = str(self.brightness_offset.get())
        selected_audio = self.audio_source.get()
        config["Audio"]["InputIndex"] = self.audio_choices.get(
            selected_audio, config.get("Audio", "InputIndex", fallback="0")
        )
        # Write to config file
        save_config()
        self._end_action_preview()

        if hasattr(self.root_window, "apply_theme"):
            self.root_window.apply_theme(config["AppSettings"]["theme"])

        self._shutdown_settings_listener()

        return 1

    def cancel(self, _=None):
        self._end_action_preview()
        self._shutdown_settings_listener()
        return super().cancel(_)

    def _load_monitor_options_async(self):
        thread = threading.Thread(target=self._collect_monitor_options, daemon=True)
        thread.start()
        self.after(40, self._poll_monitor_options)

    def _collect_monitor_options(self):
        options = ["full", "get_primary_monitor"]
        try:
            with mss.mss() as sct:
                options.extend([tuple(m.values()) for m in sct.monitors])
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("Unable to enumerate display options: %s", exc)
        try:
            self._monitor_options_queue.put_nowait(options)
        except queue.Full:
            pass

    def _poll_monitor_options(self):
        if not self.winfo_exists():
            return
        try:
            options = self._monitor_options_queue.get_nowait()
        except queue.Empty:
            self.after(40, self._poll_monitor_options)
            return
        self.avg_monitor_dropdown["menu"].delete(0, END)
        for option in options:
            option_value = str(option)
            self.avg_monitor_dropdown["menu"].add_command(
                label=option_value,
                command=lambda value=option_value: self.avg_monitor.set(value),
            )

    def get_color(self):
        """Present user with color palette dialog and return color in HSBK"""
        color = askcolor()[0]
        if color:
            # RGBtoHBSK sometimes returns >65535, so we have to clamp
            hsbk = [min(c, 65535) for c in RGBtoHSBK(color)]
            config["PresetColors"][self.preset_color_name.get()] = str(hsbk)

    def register_keybinding(self, bulb: str, keys: str, color: str):
        """Get the keybind from the input box and pass the color off to the root window."""
        if (
            bulb not in self.root_window.frame_map
            or not keys
            or keys == "Add key-combo..."
        ):
            messagebox.showerror(
                "Invalid shortcut",
                "Select a light, key combination and colour.",
                parent=self,
            )
            return
        try:
            if color not in KEYBIND_ACTIONS:
                color = (
                    self._default_colors[color]
                    if color in self._default_colors
                    else str2list(config["PresetColors"][color], int)
                )
            self.root_window.save_keybind(bulb, keys, color)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Invalid shortcut", str(exc), parent=self)
            return
        for row in reversed(range(self.mlb.size())):
            if self.mlb.get(row)[1] == keys:
                self.mlb.delete(row)
        config["Keybinds"][str(keys)] = str(bulb + ":" + str(color))
        self.mlb.insert(END, (str(bulb), str(keys), str(color)))
        self.keybind_keys_select.config(state="normal")
        self.keybind_keys_select.delete(0, "end")
        self.keybind_keys_select.insert(END, "Add key-combo...")
        self.keybind_keys_select.config(state="readonly")
        self.preset_color_name.focus_set()  # Set focus to a dummy widget to reset the Entry

    def on_keybind_keys_click(self, event):
        """Call when cursor is in key-combo entry"""
        if self.key_listener is None:
            self.key_listener = KeybindManager(self, sticky=True)
        self.key_listener.restart()
        self.keybind_keys_select.config(state="normal")
        self._schedule_keybind_capture()

    def on_keybind_keys_focus_out(self, _):
        self._stop_keybind_capture()

    def _schedule_keybind_capture(self):
        if self._key_capture_after_id is None:
            self._poll_keybind_capture()

    def _poll_keybind_capture(self):
        if not self.winfo_exists():
            self._key_capture_after_id = None
            return
        if self.focus_get() != self.keybind_keys_select:
            self._stop_keybind_capture()
            return
        if self.key_listener is not None:
            combo = self.key_listener.key_combo_code
            self.keybind_keys_select.delete(0, "end")
            self.keybind_keys_select.insert(END, combo)
        self._key_capture_after_id = self.after(40, self._poll_keybind_capture)

    def _stop_keybind_capture(self):
        if self._key_capture_after_id is not None:
            self.after_cancel(self._key_capture_after_id)
            self._key_capture_after_id = None
        if self.winfo_exists():
            self.keybind_keys_select.config(state="readonly")

    def _shutdown_settings_listener(self):
        self._stop_keybind_capture()
        if self.key_listener is not None:
            self.key_listener.shutdown()
            self.key_listener = None

    def delete_keybind(self):
        """Delete keybind currently selected in the multi-list box."""
        selection = self.mlb.curselection()
        if not selection:
            return
        row = selection[0]
        _, keybind, _ = self.mlb.get(row)
        self.mlb.delete(row)
        self.root_window.delete_keybind(keybind)
        config.remove_option("Keybinds", keybind)
