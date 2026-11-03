"""Theme utilities for light, dark, and Windows-default rendering."""

import ctypes
import sys
import tkinter
from tkinter import ttk, font

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore


THEME_LABEL_TO_VALUE = {
    "Default (Windows)": "system",
    "Light": "light",
    "Dark": "dark",
}
THEME_VALUE_TO_LABEL = {value: label for label, value in THEME_LABEL_TO_VALUE.items()}


THEME_PALETTES = {
    "dark": {
        "background": "#151b25",
        "foreground": "#eef2f6",
        "button": "#263244",
        "button_active": "#33435a",
        "field": "#1d2735",
        "selection": "#2f6db4",
        "selection_fg": "#ffffff",
        "disabled": "#8a95a5",
        "border": "#2f3848",
        "accent": "#6aa7ff",
        "menu_bg": "#171d27",
        "menu_fg": "#eef2f6",
    },
    "light": {
        "background": "#f4f6fa",
        "foreground": "#172333",
        "button": "#ffffff",
        "button_active": "#e8eef8",
        "field": "#ffffff",
        "selection": "#2f5f9f",
        "selection_fg": "#ffffff",
        "disabled": "#7a7a7a",
        "border": "#d2dbe8",
        "accent": "#2f5f9f",
        "menu_bg": "#f6f6f6",
        "menu_fg": "#202020",
    },
}


def normalize_theme_preference(value: str) -> str:
    """Normalize a user preference value to one of dark/light/system."""
    theme = str(value or "").strip().lower()
    if theme in ("dark", "light", "system"):
        return theme
    if theme in ("default", "windows"):
        return "system"
    return "system"


def theme_label_from_value(value: str) -> str:
    """Map stored theme value to user-facing label."""
    return THEME_VALUE_TO_LABEL[normalize_theme_preference(value)]


def theme_value_from_label(label: str) -> str:
    """Map user-facing label to stored theme value."""
    return THEME_LABEL_TO_VALUE.get(label, "system")


def detect_windows_theme() -> str:
    """Return dark/light based on Windows app theme preference."""
    if winreg is None:
        return "light"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) else "dark"
    except OSError:
        return "light"


def resolve_theme_mode(preference: str) -> str:
    """Resolve system/default mode to a concrete light or dark mode."""
    mode = normalize_theme_preference(preference)
    if mode == "system":
        return detect_windows_theme()
    return mode


def apply_theme(root: tkinter.Misc, preference: str) -> str:
    """Apply theme preference to tkinter and ttk widgets."""
    resolved_mode = resolve_theme_mode(preference)
    palette = THEME_PALETTES[resolved_mode]

    _apply_palette_defaults(root, palette)
    _apply_ttk_style(root, palette)
    _style_widget_tree(root, palette)

    menu_name = root.cget("menu")
    if menu_name:
        try:
            root_menu = root.nametowidget(menu_name)
            _style_menu(root_menu, palette)
        except tkinter.TclError:
            pass

    _apply_windows_theme_chrome(root, resolved_mode == "dark")

    return resolved_mode


def apply_window_chrome(window: tkinter.Misc, preference: str) -> str:
    """Apply only native window chrome/title theming for a given window."""
    resolved_mode = resolve_theme_mode(preference)
    _apply_windows_titlebar_theme(window, resolved_mode == "dark")
    return resolved_mode


