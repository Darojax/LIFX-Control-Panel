"""Compact device lists with live colour indicators and overflow-only scrolling."""

import tkinter
from tkinter import ttk

from ..utilities import utils


class BulbIconList(tkinter.Frame):
    """Device navigation; keep the selection/update API used by the main frame."""

    def __init__(
        self,
        *args,
        is_group=False,
        owner=None,
        compact=False,
        show_heading=True,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.owner = owner or self.master
        self.is_group = is_group
        self.compact = compact
        self.scale = max(0.75, self.winfo_fpixels("1i") / 96)
        self.bulb_dict = {}
        self._current_icon = None
        self.scroll_y = 0
        self._overflow = False
        self._palette = {
            "field": "#ffffff",
            "foreground": "#172333",
            "selection": "#2563eb",
            "selection_fg": "#ffffff",
            "disabled": "#738095",
            "accent": "#2563eb",
        }
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        if show_heading:
            ttk.Label(
                self, text="Groups" if is_group else "Lights", style="Section.TLabel"
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 6))
        self.canvas = tkinter.Canvas(
            self,
            width=round(204 * self.scale),
            height=round(130 * self.scale),
            highlightthickness=0,
            borderwidth=0,
            confine=True,
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self._scroll_changed)
        self.canvas.bind("<Configure>", self._layout_rows)
        self.canvas.bind("<MouseWheel>", self._mousewheel)
        self.canvas.bind("<Button-4>", lambda event: self._wheel_units(-1))
        self.canvas.bind("<Button-5>", lambda event: self._wheel_units(1))

    @property
    def current_icon(self):
        return self._current_icon

    def draw_bulb_icon(self, bulb, label):
        background = self.canvas.create_rectangle(
            0, 0, 1, 1, outline="", tags=(label, "row")
        )
        indicator = self.canvas.create_oval(
            0, 0, 1, 1, outline="", tags=(label, "indicator")
        )
        text = self.canvas.create_text(
            0, 0, text=label, anchor="w", tags=(label, "name")
        )
        self.bulb_dict[label] = (indicator, background, text)
        self._layout_rows()
        self.update_icon(bulb)
        self.apply_palette(self._palette)

    def _layout_rows(self, event=None):
        width = max(1, self.canvas.winfo_width())
        if width <= 1:
            width = self.canvas.winfo_pixels(self.canvas.cget("width"))
        padding = round(10 * self.scale)
        text_left = round(38 * self.scale)
        top = 0
        for indicator, background, text in self.bulb_dict.values():
            self.canvas.itemconfigure(text, width=max(20, width - text_left - padding))
            self.canvas.coords(text, text_left, top + padding)
            bounds = self.canvas.bbox(text)
            height = max(
                round(44 * self.scale),
                (bounds[3] - bounds[1] if bounds else 16) + 2 * padding,
            )
            self.canvas.coords(background, 0, top + 1, width, top + height - 1)
            middle = top + height / 2
            radius = round(7 * self.scale)
            self.canvas.coords(
                indicator,
                padding,
                middle - radius,
                padding + 2 * radius,
                middle + radius,
            )
            self.canvas.coords(text, text_left, middle)
            top += height
        self.scroll_y = top
        if self.is_group or self.compact:
            self.canvas.configure(
                height=min(
                    max(top, round(44 * self.scale)),
                    round((88 if self.compact else 130) * self.scale),
                )
            )
        viewport = max(1, self.canvas.winfo_height())
        self.canvas.configure(scrollregion=(0, 0, width, max(top, viewport)))
        self._set_overflow(top > viewport + 1)

    def _set_overflow(self, overflow):
        self._overflow = overflow
        if overflow:
            self.scrollbar.grid(row=1, column=1, sticky="ns")
        else:
            self.scrollbar.grid_remove()
            if self.canvas.yview()[0] != 0:
                self.canvas.yview_moveto(0)

    def _scroll_changed(self, first, last):
        self.scrollbar.set(first, last)

    def _wheel_units(self, units):
        if self._overflow:
            self.canvas.yview_scroll(units, "units")
        return "break"

    def _mousewheel(self, event):
        return self._wheel_units(
            -int(event.delta / 120)
            if abs(event.delta) >= 120
            else (-1 if event.delta > 0 else 1)
        )

    def apply_palette(self, palette):
        self._palette = palette
        self.canvas.configure(bg=palette["field"])
        for label, (indicator, background, text) in self.bulb_dict.items():
            selected = label == self._current_icon
            self.canvas.itemconfigure(
                background, fill=palette["selection"] if selected else palette["field"]
            )
            self.canvas.itemconfigure(
                text,
                fill=palette["selection_fg"] if selected else palette["foreground"],
            )
            if self.is_group:
                self.canvas.itemconfigure(
                    indicator,
                    fill=palette["selection_fg"] if selected else palette["accent"],
                )

    def update_icon(self, bulb):
        if self.is_group or bulb is None:
            return
        try:
            colour = self.owner.bulb_interface.color_cache[bulb.label]
            power = self.owner.bulb_interface.power_cache[bulb.label]
            indicator = self.bulb_dict[bulb.label][0]
            self.canvas.itemconfigure(
                indicator,
                fill=(
                    utils.tuple2hex(utils.hsbk_to_rgb(colour))
                    if power
                    else self._palette["disabled"]
                ),
            )
        except (AttributeError, TypeError, KeyError):
            pass

    def set_selected_bulb(self, light_name):
        if light_name in self.bulb_dict:
            self._current_icon = light_name
            self.apply_palette(self._palette)
            _, background, _ = self.bulb_dict[light_name]
            bounds = self.canvas.coords(background)
            if self._overflow and bounds:
                first = self.canvas.canvasy(0)
                last = first + self.canvas.winfo_height()
                if bounds[1] < first:
                    self.canvas.yview_moveto(bounds[1] / self.scroll_y)
                elif bounds[3] > last:
                    self.canvas.yview_moveto(
                        (bounds[3] - self.canvas.winfo_height()) / self.scroll_y
                    )

    def clear_selected(self):
        self._current_icon = None
        self.apply_palette(self._palette)
