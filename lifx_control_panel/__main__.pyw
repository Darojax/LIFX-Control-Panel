# -*- coding: utf-8 -*-
"""Main lifx_control_panel GUI control

This module contains several ugly God-classes that control the GUI functions and reactions.

Notes
-----
    This is the "main" function of the app, and can be run simply with 'python main.pyw'
"""

import logging
import os
import sys
import threading
import tkinter
import tkinter.colorchooser
import traceback
from collections import OrderedDict
from logging.handlers import RotatingFileHandler
from PIL import Image
from tkinter import messagebox, ttk
from typing import List, Dict, Union, Optional, cast

import pystray
import lifxlan

from lifx_control_panel import HEARTBEAT_RATE_MS, FRAME_PERIOD_MS, LOGFILE
from lifx_control_panel._constants import BUILD_DATE, AUTHOR, DEBUGGING, VERSION
from lifx_control_panel.frames import LightFrame, MultiZoneFrame, GroupFrame
from lifx_control_panel.ui import settings
from lifx_control_panel.ui.icon_list import BulbIconList
from lifx_control_panel.ui.settings import config
from lifx_control_panel.ui.theme import (
    THEME_PALETTES,
    apply_theme as apply_ui_theme,
    apply_window_chrome,
    normalize_theme_preference,
    resolve_theme_mode,
)
from lifx_control_panel.utilities import audio
from lifx_control_panel.utilities.async_bulb_interface import AsyncBulbInterface
from lifx_control_panel.utilities.keypress import KeybindManager
from lifx_control_panel.utilities.utils import resource_path, Color, str2tuple

# determine if application is a script file or frozen exe
APPLICATION_PATH = os.path.dirname(__file__)

LOGFILE = os.path.join(APPLICATION_PATH, LOGFILE)