def _apply_palette_defaults(root: tkinter.Tk, palette: dict) -> None:
    _safe_config(root, bg=palette["background"])
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        font.nametofont(name, root=root).configure(family="Segoe UI", size=9)
    font.nametofont("TkHeadingFont", root=root).configure(
        family="Segoe UI", size=10, weight="bold"
    )

    root.option_add("*Background", palette["background"])
    root.option_add("*Foreground", palette["foreground"])
    root.option_add("*activeBackground", palette["button_active"])
    root.option_add("*activeForeground", palette["foreground"])
    root.option_add("*highlightBackground", palette["background"])
    root.option_add("*highlightColor", palette["accent"])
    root.option_add("*selectBackground", palette["selection"])
    root.option_add("*selectForeground", palette["selection_fg"])
    root.option_add("*Button.background", palette["button"])
    root.option_add("*Button.foreground", palette["foreground"])
    root.option_add("*Checkbutton.background", palette["background"])
    root.option_add("*Checkbutton.foreground", palette["foreground"])
    root.option_add("*Radiobutton.background", palette["background"])
    root.option_add("*Radiobutton.foreground", palette["foreground"])
    root.option_add("*Scale.background", palette["background"])
    root.option_add("*Scale.foreground", palette["foreground"])
    root.option_add("*Scale.troughColor", palette["field"])
    root.option_add("*Label.background", palette["background"])
    root.option_add("*Label.foreground", palette["foreground"])
    root.option_add("*Frame.background", palette["background"])
    root.option_add("*LabelFrame.background", palette["background"])
    root.option_add("*LabelFrame.foreground", palette["foreground"])
    root.option_add("*Menu.background", palette["menu_bg"])
    root.option_add("*Menu.foreground", palette["menu_fg"])
    root.option_add("*Menu.activeBackground", palette["selection"])
    root.option_add("*Menu.activeForeground", palette["selection_fg"])
    root.option_add("*OptionMenu.background", palette["button"])
    root.option_add("*OptionMenu.foreground", palette["foreground"])
    root.option_add("*Entry.background", palette["field"])
    root.option_add("*Entry.foreground", palette["foreground"])
    root.option_add("*Entry.insertBackground", palette["foreground"])
    root.option_add("*Listbox.background", palette["field"])
    root.option_add("*Listbox.foreground", palette["foreground"])
    root.option_add("*Listbox.selectBackground", palette["selection"])
    root.option_add("*Listbox.selectForeground", palette["selection_fg"])
    root.option_add("*Scrollbar.background", palette["button"])
    root.option_add("*Scrollbar.activeBackground", palette["button_active"])
    root.option_add("*Scrollbar.troughColor", palette["field"])


def _apply_ttk_style(root: tkinter.Tk, palette: dict) -> None:
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(
        ".", background=palette["background"], foreground=palette["foreground"]
    )
    style.configure("TFrame", background=palette["background"])
    style.configure(
        "TLabel", background=palette["background"], foreground=palette["foreground"]
    )
    style.configure(
        "Section.TLabel", font="TkHeadingFont", foreground=palette["foreground"]
    )
    style.configure("TNotebook", background=palette["background"], borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        padding=(12, 7),
        background=palette["button"],
        foreground=palette["foreground"],
    )
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", palette["field"]),
            ("active", palette["button_active"]),
        ],
        foreground=[("selected", palette["accent"])],
    )
    style.configure(
        "TLabelframe",
        background=palette["background"],
        bordercolor=palette["border"],
        relief="solid",
        borderwidth=1,
        lightcolor=palette["border"],
        darkcolor=palette["border"],
    )
    style.configure(
        "TLabelframe.Label",
        background=palette["background"],
        foreground=palette["foreground"],
        font="TkHeadingFont",
    )
    style.configure(
        "TButton",
        background=palette["button"],
        foreground=palette["foreground"],
        bordercolor=palette["border"],
    )
    style.map(
        "TButton",
        background=[
            ("pressed", palette["selection"]),
            ("active", palette["button_active"]),
        ],
        foreground=[
            ("disabled", palette["disabled"]),
            ("pressed", palette["selection_fg"]),
        ],
    )
    style.configure(
        "TMenubutton", background=palette["button"], foreground=palette["foreground"]
    )
    style.map("TMenubutton", background=[("active", palette["button_active"])])
    style.configure(
        "TEntry",
        fieldbackground=palette["field"],
        foreground=palette["foreground"],
        bordercolor=palette["border"],
    )
    style.configure(
        "TCombobox",
        fieldbackground=palette["field"],
        foreground=palette["foreground"],
        background=palette["button"],
        bordercolor=palette["border"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette["field"])],
        selectbackground=[("readonly", palette["selection"])],
        selectforeground=[("readonly", palette["selection_fg"])],
    )
    style.configure("TSeparator", background=palette["border"])
    style.configure(
        "Horizontal.TScrollbar",
        background=palette["button"],
        troughcolor=palette["field"],
        bordercolor=palette["border"],
        arrowcolor=palette["foreground"],
        darkcolor=palette["button"],
        lightcolor=palette["button"],
        gripcount=0,
        relief="flat",
        borderwidth=0,
    )
    style.configure(
        "Vertical.TScrollbar",
        background=palette["button"],
        troughcolor=palette["field"],
        bordercolor=palette["border"],
        arrowcolor=palette["foreground"],
        darkcolor=palette["button"],
        lightcolor=palette["button"],
        gripcount=0,
        relief="flat",
        borderwidth=0,
    )
    style.map(
        "Horizontal.TScrollbar",
        background=[
            ("active", palette["button_active"]),
            ("pressed", palette["selection"]),
        ],
        darkcolor=[("active", palette["button_active"])],
        lightcolor=[("active", palette["button_active"])],
    )
    style.map(
        "Vertical.TScrollbar",
        background=[
            ("active", palette["button_active"]),
            ("pressed", palette["selection"]),
        ],
        darkcolor=[("active", palette["button_active"])],
        lightcolor=[("active", palette["button_active"])],
    )


