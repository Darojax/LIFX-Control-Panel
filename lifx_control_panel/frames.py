import logging
import queue
import math
import tkinter
from tkinter import ttk, messagebox, _setit
from typing import Union, Tuple, Dict, Mapping

import mouse
import lifxlan
import win32api

from lifxlan import (
    ORANGE,
    YELLOW,
    GREEN,
    CYAN,
    BLUE,
    PURPLE,
    PINK,
    WHITE,
    COLD_WHITE,
    WARM_WHITE,
    GOLD,
)

from lifx_control_panel import RED, FRAME_PERIOD_MS
from lifx_control_panel.ui.colorscale import ColorScale
from lifx_control_panel.ui.settings import config, save_config
from lifx_control_panel.utilities import color_thread
from lifx_control_panel.utilities.discovery import prefetch_device, group_state
from lifx_control_panel.utilities.color_thread import (
    get_screen_as_image,
)
from lifx_control_panel.utilities.utils import (
    Color,
    tuple2hex,
    hsbk_to_rgb,
    hsv_to_rgb,
    kelvin_to_rgb,
    get_primary_monitor,
    str2list,
    str2tuple,
    get_display_rects,
)

MAX_KELVIN_DEFAULT = 9000

MIN_KELVIN_DEFAULT = 1500