class LifxFrame(ttk.Frame):  # pylint: disable=too-many-ancestors
    """Parent frame of application. Holds icons for each Device/Group."""

    def __init__(
        self,
        master: tkinter.Tk,
        lifx_instance: lifxlan.LifxLAN,
        bulb_interface: AsyncBulbInterface,
    ):
        # We take a lifx instance, so we can inject our own for testing.

        # Setup frame and grid
        ttk.Frame.__init__(self, master, padding="3 3 12 12")
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.grid(column=0, row=0, sticky="nwes")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.lifx: lifxlan.LifxLAN = lifx_instance
        self.bulb_interface: AsyncBulbInterface = bulb_interface
        self.audio_interface = audio.AudioInterface()
        self.audio_interface.init_audio(config)

        # Setup logger
        root_logger = getattr(master, "_lifx_logger", logging.getLogger("root"))
        master_logger: str = root_logger.name
        self.logger = logging.getLogger(master_logger + "." + self.__class__.__name__)
        self.logger.info("Root logger initialized: %s", self.logger.name)
        self.logger.info("Binary Version: %s", VERSION)
        self.logger.info("Build time: %s", BUILD_DATE)
        self.columnconfigure(1, weight=1)
        self._build_menu_strip()

        # Initialize LIFX objects
        self.tk_light_name = tkinter.StringVar(self)
        self.device_map: Dict[str, Union[lifxlan.Device, lifxlan.Group]] = (
            OrderedDict()
        )  # LifxLight objects
        self.frame_map: Dict[str, LightFrame] = {}  # corresponding LightFrame GUI
        self.current_lightframe: Optional[LightFrame] = (
            None  # currently selected and visible LightFrame
        )
        self.bulb_icons = BulbIconList(self)
        self.group_icons = BulbIconList(self, is_group=True)
        self._theme_applying = False
        self._unmap_bind_id = None
        self._file_menu_open = False

        self.scan_for_lights()

        if any(self.device_map):
            self.tk_light_name.set(next(iter(self.device_map.keys())))
        else:
            messagebox.showwarning(
                "No lights found.",
                "No LIFX devices were found on your LAN. Try using File->Rescan"
                " to search again.",
            )

        self.bulb_icons.grid(row=2, column=1, sticky="w")
        self.bulb_icons.canvas.bind("<Button-1>", self.on_bulb_canvas_click)
        # Keep light-name in sync with drop-down selection
        self.tk_light_name.trace("w", self.bulb_changed)

        self.group_icons.grid(row=3, column=1, sticky="w")
        self.group_icons.canvas.bind("<Button-1>", self.on_bulb_canvas_click)

        # Setup tray icon
        def lambda_quit(self_):
            """Build an anonymous function call w/ correct 'self' scope"""
            return lambda *_, **__: self_.on_closing()

        def lambda_adjust(self_):
            return lambda *_, **__: self_._root_window().deiconify()

        def run_tray_icon():
            """Allow SysTrayIcon in a separate thread"""
            image = Image.open(resource_path("res/icon_vector.ico"))

            icon = pystray.Icon(
                "LIFX Control Panel",
                image,
                menu=pystray.Menu(
                    pystray.MenuItem("Open", lambda_adjust(self), default=True),
                    pystray.MenuItem("Quit", lambda_quit(self)),
                ),
            )
            icon.run()

        self.systray_thread = threading.Thread(target=run_tray_icon, daemon=True)
        self.systray_thread.start()
        self._bind_unmap_handler()

        # Setup keybinding listener
        self.key_listener = KeybindManager(self)
        for keypress, function in dict(config["Keybinds"]).items():
            light, color = function.split(":")
            color = (
                Color(*globals()[color])
                if color in globals().keys()
                else str2tuple(color, int)
            )
            self.save_keybind(light, keypress, color)

        self.apply_theme(config.get("AppSettings", "theme", fallback="system"))

        # Start icon callback
        self.after(FRAME_PERIOD_MS, self.update_icons)

        # Minimize if in config
        if config.getboolean("AppSettings", "start_minimized"):
            self._root_window().withdraw()

    def scan_for_lights(self):
        """Communicating with the interface Thread, attempt to find any new devices"""
        # Stop and restart the bulb interface
        stop_event: threading.Event = self.bulb_interface.stopped
        if not stop_event.is_set():
            stop_event.set()
        discovered_devices = list(self.lifx.get_devices() or [])
        device_list: List[lifxlan.Device] = [
            cast(lifxlan.Device, dev)
            for dev in discovered_devices
            if not isinstance(dev, lifxlan.Group)
        ]
        if self.bulb_interface:
            del self.bulb_interface
        self.bulb_interface = AsyncBulbInterface(stop_event, HEARTBEAT_RATE_MS)
        self.bulb_interface.set_device_list(device_list)
        self.bulb_interface.daemon = True
        stop_event.clear()
        self.bulb_interface.start()

        light: lifxlan.Device
        for light in self.bulb_interface.device_list:
            try:
                product: str = lifxlan.product_map[light.get_product()]
                label: str = light.get_label()
                # light.get_color()
                self.device_map[label] = light
                self.logger.info('Light found: %s: "%s"', product, label)
                if label not in self.bulb_icons.bulb_dict:
                    self.bulb_icons.draw_bulb_icon(light, label)
                if label not in self.frame_map:
                    if light.supports_multizone():
                        self.frame_map[label] = MultiZoneFrame(self, light)
                    else:
                        self.frame_map[label] = LightFrame(self, light)
                    self.frame_map[label].grid_configure(row=1)
                    self.current_lightframe = self.frame_map[label]
                    try:
                        self.bulb_icons.set_selected_bulb(label)
                    except KeyError:
                        self.group_icons.set_selected_bulb(label)
                    self.logger.info(
                        "Building new frame: %s", self.frame_map[label].get_label()
                    )
                group_label = light.get_group_label()
                if group_label not in self.device_map.keys():
                    self.build_group_frame(group_label)
            except lifxlan.WorkflowException as exc:
                self.logger.warning(
                    "Error when communicating with LIFX device: %s", exc
                )
            except KeyError as exc:
                self.logger.warning(
                    "Unknown device: %s: %s", light.get_product(), light.get_label()
                )

    def build_group_frame(self, group_label: str):
        group = cast(lifxlan.Group, self.lifx.get_devices_by_group(group_label))
        self.device_map[group_label] = group
        self.group_icons.draw_bulb_icon(None, group_label)
        self.logger.info("Group found: %s", group_label)
        self.frame_map[group_label] = GroupFrame(self, group)
        self.frame_map[group_label].grid_configure(row=1)
        self.logger.info(
            "Building new frame: %s", self.frame_map[group_label].get_label()
        )

    def bulb_changed(self, *_, **__):
        """Change current display frame when bulb icon is clicked."""
        self._unbind_unmap_handler()  # unregister unmap so grid_remove doesn't trip it
        new_light_label = self.tk_light_name.get()
        # loop below removes all other frames; not just the current one (this fixes sync bugs for some reason)
        for frame in self.frame_map.values():
            frame.grid_remove()
        self.frame_map[new_light_label].grid()  # should bring to front
        self.logger.info(
            "Brought existing frame to front: %s",
            self.frame_map[new_light_label].get_label(),
        )
        self.current_lightframe = self.frame_map[new_light_label]
        self.current_lightframe.restart()
        if (
            self.current_lightframe
            and self.current_lightframe.get_label() != self.tk_light_name.get()
        ):
            self.logger.error(
                "Mismatch between LightFrame (%s) and Dropdown (%s)",
                self.current_lightframe.get_label(),
                self.tk_light_name.get(),
            )
        self._bind_unmap_handler()  # reregister callback

    def on_bulb_canvas_click(self, event):
        """Called whenever somebody clicks on one of the Device/Group icons. Switches LightFrame being shown."""
        canvas = event.widget
        # Convert to Canvas coords as we are using a Scrollbar, so Frame coords doesn't always match up.
        x_canvas = canvas.canvasx(event.x)
        y_canvas = canvas.canvasy(event.y)
        item = canvas.find_closest(x_canvas, y_canvas)
        light_name = canvas.gettags(item)[0]
        self.tk_light_name.set(light_name)
        if not canvas.master.is_group:  # BulbIconList
            self.bulb_icons.set_selected_bulb(light_name)
            if self.group_icons.current_icon:
                self.group_icons.clear_selected()
        else:
            self.group_icons.set_selected_bulb(light_name)
            if self.bulb_icons.current_icon:
                self.bulb_icons.clear_selected()

    def update_icons(self):
        """If the window isn't minimized, redraw icons to reflect their current power/color state."""
        if self.master.winfo_viewable():
            for frame in self.frame_map.values():
                if not isinstance(frame, GroupFrame) and frame.icon_update_flag:
                    self.bulb_icons.update_icon(cast(lifxlan.Device, frame.target))
                    frame.icon_update_flag = False
        self.after(FRAME_PERIOD_MS, self.update_icons)

    def save_keybind(self, light, keypress, color):
        """Builds a new anonymous function changing light to color when keypress is entered."""

        def lambda_factory(self, light, color):
            """https://stackoverflow.com/questions/938429/scope-of-lambda-functions-and-their-parameters"""
            return lambda *_, **__: self.device_map[light].set_color(
                color, duration=float(config["AverageColor"]["duration"])
            )

        func = lambda_factory(self, light, color)
        self.key_listener.register_function(keypress, func)

    def delete_keybind(self, keycombo):
        """Deletes anonymous function from key_listener. Don't know why this is needed."""
        self.key_listener.unregister_function(keycombo)

    def show_settings(self):
        """Show the settings dialog box over the master window."""
        self.key_listener.shutdown()
        previous_audio_input = config.get("Audio", "InputIndex", fallback="")
        settings.SettingsDisplay(self, "Settings")
        if self.current_lightframe:
            self.current_lightframe.update_user_dropdown()
        current_audio_input = config.get("Audio", "InputIndex", fallback="")
        if (
            current_audio_input != previous_audio_input
            or not self.audio_interface.initialized
        ):
            self.audio_interface.init_audio(config)
        for frame in self.frame_map.values():
            frame.music_button.config(
                state="normal" if self.audio_interface.initialized else "disabled"
            )
        self.key_listener.restart()

    def apply_theme(self, preference: str):
        """Apply the selected UI theme to all existing widgets."""
        self._theme_applying = True
        resolved = apply_ui_theme(self.master, preference)
        self._apply_menu_theme(THEME_PALETTES[resolve_theme_mode(preference)])
        self.master.after_idle(self._clear_theme_applying)
        self.logger.info("Theme set to %s (resolved: %s)", preference, resolved)

    def _clear_theme_applying(self):
        self._theme_applying = False

    def _bind_unmap_handler(self):
        if self._unmap_bind_id is None:
            self._unmap_bind_id = self._root_window().bind(
                "<Unmap>", self._on_master_unmap
            )

    def _unbind_unmap_handler(self):
        if self._unmap_bind_id is not None:
            self._root_window().unbind("<Unmap>", self._unmap_bind_id)
            self._unmap_bind_id = None

    def _on_master_unmap(self, *_):
        if self._theme_applying:
            return
        root_window = self._root_window()
        try:
            if root_window.state() == "iconic":
                root_window.withdraw()
        except tkinter.TclError:
            return

    def _root_window(self) -> tkinter.Tk:
        """Return the root Tk window that owns this frame."""
        return cast(tkinter.Tk, self.winfo_toplevel())

    def _apply_menu_theme(self, palette):
        try:
            self.menu_strip.configure(bg=palette["menu_bg"])
            self.file_button.configure(
                bg=palette["menu_bg"],
                fg=palette["menu_fg"],
                activebackground=palette["selection"],
                activeforeground=palette["selection_fg"],
                highlightbackground=palette["menu_bg"],
            )
            self.about_button.configure(
                bg=palette["menu_bg"],
                fg=palette["menu_fg"],
                activebackground=palette["selection"],
                activeforeground=palette["selection_fg"],
                highlightbackground=palette["menu_bg"],
            )
            self.file_dropdown.configure(
                bg=palette["menu_bg"],
                relief=tkinter.FLAT,
                borderwidth=0,
                highlightbackground=palette["menu_bg"],
            )
            self.file_rescan_button.configure(
                bg=palette["menu_bg"],
                fg=palette["menu_fg"],
                activebackground=palette["selection"],
                activeforeground=palette["selection_fg"],
                highlightbackground=palette["menu_bg"],
            )
            self.file_settings_button.configure(
                bg=palette["menu_bg"],
                fg=palette["menu_fg"],
                activebackground=palette["selection"],
                activeforeground=palette["selection_fg"],
                highlightbackground=palette["menu_bg"],
            )
            self.file_exit_button.configure(
                bg=palette["menu_bg"],
                fg=palette["menu_fg"],
                activebackground=palette["selection"],
                activeforeground=palette["selection_fg"],
                highlightbackground=palette["menu_bg"],
            )
            self.file_separator.configure(bg=palette["border"])
        except tkinter.TclError:
            pass

    def _build_menu_strip(self):
        """Create an in-window menu strip so dark mode can be fully themed."""
        self.menu_strip = tkinter.Frame(self, relief=tkinter.FLAT, borderwidth=0)
        self.menu_strip.grid(row=0, column=1, sticky="ew", pady=(0, 3))
        self.menu_strip.columnconfigure(2, weight=1)

        self.file_button = tkinter.Button(
            self.menu_strip,
            text="File",
            relief=tkinter.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=3,
            anchor="w",
            command=self._toggle_file_dropdown,
        )
        self.file_button.grid(row=0, column=0, sticky="w")

        self.file_dropdown = tkinter.Frame(
            self,
            relief=tkinter.FLAT,
            borderwidth=0,
            highlightthickness=0,
            bd=0,
        )
        self.file_rescan_button = tkinter.Button(
            self.file_dropdown,
            text="Rescan",
            anchor="w",
            relief=tkinter.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=4,
            command=lambda: self._run_file_menu_action(self.scan_for_lights),
        )
        self.file_rescan_button.pack(fill="x")
        self.file_settings_button = tkinter.Button(
            self.file_dropdown,
            text="Settings",
            anchor="w",
            relief=tkinter.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=4,
            command=lambda: self._run_file_menu_action(self.show_settings),
        )
        self.file_settings_button.pack(fill="x")
        self.file_separator = tkinter.Frame(self.file_dropdown, height=1, bd=0)
        self.file_separator.pack(fill="x", padx=2, pady=2)
        self.file_exit_button = tkinter.Button(
            self.file_dropdown,
            text="Exit",
            anchor="w",
            relief=tkinter.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=4,
            command=lambda: self._run_file_menu_action(self.on_closing),
        )
        self.file_exit_button.pack(fill="x")
        self.file_dropdown.place_forget()

        self.about_button = tkinter.Button(
            self.menu_strip,
            text="About",
            command=self.show_about,
            relief=tkinter.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=3,
        )
        self.about_button.grid(row=0, column=1, sticky="w")

        self.master.bind_all("<Button-1>", self._on_global_click, add="+")
        self.master.bind("<Configure>", self._on_master_configure, add="+")

    def _run_file_menu_action(self, callback):
        self._hide_file_dropdown()
        callback()

    def _toggle_file_dropdown(self):
        if self._file_menu_open:
            self._hide_file_dropdown()
        else:
            self._show_file_dropdown()

    def _show_file_dropdown(self):
        self._file_menu_open = True
        self._reposition_file_dropdown()
        self.file_dropdown.lift()

    def _hide_file_dropdown(self):
        if self._file_menu_open:
            self.file_dropdown.place_forget()
            self._file_menu_open = False

    def _reposition_file_dropdown(self):
        self.update_idletasks()
        x_pos = self.file_button.winfo_x()
        y_pos = self.menu_strip.winfo_y() + self.menu_strip.winfo_height()
        self.file_dropdown.place(x=x_pos, y=y_pos, anchor="nw")

    def _on_master_configure(self, *_):
        if self._file_menu_open:
            self._reposition_file_dropdown()

    def _on_global_click(self, event):
        if not self._file_menu_open:
            return
        widget = event.widget
        if widget is self.file_button:
            return
        parent = widget
        while parent is not None:
            if parent is self.file_dropdown:
                return
            parent_name = parent.winfo_parent()
            if not parent_name:
                break
            try:
                parent = parent.nametowidget(parent_name)
            except tkinter.TclError:
                break
        self._hide_file_dropdown()

    def show_about(self):
        """Show a themed About dialog above the main window."""
        dialog = tkinter.Toplevel(self.master)
        dialog.withdraw()
        dialog.title("About")
        dialog.transient(self._root_window())
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        content = (
            f"LIFX Control Panel\n"
            f"Version {VERSION}\n"
            f"{AUTHOR}, {BUILD_DATE}\n"
            f"Bulb Icons by Quixote\n"
            f"Please consider donating at ko-fi.com/sawyermclane"
        )

        text_label = tkinter.Label(
            dialog,
            text=content,
            justify=tkinter.LEFT,
            anchor=tkinter.W,
            padx=16,
            pady=14,
        )
        text_label.grid(row=0, column=0, columnspan=2, sticky="w")

        ok_button = ttk.Button(dialog, text="OK", command=dialog.destroy)
        ok_button.grid(row=1, column=1, padx=12, pady=(0, 12), sticky="e")

        theme_pref = config.get("AppSettings", "theme", fallback="system")
        apply_ui_theme(dialog, theme_pref)
        dialog.bind(
            "<Map>", lambda *_: apply_window_chrome(dialog, theme_pref), add="+"
        )
        dialog.after_idle(lambda: apply_window_chrome(dialog, theme_pref))

        dialog.update_idletasks()
        x_pos = self.master.winfo_rootx() + max(
            0, (self.master.winfo_width() - dialog.winfo_width()) // 2
        )
        y_pos = self.master.winfo_rooty() + max(
            0, (self.master.winfo_height() - dialog.winfo_height()) // 2
        )
        dialog.geometry(f"+{x_pos}+{y_pos}")
        dialog.deiconify()
        dialog.lift()
        dialog.focus_set()

    def on_closing(self):
        """Should always be called before the application exits. Shuts down all threads and closes the program."""
        self.logger.info("Shutting down.\n")
        self.master.destroy()
        self.bulb_interface.stopped.set()
        sys.exit(0)


