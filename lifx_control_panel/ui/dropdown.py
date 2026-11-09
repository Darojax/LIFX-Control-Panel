"""Compact, themed choices with native keyboard and popup behavior."""

from collections.abc import Mapping
import tkinter as tk
from tkinter import font, ttk

from .theme import THEME_PALETTES, resolve_theme_mode

try:
    import win32api
except ImportError:  # pragma: no cover - non-Windows installations
    win32api = None


def _work_area(widget):
    """Use the owner's monitor, including negative desktop coordinates."""
    if win32api is not None:
        try:
            monitor = win32api.MonitorFromWindow(widget.winfo_id(), 2)
            return win32api.GetMonitorInfo(monitor)["Work"]
        except (win32api.error, tk.TclError):
            pass
    left, top = widget.winfo_vrootx(), widget.winfo_vrooty()
    return left, top, left + widget.winfo_vrootwidth(), top + widget.winfo_vrootheight()


def _current_palette(widget):
    return (
        getattr(widget._root(), "_lifx_palette", None)
        or THEME_PALETTES[resolve_theme_mode("system")]
    )


class ChoiceDropdown(ttk.Combobox):
    """Display friendly labels while preserving the caller's stored values.

    Tk's combobox owns focus, selection, scrolling, and dismissal.  Only its
    presentation is customized, including room for long labels in the popup
    without widening the main window.
    """

    def __init__(self, master, variable, choices, *, placeholder="", width=24):
        self.variable = variable
        self.placeholder = placeholder
        self._display = tk.StringVar(master)
        self._choices = ()
        self._palette = _current_palette(master)
        self._choice_style = "Dropdown.TCombobox"
        super().__init__(
            master,
            textvariable=self._display,
            state="readonly",
            width=width,
            height=10,
            font="TkDefaultFont",
            exportselection=False,
            style=self._choice_style,
            postcommand=self._prepare_popup,
        )
        self._value_trace = variable.trace_add("write", self._sync_display)
        self.bind("<<ComboboxSelected>>", self._selected)
        self.bind("<Destroy>", self._dispose, add="+")
        # A wheel over a closed preset control must never change the lamp.
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(sequence, lambda event: "break")
        for sequence in ("<space>", "<Return>", "<F4>"):
            self.bind(sequence, self._toggle_popup)
        self.set_choices(choices)

    def set_choices(self, choices):
        """Refresh choices without selecting a value or firing its action."""
        if self.instate(["pressed"]):
            self.tk.call("ttk::combobox::Unpost", self._w)
        items = (
            choices.items()
            if isinstance(choices, Mapping)
            else ((value, value) for value in choices)
        )
        self._choices = tuple((str(value), str(label)) for value, label in items)
        self.configure(values=[label for _, label in self._choices])
        self.state(["!disabled", "readonly"] if self._choices else ["disabled"])
        self._sync_display()

    def _sync_display(self, *_):
        value = self.variable.get()
        label = next(
            (label for choice, label in self._choices if choice == value),
            self.placeholder or value,
        )
        self._display.set(label)

    def _selected(self, _=None):
        index = self.current()
        if 0 <= index < len(self._choices):
            # Write even when reselecting the same preset so it can be reapplied.
            self.variable.set(self._choices[index][0])
        self.selection_clear()

    def _toggle_popup(self, _=None):
        if not self.instate(["disabled"]):
            action = "Unpost" if self.instate(["pressed"]) else "Post"
            self.tk.call(f"ttk::combobox::{action}", self._w)
        return "break"

    def apply_palette(self, palette):
        """Update an already-created popup as well as future openings."""
        self._palette = palette
        popup = f"{self._w}.popdown"
        if self.tk.call("winfo", "exists", popup):
            self._style_popup(popup)

    def _style_popup(self, popup):
        palette = self._palette
        inset = max(2, round(4 * self.winfo_fpixels("1i") / 96))
        # These are Tk's own popup children, not separate Python widgets.
        self.tk.call(
            f"{popup}.f.l",
            "configure",
            "-background",
            palette["field"],
            "-foreground",
            palette["foreground"],
            "-selectbackground",
            palette["selection"],
            "-selectforeground",
            palette["selection_fg"],
            "-font",
            "TkDefaultFont",
            "-relief",
            "flat",
            "-borderwidth",
            inset,
            "-highlightthickness",
            0,
            "-selectborderwidth",
            inset,
            "-activestyle",
            "none",
        )

    def _prepare_popup(self):
        popup = self.tk.call("ttk::combobox::PopdownWindow", self._w)
        self._style_popup(popup)
        text = font.nametofont("TkDefaultFont", root=self)
        scale = self.winfo_fpixels("1i") / 96
        screen_left, screen_top, screen_right, screen_bottom = _work_area(self)
        row_height = text.metrics("linespace") + 2 * round(4 * scale)
        rows = min(10, max(1, (screen_bottom - screen_top - 32) // row_height))
        self.configure(height=rows)
        self.tk.call("ttk::combobox::ConfigureListbox", self._w)
        self.update_idletasks()
        popup_height = int(self.tk.call("winfo", "reqheight", popup))
        # Allow a scrollbar and comfortable text insets, only in the popup.
        extra = round((40 if len(self._choices) > rows else 24) * scale)
        needed = (
            max((text.measure(label) for _, label in self._choices), default=0) + extra
        )
        width = min(max(self.winfo_width(), needed), screen_right - screen_left - 16)
        left = min(self.winfo_rootx(), screen_right - width - 8)
        left = max(screen_left + 8, left)
        top = self.winfo_rooty() + self.winfo_height() + 2
        if top + popup_height > screen_bottom - 8:
            top = self.winfo_rooty() - popup_height - 2
        top = max(screen_top + 8, top)
        # Tk 8.6 chooses above/below using the primary screen's height. Account
        # for that choice when the owner is on a differently positioned monitor.
        if top + popup_height > self.winfo_screenheight():
            y_offset = top + popup_height - self.winfo_rooty()
        else:
            y_offset = top - self.winfo_rooty() - self.winfo_height()
        ttk.Style(self).configure(
            self._choice_style,
            # Tk reads this only when positioning the next popup. Sharing the
            # style avoids retaining one new style for every rescan or dialog.
            postoffset=(
                left - self.winfo_rootx(),
                y_offset,
                width - self.winfo_width(),
                0,
            ),
        )

    def _dispose(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self._value_trace)


class MenuPopup(tk.Toplevel):
    """A themed command menu that fits independently of its owner's window."""

    def __init__(self, master, anchor, *, mnemonic=None):
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(master.winfo_toplevel())
        self.anchor = anchor
        self.is_open = False
        self._items = []
        self._callbacks = []
        self._separators = []
        self._selected = -1
        self._focus_before = None
        self._grab_before = None
        self._grab_status_before = None
        self._focus_job = None
        self._palette = _current_palette(master)
        self._bindings = []
        self.bind("<Escape>", self._cancel)
        self.bind("<Up>", lambda event: self._move(-1))
        self.bind("<Down>", lambda event: self._move(1))
        self.bind("<Home>", lambda event: self._select_key(0))
        self.bind("<End>", lambda event: self._select_key(len(self._items) - 1))
        self.bind("<Return>", self._invoke_selected)
        self.bind("<space>", self._invoke_selected)
        self.bind("<Tab>", lambda event: self._traverse(False))
        self.bind("<Shift-Tab>", lambda event: self._traverse(True))
        self.bind("<Button-1>", self._outside_click, add="+")
        self.bind("<FocusOut>", self._defer_focus_check, add="+")
        self.bind("<Destroy>", self._dispose, add="+")
        root = master.winfo_toplevel()
        self._bind_owner(root, "<Configure>", self._owner_configured)
        self._bind_owner(root, "<Unmap>", self._owner_unmapped)
        self._bind_owner(anchor, "<Down>", self._open_from_key)
        if mnemonic:
            self._bind_owner(root, f"<Alt-{mnemonic}>", self._open_from_key)

    def _bind_owner(self, widget, sequence, callback):
        binding = widget.bind(sequence, callback, add="+")
        self._bindings.append((widget, sequence, binding))

    def add_command(self, label, command):
        index = len(self._items)
        button = tk.Button(
            self,
            text=label,
            anchor="w",
            font="TkMenuFont",
            command=lambda: self._invoke(index),
            takefocus=False,
        )
        button.pack(fill="x", padx=4, pady=1)
        button.bind("<Enter>", lambda event: self._select(index))
        for sequence in ("<Return>", "<space>"):
            button.bind(sequence, self._invoke_selected)
        self._items.append(button)
        self._callbacks.append(command)
        self.apply_palette(self._palette)
        return button

    def add_separator(self):
        separator = tk.Frame(self, height=1, borderwidth=0)
        separator.pack(fill="x", padx=10, pady=5)
        self._separators.append(separator)
        self.apply_palette(self._palette)
        return separator

    def apply_palette(self, palette):
        self._palette = palette
        scale = self.winfo_fpixels("1i") / 96
        self.configure(
            background=palette["field"],
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=palette["border"],
            highlightcolor=palette["border"],
            padx=0,
            pady=round(4 * scale),
        )
        for index, button in enumerate(self._items):
            selected = self.is_open and index == self._selected
            button.configure(
                background=palette["selection"] if selected else palette["field"],
                foreground=(
                    palette["selection_fg"] if selected else palette["foreground"]
                ),
                activebackground=palette["selection"],
                activeforeground=palette["selection_fg"],
                disabledforeground=palette["disabled"],
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                padx=round(12 * scale),
                pady=round(6 * scale),
            )
            button.pack_configure(padx=round(4 * scale), pady=max(1, round(scale)))
        for separator in self._separators:
            separator.configure(background=palette["border"])

    def show(self):
        if self.is_open or not self._items or not self.anchor.winfo_viewable():
            return
        self._focus_before = self.focus_get() or self.anchor
        self._grab_before = self.grab_current()
        self._grab_status_before = (
            self._grab_before.grab_status() if self._grab_before is not None else None
        )
        self.update_idletasks()
        self._position()
        self.is_open = True
        self.anchor.state(["selected"])
        self.deiconify()
        self.lift()
        self._select(0)
        self.grab_set()

    def hide(self, *, restore_focus=True):
        if self._focus_job is not None:
            self.after_cancel(self._focus_job)
            self._focus_job = None
        if not self.is_open:
            return
        self.is_open = False
        if self.grab_current() is self:
            self.grab_release()
            if self._grab_before is not None and self._grab_before.winfo_exists():
                if self._grab_status_before == "global":
                    self._grab_before.grab_set_global()
                else:
                    self._grab_before.grab_set()
        self.withdraw()
        self.anchor.state(["!selected"])
        if restore_focus and self._focus_before is not None:
            try:
                if self._focus_before.winfo_viewable():
                    self._focus_before.focus_set()
            except tk.TclError:
                pass
        self._focus_before = self._grab_before = None
        self._grab_status_before = None

    def _position(self):
        margin = 8
        screen_left, screen_top, screen_right, screen_bottom = _work_area(self.anchor)
        width = min(
            max(self.winfo_reqwidth(), self.anchor.winfo_width()),
            screen_right - screen_left - 2 * margin,
        )
        height = self.winfo_reqheight()
        left = min(self.anchor.winfo_rootx(), screen_right - width - margin)
        left = max(screen_left + margin, left)
        top = self.anchor.winfo_rooty() + self.anchor.winfo_height() + 2
        if top + height > screen_bottom - margin:
            top = self.anchor.winfo_rooty() - height - 2
        top = max(screen_top + margin, top)
        self.geometry(f"{width}x{height}+{left}+{top}")

    def _select(self, index):
        if self.is_open and self._items:
            self._selected = index % len(self._items)
            self.apply_palette(self._palette)
            self._items[self._selected].focus_set()

    def _select_key(self, index):
        self._select(index)
        return "break"

    def _move(self, offset):
        return self._select_key(self._selected + offset)

    def _invoke(self, index):
        self.hide()
        # Release the popup grab before opening a dialog or running its action.
        self._callbacks[index]()

    def _invoke_selected(self, _=None):
        if 0 <= self._selected < len(self._items):
            self._invoke(self._selected)
        return "break"

    def _cancel(self, _=None):
        self.hide()
        return "break"

    def _open_from_key(self, _=None):
        self.show()
        return "break"

    def _traverse(self, backwards):
        self.hide(restore_focus=False)
        target = self.anchor.tk_focusPrev() if backwards else self.anchor.tk_focusNext()
        if target is not None:
            target.focus_set()
        return "break"

    def _outside_click(self, event):
        inside = (
            self.winfo_rootx() <= event.x_root < self.winfo_rootx() + self.winfo_width()
            and self.winfo_rooty()
            <= event.y_root
            < self.winfo_rooty() + self.winfo_height()
        )
        if self.is_open and not inside:
            self.hide(restore_focus=False)
            return "break"
        return None

    def _defer_focus_check(self, _=None):
        if self.is_open and self._focus_job is None:
            self._focus_job = self.after_idle(self._check_focus)

    def _check_focus(self):
        self._focus_job = None
        focused = self.focus_get()
        if self.is_open and (focused is None or focused.winfo_toplevel() is not self):
            self.hide(restore_focus=False)

    def _owner_configured(self, event):
        if self.is_open and event.widget is self.master.winfo_toplevel():
            self._position()

    def _owner_unmapped(self, event):
        if event.widget is self.master.winfo_toplevel():
            self.hide(restore_focus=False)

    def _dispose(self, event):
        if event.widget is not self:
            return
        self.is_open = False
        try:
            self.anchor.state(["!selected"])
        except tk.TclError:
            pass
        if self._focus_job is not None:
            self.after_cancel(self._focus_job)
            self._focus_job = None
        for widget, sequence, binding in self._bindings:
            try:
                widget.unbind(sequence, binding)
            except tk.TclError:
                pass
        self._bindings.clear()