class LightFrame(ttk.Labelframe):  # pylint: disable=too-many-ancestors
    """Holds control and state information about a single device."""

    label: str
    target: Union[lifxlan.Group, lifxlan.Device]
    ###
    screen_region_lf: ttk.LabelFrame
    screen_region_entries: Dict[str, tkinter.Entry]
    avg_screen_btn: tkinter.Button
    dominant_screen_btn: tkinter.Button
    music_button: tkinter.Button
    preset_colors_lf: ttk.LabelFrame
    color_var: tkinter.StringVar
    default_colors: Mapping[str, Color]
    preset_dropdown: tkinter.OptionMenu
    tk_user_def_color_var: tkinter.StringVar
    user_dropdown: tkinter.OptionMenu
    current_color: tkinter.Canvas
    hsbk: Tuple[tkinter.IntVar, tkinter.IntVar, tkinter.IntVar, tkinter.IntVar]
    hsbk_labels: Tuple[tkinter.Label, tkinter.Label, tkinter.Label, tkinter.Label]
    hsbk_scale: Tuple[ColorScale, ColorScale, ColorScale, ColorScale]
    hsbk_display: Tuple[tkinter.Canvas, tkinter.Canvas, tkinter.Canvas, tkinter.Canvas]
    threads: Dict[str, color_thread.ColorThreadRunner]
    tk_power_var: tkinter.BooleanVar
    option_on: tkinter.Radiobutton
    option_off: tkinter.Radiobutton
    logger: logging.Logger
    min_kelvin: int = MIN_KELVIN_DEFAULT
    max_kelvin: int = MAX_KELVIN_DEFAULT

    def __init__(
        self, master, target: Union[lifxlan.Device, lifxlan.Group], initial_state=None
    ):
        super().__init__(
            master,
            padding=6,
        )
        self._initial_state = initial_state
        self._color_send_job = None
        self._poll_after_id = None
        self._pending_color = None
        self.bind("<Destroy>", self._dispose_frame, add="+")
        self.icon_update_flag: bool = True
        # Initialize LightFrames
        bulb_power, init_color = self._get_light_info(target)

        # Reconfigure label with correct name
        self.configure(
            labelwidget=tkinter.Label(
                master,
                text=self.label,
                font="TkHeadingFont",
                wraplength=round(250 * max(0.75, self.winfo_fpixels("1i") / 96)),
                justify="left",
                fg="#0046d5",
                relief=tkinter.FLAT,
            )
        )
        self.grid(column=0, row=2, sticky=(tkinter.N, tkinter.W, tkinter.E, tkinter.S))
        self.columnconfigure(1, weight=1)
        self.target = target

        # Setup logger
        self._setup_logger()

        # Initialize vars to hold on/off state
        self.setup_power_controls(bulb_power)

        # Initialize vars to hold and display bulb color
        self.setup_color_controls(init_color)

        # Add buttons for pre-made colors
        self._setup_color_dropdowns()

        # Add buttons for special routines
        self.special_functions_lf = ttk.LabelFrame(
            self, text="Effects & tools", padding=6
        )
        ####

        self._setup_special_functions()

        ####
        # Add custom screen region (real ugly)
        self._setup_screen_region_select()

        # Start update loop
        self.update_status_from_bulb()

    def _get_light_info(
        self, target: Union[lifxlan.Device, lifxlan.Group]
    ) -> Tuple[int, Color]:
        state = self._initial_state or prefetch_device(target)
        if state is None:
            # scan_for_lights decides whether to skip/retry this device; a
            # single unreachable bulb must never terminate the whole app.
            raise lifxlan.WorkflowException("Unable to read device state")
        self._initial_state = state
        self.label = state.label
        self.min_kelvin = state.features.get("min_kelvin") or MIN_KELVIN_DEFAULT
        self.max_kelvin = state.features.get("max_kelvin") or MAX_KELVIN_DEFAULT
        return state.power, Color(*state.color)

    def _dispose_frame(self, event):
        if event.widget is not self:
            return
        for name in ("_poll_after_id", "_color_send_job", "_eyedropper_after_id"):
            timer = getattr(self, name, None)
            if timer is not None:
                self.after_cancel(timer)
                setattr(self, name, None)
        self._pending_color = None
        for runner in getattr(self, "threads", {}).values():
            runner.stop()

    def _setup_screen_region_select(self):
        self.screen_region_lf = ttk.LabelFrame(self, text="Screen region", padding=8)
        self.screen_region_entries = {
            "left": tkinter.Entry(self.screen_region_lf, width=6),
            "width": tkinter.Entry(self.screen_region_lf, width=6),
            "top": tkinter.Entry(self.screen_region_lf, width=6),
            "height": tkinter.Entry(self.screen_region_lf, width=6),
        }
        region = config["AverageColor"][
            (
                self.label
                if self.label in config["AverageColor"].keys()
                else "defaultmonitor"
            )
        ]
        if region == "full":
            region = ["full"] * 4
        elif region[:19] == "get_primary_monitor":
            region = get_primary_monitor()
        else:
            region = str2list(region, int)
        self.screen_region_entries["left"].insert(tkinter.END, region[0])
        self.screen_region_entries["top"].insert(tkinter.END, region[1])
        self.screen_region_entries["width"].insert(tkinter.END, region[2])
        self.screen_region_entries["height"].insert(tkinter.END, region[3])
        self._grid_horiz_coordinate_box("left", 0, "width")
        self._grid_horiz_coordinate_box("top", 1, "height")
        tkinter.Button(
            self.screen_region_lf, text="Save", command=self.save_monitor_bounds
        ).grid(row=2, column=3, sticky="e", pady=(6, 0))
        self.screen_region_lf.grid(row=8, columnspan=4, sticky="ew")
        self.screen_region_lf.grid_remove()
        self.screen_region_toggle = tkinter.Button(
            self, text="Screen region...", command=self._toggle_screen_region
        )
        self.screen_region_toggle.grid(row=7, columnspan=4, sticky="ew", pady=(6, 0))

    def _toggle_screen_region(self):
        visible = bool(self.screen_region_lf.winfo_manager())
        if visible:
            self.screen_region_lf.grid_remove()
        else:
            self.screen_region_lf.grid()
        self.screen_region_toggle.configure(
            text="Screen region..." if visible else "Hide screen region"
        )
        root = self.winfo_toplevel()
        root.update_idletasks()
        root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())

    def _grid_horiz_coordinate_box(self, text: str, row, arg2):
        tkinter.Label(self.screen_region_lf, text=text).grid(
            row=row, column=0, sticky="e"
        )

        self.screen_region_entries[text].grid(row=row, column=1, padx=(0, 10))
        tkinter.Label(self.screen_region_lf, text=arg2).grid(row=row, column=2)
        self.screen_region_entries[arg2].grid(row=row, column=3)

    def _setup_special_functions(self):
        # Color cycle
        self.threads["cycle"] = color_thread.ColorThreadRunner(
            self.target, color_thread.ColorCycle(), self
        )

        def start_color_cycle():
            self._start_effect("cycle", self.color_cycle_btn)

        self.color_cycle_btn = tkinter.Button(
            self.special_functions_lf,
            text="Color Cycle",
            command=start_color_cycle,
        )
        self.color_cycle_btn.grid(row=9, column=0)
        self.threads["action"] = color_thread.ColorThreadRunner(
            self.target,
            color_thread.ActionScreenColor(),
            self,
            func_bounds=self.get_monitor_bounds,
        )
        self.action_sync_btn = tkinter.Button(
            self.special_functions_lf,
            text="Cinema Sync",
            command=lambda: self._start_effect("action", self.action_sync_btn),
        )
        self.action_sync_btn.grid(row=10, column=0)
        # Screen Avg.
        self.threads["screen"] = color_thread.ColorThreadRunner(
            self.target,
            color_thread.avg_screen_color,
            self,
            func_bounds=self.get_monitor_bounds,
        )

        def start_screen_avg():
            """Allow the screen avg. to be run in a separate thread. Also turns button green while running."""
            self._start_effect("screen", self.avg_screen_btn)

        self.avg_screen_btn = tkinter.Button(
            self.special_functions_lf,
            text="Avg. Screen Color",
            command=start_screen_avg,
        )
        self.avg_screen_btn.grid(row=6, column=0)
        tkinter.Button(
            self.special_functions_lf,
            text="Pick Color",
            command=self.get_color_from_palette,
        ).grid(row=6, column=1)
        # Screen Dominant
        self.threads["dominant"] = color_thread.ColorThreadRunner(
            self.target,
            color_thread.dominant_screen_color,
            self,
            func_bounds=self.get_monitor_bounds,
        )

        def start_screen_dominant():
            self._start_effect("dominant", self.dominant_screen_btn)

        self.dominant_screen_btn = tkinter.Button(
            self.special_functions_lf,
            text="Dominant Screen Color",
            command=start_screen_dominant,
        )
        self.dominant_screen_btn.grid(row=7, column=0)
        # Audio
        self.threads["audio"] = color_thread.ColorThreadRunner(
            self.target, self.master.audio_interface.get_music_color, self
        )

        def start_audio():
            """Allow the audio to be run in a separate thread. Also turns button green while running."""
            self._start_effect("audio", self.music_button)

        self.music_button = tkinter.Button(
            self.special_functions_lf,
            text="Music Color",
            command=start_audio,
            state=(
                "disabled" if not self.master.audio_interface.initialized else "normal"
            ),
        )
        self.music_button.grid(row=8, column=0)
        tkinter.Button(
            self.special_functions_lf,
            text="Color Eyedropper",
            command=self.eyedropper,
        ).grid(row=7, column=1)
        tkinter.Button(
            self.special_functions_lf, text="Stop effects", command=self.stop_threads
        ).grid(row=8, column=1)
        children = self.special_functions_lf.winfo_children()
        by_text = {child.cget("text"): child for child in children}
        self.avg_screen_btn.configure(text="Avg. Screen Color")
        self.dominant_screen_btn.configure(text="Dominant Screen")
        self.action_buttons = (
            self.action_sync_btn,
            by_text["Stop effects"],
            self.avg_screen_btn,
            self.dominant_screen_btn,
            self.music_button,
            self.color_cycle_btn,
            by_text["Pick Color"],
            by_text["Color Eyedropper"],
        )
        for column in range(2):
            self.special_functions_lf.columnconfigure(
                column, weight=1, uniform="actions"
            )
        for index, button in enumerate(self.action_buttons):
            button.grid(
                row=index // 2, column=index % 2, sticky="ew", padx=3, pady=2, ipady=2
            )
        self.special_functions_lf.grid(row=6, columnspan=4, sticky="ew", pady=(6, 0))

    def _setup_color_dropdowns(self):
        self.preset_colors_lf = ttk.Frame(self, padding=(0, 4))
        self.color_var = tkinter.StringVar(self, value="Presets")
        self.default_colors = {
            "RED": RED,
            "ORANGE": ORANGE,
            "YELLOW": YELLOW,
            "GREEN": GREEN,
            "CYAN": CYAN,
            "BLUE": BLUE,
            "PURPLE": PURPLE,
            "PINK": PINK,
            "WHITE": WHITE,
            "COLD_WHITE": COLD_WHITE,
            "WARM_WHITE": WARM_WHITE,
            "GOLD": GOLD,
        }
        self.preset_dropdown = tkinter.OptionMenu(
            self.preset_colors_lf, self.color_var, *self.default_colors
        )
        self.preset_colors_lf.columnconfigure((0, 1), weight=1, uniform="presets")
        self.preset_dropdown.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.preset_dropdown.configure(width=13)
        self.color_var.trace_add("write", self.change_preset_dropdown)
        self.tk_user_def_color_var = tkinter.StringVar(self, value="User Presets")
        self.user_dropdown = tkinter.OptionMenu(
            self.preset_colors_lf,
            self.tk_user_def_color_var,
            *(
                [*config["PresetColors"].keys()]
                if any(config["PresetColors"].keys())
                else [None]
            ),
        )
        self.user_dropdown.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.user_dropdown.config(
            width=13, state="normal" if config["PresetColors"] else "disabled"
        )
        self.tk_user_def_color_var.trace_add("write", self.change_user_dropdown)
        self.preset_colors_lf.grid(row=5, columnspan=4, sticky="ew", pady=(6, 0))

    def setup_color_controls(self, init_color: Color):
        self.logger.info("Initial light color HSBK: %s", init_color)
        self.current_color = tkinter.Canvas(
            self,
            background=tuple2hex(hsbk_to_rgb(init_color)),
            width=40,
            height=20,
            borderwidth=1,
            relief=tkinter.FLAT,
        )
        self.current_color.grid(row=0, column=2)
        self.hsbk = (
            tkinter.IntVar(self, init_color.hue),
            tkinter.IntVar(self, init_color.saturation),
            tkinter.IntVar(self, init_color.brightness),
            tkinter.IntVar(self, init_color.kelvin),
        )
        for i in self.hsbk:
            i.trace_add("write", self.trigger_icon_update)
        self.hsbk_entry_vars = tuple(tkinter.StringVar(self) for _ in range(4))
        self.hsbk_labels = tuple(
            tkinter.Entry(self, textvariable=value, width=7, justify="right")
            for value in self.hsbk_entry_vars
        )
        for key, entry in enumerate(self.hsbk_labels):
            entry.bind("<Return>", lambda event, index=key: self.commit_entry(index))
            entry.bind("<FocusOut>", lambda event, index=key: self.commit_entry(index))
            self.update_label(key, force=True)
        self.hsbk_scale: Tuple[ColorScale, ColorScale, ColorScale, ColorScale] = (
            ColorScale(
                self,
                to=65535.0,
                variable=self.hsbk[0],
                command=self.update_color_from_ui,
            ),
            ColorScale(
                self,
                from_=0,
                to=65535,
                variable=self.hsbk[1],
                command=self.update_color_from_ui,
                gradient="wb",
            ),
            ColorScale(
                self,
                from_=0,
                to=65535,
                variable=self.hsbk[2],
                command=self.update_color_from_ui,
                gradient="bw",
            ),
            ColorScale(
                self,
                from_=self.min_kelvin,
                to=self.max_kelvin,
                variable=self.hsbk[3],
                command=self.update_color_from_ui,
                gradient="kelvin",
            ),
        )
        relief = tkinter.FLAT
        self.hsbk_display: Tuple[
            tkinter.Canvas, tkinter.Canvas, tkinter.Canvas, tkinter.Canvas
        ] = (
            tkinter.Canvas(
                self,
                background=tuple2hex(hsv_to_rgb(360 * (init_color.hue / 65535))),
                width=20,
                height=20,
                borderwidth=1,
                relief=relief,
            ),
            tkinter.Canvas(
                self,
                background=tuple2hex(
                    (
                        int(255 * (init_color.saturation / 65535)),
                        int(255 * (init_color.saturation / 65535)),
                        int(255 * (init_color.saturation / 65535)),
                    )
                ),
                width=20,
                height=20,
                borderwidth=1,
                relief=relief,
            ),
            tkinter.Canvas(
                self,
                background=tuple2hex(
                    (
                        int(255 * (init_color.brightness / 65535)),
                        int(255 * (init_color.brightness / 65535)),
                        int(255 * (init_color.brightness / 65535)),
                    )
                ),
                width=20,
                height=20,
                borderwidth=1,
                relief=relief,
            ),
            tkinter.Canvas(
                self,
                background=tuple2hex(kelvin_to_rgb(init_color.kelvin)),
                width=20,
                height=20,
                borderwidth=1,
                relief=relief,
            ),
        )
        scale: ColorScale
        for key, scale in enumerate(self.hsbk_scale):
            tkinter.Label(
                self,
                text=("Hue (degrees)", "Saturation (%)", "Brightness (%)", "Kelvin")[
                    key
                ],
            ).grid(row=key + 1, column=0)
            scale.configure(width=round(100 * max(0.75, self.winfo_fpixels("1i") / 96)))
            scale.grid(row=key + 1, column=1, sticky="ew", padx=3, pady=5)
            self.hsbk_labels[key].grid(row=key + 1, column=2, padx=(0, 3))
            self.hsbk_display[key].grid(row=key + 1, column=3)
        self.threads: Dict[str, color_thread.ColorThreadRunner] = {}

    def setup_power_controls(self, bulb_power: int):
        self.tk_power_var = tkinter.BooleanVar(self)
        self.tk_power_var.set(bool(bulb_power))
        self.option_on = tkinter.Radiobutton(
            self,
            text="On",
            variable=self.tk_power_var,
            value=65535,
            command=self.update_power,
        )
        self.option_off = tkinter.Radiobutton(
            self,
            text="Off",
            variable=self.tk_power_var,
            value=0,
            command=self.update_power,
        )
        if self.tk_power_var.get() == 0:
            # Light is off
            self.option_off.select()
            self.option_on.selection_clear()
        else:
            self.option_on.select()
            self.option_off.selection_clear()
        self.option_on.grid(row=0, column=0)
        self.option_off.grid(row=0, column=1)

    def _setup_logger(self):
        self.logger = logging.getLogger(
            self.master.logger.name + "." + self.__class__.__name__ + f"({self.label})"
        )
        self.logger.setLevel(logging.DEBUG)
        self.logger.info(
            "%s logger initialized: %s // Device: %s",
            self.__class__.__name__,
            self.logger.name,
            self.label,
        )

    def restart(self):
        """Get updated information for the bulb when clicked."""
        self.update_status_from_bulb(run_once=True)
        self.logger.info("Light frame Restarted.")

    def get_label(self):
        """Getter method for the label attribute. Often is monkey-patched."""
        return self.label

    def trigger_icon_update(self, *_, **__):
        """Just sets a flag for now. Could be more advanced in the future."""
        self.icon_update_flag = True

    def get_color_values_hsbk(self):
        """Get color values entered into GUI"""
        return Color(*tuple(v.get() for v in self.hsbk))

    def _start_effect(self, name, button):
        """Give one effect exclusive control of this light or group."""
        self._stop_conflicting_effects()
        try:
            self.threads[name].start()
        except (ValueError, tkinter.TclError) as exc:
            messagebox.showerror("Unable to start effect", str(exc), parent=self)
            return
        self._active_effect = name
        self.refresh_effect_buttons()

    def _stop_conflicting_effects(self, keep_pending=False):
        """A group and its individual lights must not compete for the same bulb."""

        def device_ids(target):
            devices = (
                target.get_device_list()
                if isinstance(target, lifxlan.Group)
                else [target]
            )
            return {
                getattr(device, "mac_addr", None) or id(device) for device in devices
            }

        own_devices = device_ids(self.target)
        for frame in getattr(self.master, "frame_map", {}).values():
            if frame is not self and own_devices & device_ids(frame.target):
                frame.stop_threads(invalidate_commands=False)
        self.stop_threads(cancel_pending=not keep_pending)

    def refresh_effect_buttons(self):
        """Restore theme colours while retaining the active effect indicator."""
        buttons = {
            "action": self.action_sync_btn,
            "audio": self.music_button,
            "screen": self.avg_screen_btn,
            "dominant": self.dominant_screen_btn,
            "cycle": self.color_cycle_btn,
        }
        for name, button in buttons.items():
            active = name == getattr(self, "_active_effect", None)
            background = button.option_get("background", "Button")
            foreground = button.option_get("foreground", "Button")
            selection = button.option_get("selectBackground", "Button") or "#2563eb"
            button.config(
                bg=(
                    selection
                    if active
                    else background or button.configure("background")[3]
                ),
                fg=(
                    "white"
                    if active
                    else foreground or button.configure("foreground")[3]
                ),
                activebackground=(
                    selection
                    if active
                    else button.option_get("activeBackground", "Button")
                    or button.configure("activebackground")[3]
                ),
                activeforeground=(
                    "white"
                    if active
                    else foreground or button.configure("foreground")[3]
                ),
            )

    def effect_finished(self, runner):
        """Clear a finished effect on the GUI thread, including after a failure."""
        name = getattr(self, "_active_effect", None)
        if name and self.threads[name] is runner and not runner.is_running():
            self._active_effect = None
            self.refresh_effect_buttons()

    def stop_threads(self, cancel_pending=True, invalidate_commands=True):
        """Stop all ColorRunner threads"""
        if cancel_pending:
            self._cancel_pending_color()
        gate = getattr(self.master, "commands", None)
        if gate is not None and invalidate_commands:
            gate.invalidate(self.target)
        for thread in self.threads.values():
            thread.stop()
        self._active_effect = None
        self.refresh_effect_buttons()
        self._cancel_eyedropper()

    def update_power(self):
        """Send new power state to bulb when UI is changed."""
        self.set_power(self.tk_power_var.get())

    def set_power(self, power):
        self._stop_conflicting_effects()
        gate = getattr(self.master, "commands", None)
        if gate is None:
            self.target.set_power(power)
        else:
            gate.write(self.target, lambda device: device.set_power(power))
        self.tk_power_var.set(bool(power))

    def update_color_from_ui(self, *_, **__):
        """Send new color state to bulb when UI is changed."""
        self.set_color(self.get_color_values_hsbk(), rapid=True)

    def set_color(self, color, rapid=False):
        """Should be called whenever the bulb wants to change color. Sends bulb command and updates UI accordingly."""
        self._stop_conflicting_effects(keep_pending=rapid)
        color = tuple(color)
        if rapid:
            self._pending_color = color
            if self._color_send_job is None:
                self._color_send_job = self.after(50, self._flush_color)
        else:
            self._send_color(color, rapid=False)

    def _cancel_pending_color(self):
        callback = getattr(self, "_color_send_job", None)
        if callback is not None:
            self.after_cancel(callback)
        self._color_send_job = None
        self._pending_color = None

    def _flush_color(self):
        self._color_send_job = None
        color, self._pending_color = self._pending_color, None
        if color is not None:
            self._send_color(color, rapid=True)

    def _send_color(self, color, rapid):
        try:
            duration = (
                0 if rapid else round(float(config["AverageColor"]["duration"]) * 1000)
            )
            gate = getattr(self.master, "commands", None)
            if gate is None:
                self.target.set_color(color, duration=duration, rapid=rapid)
            else:
                gate.write(
                    self.target,
                    lambda device: device.set_color(
                        color, duration=duration, rapid=rapid
                    ),
                )
            self.apply_color_preview(color)
        except lifxlan.WorkflowException as exc:
            if not rapid:
                raise exc
        if not rapid:
            self.logger.debug(
                "Color changed to HSBK: %s", color
            )  # Don't pollute log with rapid color changes

    def apply_color_preview(self, color, update_zones=True):
        for key, value in enumerate(color):
            self.hsbk[key].set(value)
            self.update_label(key)
            self.update_display(key)
        self.current_color.config(background=tuple2hex(hsbk_to_rgb(color)))
        if update_zones and hasattr(self, "zone_colors"):
            self.display_zones([tuple(color)] * len(self.zone_colors))

    def update_label(self, key, force=False):
        if not force and self.focus_get() is self.hsbk_labels[key]:
            return
        value = self.hsbk[key].get()
        value = (
            value * 360 / 65535
            if key == 0
            else value * 100 / 65535 if key in (1, 2) else value
        )
        self.hsbk_entry_vars[key].set(f"{value:.4g}")

    def commit_entry(self, key):
        try:
            value = float(self.hsbk_entry_vars[key].get())
            if not math.isfinite(value):
                raise ValueError("Non-finite colour value")
            value = (
                round(value * 65535 / 360)
                if key == 0
                else round(value * 65535 / 100) if key in (1, 2) else round(value)
            )
            value = max(
                int(self.hsbk_scale[key].min), min(int(self.hsbk_scale[key].max), value)
            )
        except (ValueError, OverflowError):
            self.update_label(key, force=True)
            return
        if value != self.hsbk[key].get():
            self.hsbk[key].set(value)
            self.update_color_from_ui()
        self.update_label(key, force=True)

    def update_display(self, key: int):
        """Update color swatches to match current device state"""
        h, s, b, k = self.get_color_values_hsbk()  # pylint: disable=invalid-name
        if key == 0:
            self.hsbk_display[0].config(
                background=tuple2hex(hsv_to_rgb(360 * (h / 65535)))
            )
        elif key == 1:
            s = 65535 - s  # pylint: disable=invalid-name
            self.hsbk_display[1].config(
                background=tuple2hex(
                    (
                        int(255 * (s / 65535)),
                        int(255 * (s / 65535)),
                        int(255 * (s / 65535)),
                    )
                )
            )
        elif key == 2:
            self.hsbk_display[2].config(
                background=tuple2hex(
                    (
                        int(255 * (b / 65535)),
                        int(255 * (b / 65535)),
                        int(255 * (b / 65535)),
                    )
                )
            )
        elif key == 3:
            self.hsbk_display[3].config(background=tuple2hex(kelvin_to_rgb(k)))

    def get_color_from_palette(self):
        """Asks users for color selection using standard color palette dialog."""
        color = tkinter.colorchooser.askcolor(
            initialcolor=hsbk_to_rgb(self.get_color_values_hsbk())
        )[0]
        if color:
            # RGBtoHBSK sometimes returns >65535, so we have to truncate
            hsbk = [min(c, 65535) for c in lifxlan.RGBtoHSBK(color, self.hsbk[3].get())]
            self.set_color(hsbk)
            self.logger.info("Color set to HSBK %s from palette.", hsbk)

    def update_status_from_bulb(self, run_once=False):
        """
        Periodically update status from the bulb to keep UI in sync.
        run_once - Don't call `after` statement at end. Keeps a million workers from being instanced.
        """
        require_icon_update = False

        def newest(queues):
            values = queues.get(self.label)
            if values is None:
                return None
            latest = None
            while True:
                try:
                    latest = values.get_nowait()
                except queue.Empty:
                    return latest

        power = newest(self.master.bulb_interface.power_queue)
        if power is not None:
            require_icon_update = True
            self.tk_power_var.set(power)
            if self.tk_power_var.get() == 0:
                # Light is off
                self.option_off.select()
                self.option_on.selection_clear()
            else:
                self.option_on.select()
                self.option_off.selection_clear()

        hsbk = newest(self.master.bulb_interface.color_queue)
        if hsbk is not None:
            require_icon_update = True
            for key, _ in enumerate(self.hsbk):
                self.hsbk[key].set(hsbk[key])
                self.update_label(key)
                self.update_display(key)
            self.current_color.config(background=tuple2hex(hsbk_to_rgb(hsbk)))

        if require_icon_update:
            self.trigger_icon_update()
        if not run_once:
            self._poll_after_id = self.after(
                FRAME_PERIOD_MS, self.update_status_from_bulb
            )

    def eyedropper(self, *_, **__):
        """Wait for a click without accessing Tk from an effect worker."""
        self._stop_conflicting_effects()
        self._eyedropper_root = self.winfo_toplevel()
        self._eyedropper_was_down = False
        self._eyedropper_root.withdraw()
        self._eyedropper_after_id = self.after(10, self._poll_eyedropper)

    def _cancel_eyedropper(self):
        callback = getattr(self, "_eyedropper_after_id", None)
        if callback is not None:
            self.after_cancel(callback)
            self._eyedropper_after_id = None
        root = getattr(self, "_eyedropper_root", None)
        if root is not None:
            self._eyedropper_root = None
            root.deiconify()

    def _poll_eyedropper(self):
        self._eyedropper_after_id = None
        if win32api.GetAsyncKeyState(0x1B) & 0x8000:  # Escape cancels selection.
            self._cancel_eyedropper()
            return
        down = bool(win32api.GetAsyncKeyState(0x01) & 0x8000)
        if down:
            self._eyedropper_was_down = True
        if self._eyedropper_was_down and not down:
            try:
                screen_img = get_screen_as_image()
                x_pos, y_pos = mouse.get_position()
                left, top, _, _ = get_display_rects()[0]
                color = screen_img.getpixel((x_pos - left, y_pos - top))
                self.set_color(
                    lifxlan.RGBtoHSBK(
                        color, temperature=self.get_color_values_hsbk().kelvin
                    )
                )
            except (OSError, ValueError, IndexError) as exc:
                messagebox.showerror("Unable to pick colour", str(exc), parent=self)
            finally:
                self._cancel_eyedropper()
            return
        self._eyedropper_after_id = self.after(10, self._poll_eyedropper)

    def change_preset_dropdown(self, *_, **__):
        """Change device color to selected preset option."""
        color = Color(*globals()[self.color_var.get()])
        self._style_color_dropdown(self.preset_dropdown, color)
        self.set_color(color, False)

    def change_user_dropdown(self, *_, **__):
        """Change device color to selected user-defined option."""
        color = str2tuple(config["PresetColors"][self.tk_user_def_color_var.get()], int)
        self._style_color_dropdown(self.user_dropdown, color)
        self.set_color(color, rapid=False)

    @staticmethod
    def _style_color_dropdown(dropdown, color):
        red, green, blue = hsbk_to_rgb(color)
        foreground = (
            "black" if 0.299 * red + 0.587 * green + 0.114 * blue > 145 else "white"
        )
        background = tuple2hex((red, green, blue))
        dropdown.config(
            bg=background,
            fg=foreground,
            activebackground=background,
            activeforeground=foreground,
        )

    def update_user_dropdown(self):
        """Add newly defined color to the user color dropdown menu."""
        # self.tk_user_def_color_var.set('')
        self.user_dropdown["menu"].delete(0, "end")
        self.user_dropdown.config(
            state="normal" if config["PresetColors"] else "disabled"
        )

        for choice in config["PresetColors"]:
            self.user_dropdown["menu"].add_command(
                label=choice, command=_setit(self.tk_user_def_color_var, choice)
            )

    def get_monitor_bounds(self):
        """Return the 4 rectangle coordinates from the entry boxes in the UI"""
        return (
            f"[{self.screen_region_entries['left'].get()}, {self.screen_region_entries['top'].get()}, "
            f"{self.screen_region_entries['width'].get()}, {self.screen_region_entries['height'].get()}]"
        )

    def save_monitor_bounds(self):
        """Write monitor bounds entered into the UI into the config file."""
        try:
            color_thread.validate_monitor_bounds(self.get_monitor_bounds())
        except ValueError as exc:
            messagebox.showerror("Invalid screen region", str(exc), parent=self)
            return
        config["AverageColor"][self.label] = self.get_monitor_bounds()
        # Write to config file
        save_config()


