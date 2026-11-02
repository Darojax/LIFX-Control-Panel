# -*- coding: utf-8 -*-
"""Main lifx_control_panel GUI control

This module contains several ugly God-classes that control the GUI functions and reactions.

Notes
-----
    This is the "main" function of the app, and can be run simply with 'python main.pyw'
"""

import logging
import concurrent.futures
import os
import queue
import sys
import threading
import tkinter
import tkinter.colorchooser
import traceback
from collections import OrderedDict, defaultdict
from logging.handlers import RotatingFileHandler
from PIL import Image
from tkinter import messagebox, ttk
from typing import Dict, Union, Optional, cast

import pystray
import lifxlan

from lifx_control_panel import HEARTBEAT_RATE_MS, FRAME_PERIOD_MS, LOGFILE
from lifx_control_panel._constants import BUILD_DATE, AUTHOR, DEBUGGING, VERSION
from lifx_control_panel.frames import LightFrame, MultiZoneFrame, GroupFrame
from lifx_control_panel.ui import settings
from lifx_control_panel.ui.icon_list import BulbIconList
from lifx_control_panel.ui.settings import config, save_config
from lifx_control_panel.ui.theme import (
    THEME_PALETTES,
    apply_theme as apply_ui_theme,
    apply_window_chrome,
    normalize_theme_preference,
    resolve_theme_mode,
)
from lifx_control_panel.utilities import audio
from lifx_control_panel.utilities.device_actions import (
    CommandGate,
    KEYBIND_ACTIONS,
    devices_in,
    device_key,
    capture_state,
    decode_state,
    restore_device,
)
from lifx_control_panel.utilities.desktop import configure_dpi
from lifx_control_panel.utilities.async_bulb_interface import AsyncBulbInterface
from lifx_control_panel.utilities.keypress import KeybindManager
from lifx_control_panel.utilities.discovery import (
    SCAN_ATTEMPTS,
    prefetch_devices,
    group_state,
    install_socket_workaround,
)
from lifx_control_panel.utilities.utils import resource_path, Color, str2tuple