def main():
    """Start the GUI, bulb_interface, loggers, exception handling, and finally run the app"""
    root = None
    app_logger = logging.getLogger("root")
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.title("LIFX Control Panel")
        root.resizable(False, False)

        theme_pref = normalize_theme_preference(
            config.get("AppSettings", "theme", fallback="system")
        )
        apply_ui_theme(root, theme_pref)

        # Setup main_icon
        root.iconbitmap(resource_path("res/icon_vector.ico"))

        app_logger.setLevel(logging.DEBUG)
        file_handler = RotatingFileHandler(
            LOGFILE, maxBytes=5 * 1024 * 1024, backupCount=1
        )
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        app_logger.addHandler(file_handler)
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.DEBUG)
        stream_handler.setFormatter(formatter)
        app_logger.addHandler(stream_handler)
        app_logger.info("Logger initialized.")
        setattr(root, "_lifx_logger", app_logger)

        def custom_handler(type_, value, trace_back):
            """A custom exception handler that logs exceptions in the root window's logger."""
            app_logger.exception(
                "Uncaught exception: %s:%s:%s",
                repr(type_),
                str(value),
                repr(trace_back),
            )

        sys.excepthook = custom_handler

        lifxlan.light_products.append(38)  # TODO Hotfix for missing LIFX Beam

        LifxFrame(
            root,
            lifxlan.LifxLAN(verbose=DEBUGGING),
            AsyncBulbInterface(threading.Event(), HEARTBEAT_RATE_MS),
        )
        if not config.getboolean("AppSettings", "start_minimized"):
            root.deiconify()

        # Run main app
        root.mainloop()

    except Exception as exc:  # pylint: disable=broad-except
        app_logger.exception(exc)
        messagebox.showerror(
            "Unhandled Exception",
            f"Unhandled runtime exception: {traceback.format_exc()}\n\n"
            f"Please report this at:"
            f" https://github.com/samclane/lifx_control_panel/issues",
        )
        os._exit(1)  # pylint: disable=protected-access


if __name__ == "__main__":
    main()