class GroupFrame(LightFrame):
    def _get_light_info(self, target: lifxlan.Group) -> Tuple[int, Color]:
        state = self._initial_state
        if state is None:
            states = [prefetch_device(device) for device in target.get_device_list()]
            states = [member for member in states if member is not None]
            if not states:
                raise lifxlan.WorkflowException("No reachable devices in group")
            state = group_state(states[0].group_label, states)
        self.label = state.label
        self.min_kelvin = state.features.get("min_kelvin") or MIN_KELVIN_DEFAULT
        self.max_kelvin = state.features.get("max_kelvin") or MAX_KELVIN_DEFAULT
        return state.power, Color(*state.color)

    def update_status_from_bulb(self, run_once=False):
        return


class MultiZoneFrame(LightFrame):
    def __init__(self, master, target, initial_state=None):
        super().__init__(master, target, initial_state)
        self.zone_colors = list(
            self._initial_state.zones or [tuple(self.get_color_values_hsbk())]
        )
        group = ttk.LabelFrame(self, text="Zones (drag to paint)", padding=4)
        group.grid(row=9, columnspan=4, sticky="ew", pady=(6, 0))
        self.zone_canvas = tkinter.Canvas(
            group, width=240, height=28, highlightthickness=0
        )
        self.zone_canvas.pack(fill="x")
        self.zone_canvas.bind("<Button-1>", self.paint_zone)
        self.zone_canvas.bind("<B1-Motion>", self.paint_zone)
        self.zone_canvas.bind("<ButtonRelease-1>", self.commit_zones)
        self.zone_canvas.bind(
            "<Configure>", lambda event: self.display_zones(self.zone_colors)
        )
        tkinter.Button(group, text="Read zones", command=self.read_zones).pack(
            anchor="w"
        )
        self.display_zones(self.zone_colors)

    def display_zones(self, colors):
        self.zone_colors = [tuple(color) for color in colors]
        self.zone_canvas.delete("all")
        width = max(
            self.zone_canvas.winfo_width(),
            self.zone_canvas.winfo_pixels(self.zone_canvas.cget("width")),
        )
        self.zone_width = width / len(self.zone_colors)
        self.zone_rects = [
            self.zone_canvas.create_rectangle(
                index * self.zone_width,
                0,
                (index + 1) * self.zone_width,
                28,
                fill=tuple2hex(hsbk_to_rgb(color)),
                outline="",
            )
            for index, color in enumerate(self.zone_colors)
        ]

    def update_color_from_ui(self, *args):
        self._stop_conflicting_effects()
        self.apply_color_preview(self.get_color_values_hsbk(), update_zones=False)

    def paint_zone(self, event):
        self._stop_conflicting_effects()
        index = int(event.x // self.zone_width)
        if 0 <= index < len(self.zone_colors):
            color = tuple(self.get_color_values_hsbk())
            self.zone_colors[index] = color
            self.zone_canvas.itemconfigure(
                self.zone_rects[index], fill=tuple2hex(hsbk_to_rgb(color))
            )

    def commit_zones(self, event=None):
        from .utilities.multizone import set_zone_colors

        self._stop_conflicting_effects()
        colors, target = list(self.zone_colors), self.target
        gate = getattr(self.master, "commands", None)
        ticket = gate.ticket(target) if gate else None

        def send():
            if gate:
                gate.write(
                    target,
                    lambda device: set_zone_colors(
                        device, colors, cancelled=lambda: not gate.current(ticket)
                    ),
                    ticket,
                )
            else:
                set_zone_colors(target, colors)

        self.master.run_device_job(send)

    def read_zones(self):
        self._stop_conflicting_effects()
        target, gate = self.target, self.master.commands
        ticket = gate.ticket(target)

        def read():
            result = []
            gate.write(
                target, lambda device: result.extend(device.get_color_zones()), ticket
            )
            return result

        def display(colors):
            if colors and gate.current(ticket):
                self.display_zones(colors)

        self.master.run_device_job(read, display)