def _style_widget_tree(widget: tkinter.Misc, palette: dict) -> None:
    if isinstance(widget, tkinter.OptionMenu):
        _safe_config(
            widget,
            bg=palette["button"],
            fg=palette["foreground"],
            activebackground=palette["button_active"],
            activeforeground=palette["foreground"],
            highlightbackground=palette["background"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
        )
        try:
            menu = widget.nametowidget(widget["menu"])
            _style_menu(menu, palette)
        except tkinter.TclError:
            pass
    elif isinstance(widget, tkinter.Menubutton):
        _safe_config(
            widget,
            bg=palette["button"],
            fg=palette["foreground"],
            activebackground=palette["button_active"],
            activeforeground=palette["foreground"],
            highlightbackground=palette["background"],
        )
    elif isinstance(
        widget, (tkinter.Tk, tkinter.Toplevel, tkinter.Frame, tkinter.LabelFrame)
    ):
        _safe_config(
            widget,
            bg=palette["background"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Label):
        _safe_config(
            widget,
            bg=palette["background"],
            fg=palette["foreground"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Button):
        _safe_config(
            widget,
            bg=palette["button"],
            fg=palette["foreground"],
            activebackground=palette["button_active"],
            activeforeground=palette["foreground"],
            highlightbackground=palette["border"],
            highlightcolor=palette["accent"],
            highlightthickness=1,
            relief="flat",
            borderwidth=0,
            padx=9,
            pady=3,
            disabledforeground=palette["disabled"],
        )
    elif isinstance(widget, tkinter.Entry):
        _safe_config(
            widget,
            bg=palette["field"],
            fg=palette["foreground"],
            insertbackground=palette["foreground"],
            selectbackground=palette["selection"],
            selectforeground=palette["selection_fg"],
            readonlybackground=palette["field"],
            disabledforeground=palette["disabled"],
            highlightbackground=palette["border"],
            highlightcolor=palette["accent"],
            highlightthickness=1,
            relief="flat",
            borderwidth=0,
        )
    elif isinstance(widget, tkinter.Listbox):
        _safe_config(
            widget,
            bg=palette["field"],
            fg=palette["foreground"],
            selectbackground=palette["selection"],
            selectforeground=palette["selection_fg"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Text):
        _safe_config(
            widget,
            bg=palette["field"],
            fg=palette["foreground"],
            insertbackground=palette["foreground"],
            selectbackground=palette["selection"],
            selectforeground=palette["selection_fg"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Radiobutton):
        _safe_config(
            widget,
            bg=palette["background"],
            fg=palette["foreground"],
            activebackground=palette["background"],
            activeforeground=palette["foreground"],
            selectcolor=palette["field"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Checkbutton):
        _safe_config(
            widget,
            bg=palette["background"],
            fg=palette["foreground"],
            activebackground=palette["background"],
            activeforeground=palette["foreground"],
            selectcolor=palette["field"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Scale):
        _safe_config(
            widget,
            bg=palette["background"],
            fg=palette["foreground"],
            activebackground=palette["button_active"],
            troughcolor=palette["field"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Scrollbar):
        _safe_config(
            widget,
            bg=palette["button"],
            activebackground=palette["button_active"],
            troughcolor=palette["field"],
            highlightbackground=palette["background"],
        )
    elif isinstance(widget, tkinter.Canvas):
        _style_canvas(widget, palette)
    elif isinstance(widget, tkinter.Menu):
        _style_menu(widget, palette)

    for child in widget.winfo_children():
        _style_widget_tree(child, palette)


def _style_menu(menu: tkinter.Menu, palette: dict) -> None:
    _safe_config(
        menu,
        bg=palette["menu_bg"],
        fg=palette["menu_fg"],
        activebackground=palette["selection"],
        activeforeground=palette["selection_fg"],
        relief=tkinter.FLAT,
        borderwidth=0,
        activeborderwidth=0,
        highlightthickness=0,
        highlightbackground=palette["menu_bg"],
        highlightcolor=palette["menu_bg"],
    )
    end = menu.index("end")
    if end is None:
        return

    for index in range(end + 1):
        try:
            menu.entryconfig(
                index,
                background=palette["menu_bg"],
                foreground=palette["menu_fg"],
                activebackground=palette["selection"],
                activeforeground=palette["selection_fg"],
            )
        except tkinter.TclError:
            pass

        try:
            if menu.type(index) == "cascade":
                child_name = menu.entrycget(index, "menu")
                if child_name:
                    _style_menu(menu.nametowidget(child_name), palette)
        except tkinter.TclError:
            pass


def _style_canvas(canvas: tkinter.Canvas, palette: dict) -> None:
    _safe_config(canvas, highlightbackground=palette["background"])

    # Keep tiny color-preview canvases and gradients untouched.
    if _is_color_preview_canvas(canvas):
        return

    _safe_config(canvas, bg=palette["field"])
    for item_id in canvas.find_all():
        if canvas.type(item_id) == "text":
            _safe_config_canvas_item(canvas, item_id, fill=palette["foreground"])
    if hasattr(canvas.master, "apply_palette"):
        canvas.master.apply_palette(palette)


def _is_color_preview_canvas(canvas: tkinter.Canvas) -> bool:
    requested_w = int(canvas.cget("width"))
    requested_h = int(canvas.cget("height"))
    return requested_w <= 120 and requested_h <= 24


def _safe_config_canvas_item(canvas: tkinter.Canvas, item_id: int, **kwargs) -> None:
    try:
        canvas.itemconfigure(item_id, **kwargs)
    except tkinter.TclError:
        pass


def _safe_config(widget: tkinter.Misc, **kwargs) -> None:
    for key, value in kwargs.items():
        try:
            widget.configure(**{key: value})
        except tkinter.TclError:
            pass


def _apply_windows_titlebar_theme(root: tkinter.Misc, use_dark: bool) -> None:
    """Set native Windows title-bar dark mode when available."""
    if sys.platform != "win32":
        return
    try:
        root.update_idletasks()
        user32 = ctypes.windll.user32
        raw_hwnd = int(root.winfo_id())
        window_handles = {raw_hwnd}

        parent_hwnd = int(user32.GetParent(raw_hwnd) or 0)
        if parent_hwnd:
            window_handles.add(parent_hwnd)

        get_ancestor = getattr(user32, "GetAncestor", None)
        if get_ancestor is not None:
            # GA_ROOT=2, GA_ROOTOWNER=3
            for flag in (2, 3):
                ancestor_hwnd = int(get_ancestor(raw_hwnd, flag) or 0)
                if ancestor_hwnd:
                    window_handles.add(ancestor_hwnd)

        value = ctypes.c_int(1 if use_dark else 0)
        attrs = (20, 19)  # Win10 2004+ and older builds
        dwmapi = ctypes.windll.dwmapi
        for window_hwnd in window_handles:
            hwnd = ctypes.c_void_p(window_hwnd)
            for attr in attrs:
                dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    ctypes.c_uint(attr),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )

            # Force explicit caption/text/border colors where supported.
            if use_dark:
                caption = ctypes.c_uint(0x001C1612)  # COLORREF BGR
                text = ctypes.c_uint(0x00FFFFFF)
                border = ctypes.c_uint(0x0048382F)
            else:
                caption = ctypes.c_uint(0xFFFFFFFF)  # reset to default
                text = ctypes.c_uint(0xFFFFFFFF)
                border = ctypes.c_uint(0xFFFFFFFF)

            for attr, color in ((35, caption), (36, text), (34, border)):
                dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    ctypes.c_uint(attr),
                    ctypes.byref(color),
                    ctypes.sizeof(color),
                )

            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
    except Exception:
        pass


def _apply_windows_theme_chrome(root: tkinter.Misc, use_dark: bool) -> None:
    """Apply Windows title-bar theming to root and all open toplevel windows."""
    visited = set()
    stack = [root]
    while stack:
        widget = stack.pop()
        if str(widget) in visited:
            continue
        visited.add(str(widget))
        if isinstance(widget, (tkinter.Tk, tkinter.Toplevel)):
            _apply_windows_titlebar_theme(widget, use_dark)
        stack.extend(widget.winfo_children())