# determine if application is a script file or frozen exe
APPLICATION_PATH = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(__file__)
)

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
        self._closing = False
        self.commands = CommandGate()
        self._action_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self._tray_targets = ()
        self._ui_queue = queue.Queue()
        self.after(40, self._drain_ui_queue)
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
        self.tk_light_name.trace_add("write", self.bulb_changed)
        if self.tk_light_name.get():
            self.bulb_changed()

        self.group_icons.grid(row=3, column=1, sticky="w")
        self.group_icons.canvas.bind("<Button-1>", self.on_bulb_canvas_click)

        # Menus read an immutable snapshot; their callbacks enqueue UI actions.
        tray_menu = self.build_tray_menu()

        def run_tray_icon():
            image = Image.open(resource_path("res/icon_vector.ico"))
            icon = pystray.Icon("LIFX Control Panel", image, menu=tray_menu)
            self.tray_icon = icon
            if not self._closing:
                icon.run()

        self.systray_thread = threading.Thread(target=run_tray_icon, daemon=True)
        self.systray_thread.start()
        self._bind_unmap_handler()

        # Setup keybinding listener
        self.key_listener = KeybindManager(self)
        for keypress, function in dict(config["Keybinds"]).items():
            try:
                light, color = function.rsplit(":", 1)
                if color not in KEYBIND_ACTIONS:
                    color = (
                        Color(*getattr(lifxlan, color))
                        if hasattr(lifxlan, color)
                        else str2tuple(color, int)
                    )
                self.save_keybind(light, keypress, color)
            except (ValueError, TypeError) as exc:
                self.logger.warning("Ignoring invalid shortcut %s: %s", keypress, exc)

        self.apply_theme(config.get("AppSettings", "theme", fallback="system"))

        # Start icon callback
        self.after(FRAME_PERIOD_MS, self.update_icons)

        if config.getboolean("AppSettings", "restore_state_on_startup", fallback=False):
            self.restore_state()

        # Minimize if in config
        if config.getboolean("AppSettings", "start_minimized"):
            self._root_window().withdraw()

    def scan_for_lights(self):
        """Prefetch devices concurrently, then publish only complete GUI panels."""
        if isinstance(self.lifx, lifxlan.LifxLAN):
            install_socket_workaround()
        discovered = None
        for attempt in range(SCAN_ATTEMPTS):
            try:
                discovered = list(self.lifx.get_devices() or [])
                break
            except (lifxlan.WorkflowException, OSError) as exc:
                self.logger.warning(
                    "Discovery failed (attempt %d/%d): %s",
                    attempt + 1,
                    SCAN_ATTEMPTS,
                    exc,
                )
        if discovered is None:
            # Preserve the working interface and panels after a failed rescan.
            return
        for frame in self.frame_map.values():
            frame.stop_threads()
        self.bulb_interface.stopped.set()
        # Let an in-flight polling batch finish before issuing reads to those
        # same devices again. Each generation retains its own stop event.
        if self.bulb_interface.is_alive():
            self.bulb_interface.join()
        devices = [
            device for device in discovered if not isinstance(device, lifxlan.Group)
        ]

        states = prefetch_devices(devices, logger=self.logger)
        self.bulb_interface = AsyncBulbInterface(threading.Event(), HEARTBEAT_RATE_MS)
        self.bulb_interface.set_device_list(
            [state.device for state in states], states=states
        )
        groups = defaultdict(list)
        for state in states:
            light, label = state.device, state.label
            try:
                if label not in self.frame_map:
                    frame_type = (
                        MultiZoneFrame
                        if hasattr(light, "get_color_zones")
                        else LightFrame
                    )
                    frame = frame_type(self, light, initial_state=state)
                    self.frame_map[label] = frame
                    frame.grid_configure(row=1)
                else:
                    frame = self.frame_map[label]
                    frame.target = light
                    for runner in frame.threads.values():
                        runner.bulb = light
                # Registration follows successful construction, so a failure
                # cannot leave a clickable icon with no corresponding panel.
                self.device_map[label] = light
                if label not in self.bulb_icons.bulb_dict:
                    self.bulb_icons.draw_bulb_icon(light, label)
                groups[state.group_label].append(state)
            except (lifxlan.WorkflowException, OSError) as exc:
                self.logger.warning("Unable to build panel for %s: %s", label, exc)
        for label, members in groups.items():
            self.build_group_frame(label, members)
        self.bulb_interface.daemon = True
        self.bulb_interface.start()
        selected = self.tk_light_name.get()
        if selected in self.frame_map:
            self.bulb_changed()
        elif self.frame_map:
            self.tk_light_name.set(next(iter(self.frame_map)))
            self.bulb_changed()
        self._tray_targets = tuple(self.device_map.keys())
        if hasattr(self, "tray_icon"):
            self.tray_icon.update_menu()

    def build_group_frame(self, group_label, members):
        if group_label in self.frame_map and not isinstance(
            self.frame_map[group_label], GroupFrame
        ):
            self.logger.warning(
                "Group label conflicts with a light label: %s", group_label
            )
            return
        state = group_state(group_label, members)
        if group_label not in self.frame_map:
            frame = GroupFrame(self, state.device, initial_state=state)
            self.frame_map[group_label] = frame
            frame.grid_configure(row=1)
        else:
            frame = self.frame_map[group_label]
            frame.target = state.device
            for runner in frame.threads.values():
                runner.bulb = state.device
        self.device_map[group_label] = state.device
        if group_label not in self.group_icons.bulb_dict:
            self.group_icons.draw_bulb_icon(None, group_label)
        self.logger.info("Group found: %s", group_label)

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
        tags = canvas.gettags(item) if item else ()
        if not tags or tags[0] not in self.frame_map:
            return
        light_name = tags[0]
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
        def apply_color():
            if light not in self.frame_map:
                self.logger.warning("Shortcut target is unavailable: %s", light)
                return
            if isinstance(color, str) and color in KEYBIND_ACTIONS:
                self.apply_action(light, color)
            else:
                self.frame_map[light].set_color(color)

        def func():
            self.post_ui(apply_color)

        self.key_listener.register_function(keypress, func)

    def run_device_job(self, function, completed=None):
        if self._closing:
            return

        def run():
            try:
                result = function()
            except Exception as exc:
                self.logger.exception("Device action failed")
                self.post_ui(
                    lambda message=str(exc): messagebox.showerror(
                        "Device action failed", message, parent=self.master
                    )
                )
                return
            if completed is not None:
                self.post_ui(lambda: completed(result))

        self._action_executor.submit(run)

    def apply_action(self, label, action):
        frame = self.frame_map.get(label)
        if frame is None:
            return
        frame._stop_conflicting_effects()
        target = frame.target
        ticket = self.commands.ticket(target)

        def change(device):
            if action in ("On", "Off", "Toggle Power"):
                power = 65535 if action == "On" else 0
                if action == "Toggle Power":
                    power = 0 if device.get_power() else 65535
                device.set_power(power, rapid=False)
            else:
                from lifx_control_panel.utilities.multizone import set_zone_colors

                step = 6554 if action == "Brightness Up" else -6554
                if hasattr(device, "get_color_zones"):
                    colors = [list(color) for color in device.get_color_zones()]
                    for color in colors:
                        color[2] = max(0, min(65535, color[2] + step))
                    set_zone_colors(
                        device,
                        colors,
                        cancelled=lambda: not self.commands.current(ticket),
                    )
                else:
                    color = list(device.get_color())
                    color[2] = max(0, min(65535, color[2] + step))
                    device.set_color(
                        color,
                        duration=round(
                            float(config["AverageColor"]["duration"]) * 1000
                        ),
                    )

        def run():
            if not self.commands.current(ticket):
                return
            if action == "Toggle Power" and isinstance(target, lifxlan.Group):
                power = (
                    0
                    if any(device.get_power() for device in devices_in(target))
                    else 65535
                )
                self.commands.write(
                    target, lambda device: device.set_power(power, rapid=False), ticket
                )
            else:
                self.commands.write(target, change, ticket)

        self.run_device_job(run)

    def all_power(self, power):
        for label, frame in tuple(self.frame_map.items()):
            if not isinstance(frame.target, lifxlan.Group):
                self.apply_action(label, "On" if power else "Off")

    def build_tray_menu(self):
        def post(callback):
            return lambda *args: self.post_ui(callback)

        def lights():
            return tuple(
                pystray.MenuItem(
                    label,
                    pystray.Menu(
                        pystray.MenuItem(
                            "On", post(lambda name=label: self.apply_action(name, "On"))
                        ),
                        pystray.MenuItem(
                            "Off",
                            post(lambda name=label: self.apply_action(name, "Off")),
                        ),
                    ),
                )
                for label in self._tray_targets
            )

        return pystray.Menu(
            pystray.MenuItem("Open", post(self._root_window().deiconify), default=True),
            pystray.MenuItem("All lights on", post(lambda: self.all_power(True))),
            pystray.MenuItem("All lights off", post(lambda: self.all_power(False))),
            pystray.MenuItem("Lights", pystray.Menu(lights)),
            pystray.MenuItem("Quit", post(self.on_closing)),
        )

    def save_state(self):
        devices = tuple(self.bulb_interface.device_list)

        def capture():
            saved = {}
            for device in devices:
                try:
                    self.commands.write(
                        device,
                        lambda bulb: saved.update(
                            {device_key(bulb): capture_state(bulb)}
                        ),
                    )
                except (lifxlan.WorkflowException, OSError, ValueError) as exc:
                    self.logger.warning("Unable to save state: %s", exc)
            return saved

        def store(saved):
            if not config.has_section("SavedState"):
                config.add_section("SavedState")
            config["SavedState"].update(saved)
            save_config()
            self.logger.info("Saved %d light states", len(saved))

        self.run_device_job(capture, store)

    def restore_state(self):
        saved = dict(config["SavedState"]) if config.has_section("SavedState") else {}
        for label, frame in tuple(self.frame_map.items()):
            if isinstance(frame.target, lifxlan.Group):
                continue
            value = saved.get(device_key(frame.target))
            if value is None:
                continue
            try:
                state = decode_state(value)
            except (ValueError, TypeError, KeyError) as exc:
                self.logger.warning(
                    "Ignoring invalid saved state for %s: %s", label, exc
                )
                continue
            frame._stop_conflicting_effects()
            device = frame.target
            ticket = self.commands.ticket(device)

            def restore(target=device, snapshot=state, token=ticket):
                self.commands.write(
                    target,
                    lambda bulb: restore_device(
                        bulb,
                        snapshot,
                        cancelled=lambda: not self.commands.current(token),
                    ),
                    token,
                )

            def display(result, panel=frame, snapshot=state, token=ticket):
                if self.commands.current(token):
                    panel.apply_color_preview(snapshot["color"])
                    panel.tk_power_var.set(bool(snapshot["power"]))
                    if snapshot["zones"] and hasattr(panel, "display_zones"):
                        panel.display_zones(snapshot["zones"])

            self.run_device_job(restore, display)

    def delete_keybind(self, keycombo):
        """Deletes anonymous function from key_listener. Don't know why this is needed."""
        self.key_listener.unregister_function(keycombo)

    def show_settings(self):
        """Show the settings dialog box over the master window."""
        self.key_listener.shutdown()
        previous_audio_input = config.get("Audio", "InputIndex", fallback="")
        try:
            settings.SettingsDisplay(self, "Settings")
        finally:
            self.key_listener.restart()
        for frame in self.frame_map.values():
            frame.update_user_dropdown()
        current_audio_input = config.get("Audio", "InputIndex", fallback="")
        if (
            current_audio_input != previous_audio_input
            or not self.audio_interface.initialized
        ):
            for frame in self.frame_map.values():
                frame.threads["audio"].stop()
            self.audio_interface.init_audio(config)
        for frame in self.frame_map.values():
            frame.music_button.config(
                state="normal" if self.audio_interface.initialized else "disabled"
            )

    def apply_theme(self, preference: str):
        """Apply the selected UI theme to all existing widgets."""
        self._theme_applying = True
        resolved = apply_ui_theme(self.master, preference)
        for frame in self.frame_map.values():
            frame.refresh_effect_buttons()
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
            for button in self.state_menu_buttons:
                button.configure(
                    bg=palette["menu_bg"],
                    fg=palette["menu_fg"],
                    activebackground=palette["selection"],
                    activeforeground=palette["selection_fg"],
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
        self.state_menu_buttons = []
        for label, callback in (
            ("Save current state", self.save_state),
            ("Restore saved state", self.restore_state),
        ):
            button = tkinter.Button(
                self.file_dropdown,
                text=label,
                anchor="w",
                relief=tkinter.FLAT,
                borderwidth=0,
                padx=10,
                pady=4,
                command=lambda action=callback: self._run_file_menu_action(action),
            )
            button.pack(fill="x")
            self.state_menu_buttons.append(button)
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
        if self._closing:
            return
        self._closing = True
        self.logger.info("Shutting down.\n")
        for frame in self.frame_map.values():
            frame.stop_threads()
        self.bulb_interface.stopped.set()
        if hasattr(self, "key_listener"):
            self.key_listener.shutdown()
        if hasattr(self, "tray_icon"):
            self.tray_icon.stop()
        self._action_executor.shutdown(wait=False, cancel_futures=True)
        self.audio_interface.close()
        self.master.destroy()

    def post_ui(self, callback):
        """Workers enqueue actions; only the Tk thread touches widgets."""
        if not self._closing:
            self._ui_queue.put(callback)

    def _drain_ui_queue(self):
        if self._closing:
            return
        for _ in range(100):
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                self.logger.exception("UI callback failed")
            if self._closing:
                return
        self.after(40, self._drain_ui_queue)


def main(lifx_instance=None):
    """Start the GUI, bulb_interface, loggers, exception handling, and finally run the app"""
    root = None
    app_logger = logging.getLogger("root")
    try:
        configure_dpi()
        root = tkinter.Tk()
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72)
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
            app_logger.error(
                "Uncaught exception: %s:%s:%s",
                repr(type_),
                str(value),
                repr(trace_back),
                exc_info=(type_, value, trace_back),
            )

        sys.excepthook = custom_handler
        root.report_callback_exception = custom_handler

        lifxlan.light_products.append(38)  # TODO Hotfix for missing LIFX Beam

        LifxFrame(
            root,
            (
                lifx_instance
                if lifx_instance is not None
                else lifxlan.LifxLAN(verbose=DEBUGGING)
            ),
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
