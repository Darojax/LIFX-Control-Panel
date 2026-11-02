"""Windows startup registration and display scaling."""

import ctypes
import os
from pathlib import Path
import sys

STARTUP_NAME = "LIFX-Control-Panel.lnk"


def startup_path():
    return (
        Path(os.environ["APPDATA"])
        / "Microsoft/Windows/Start Menu/Programs/Startup"
        / STARTUP_NAME
    )


def get_launch_on_startup():
    return sys.platform == "win32" and startup_path().exists()


def set_launch_on_startup(enabled):
    path = startup_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    import pythoncom
    from win32com.shell import shell

    pythoncom.CoInitialize()
    try:
        link = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink,
            None,
            pythoncom.CLSCTX_INPROC_SERVER,
            shell.IID_IShellLink,
        )
        if getattr(sys, "frozen", False):
            target, arguments, directory = (
                sys.executable,
                "",
                Path(sys.executable).parent,
            )
        else:
            executable = Path(sys.executable)
            target = str(executable.with_name("pythonw.exe"))
            arguments, directory = (
                "-m lifx_control_panel",
                Path(__file__).resolve().parents[2],
            )
        link.SetPath(target)
        link.SetArguments(arguments)
        link.SetWorkingDirectory(str(directory))
        path.parent.mkdir(parents=True, exist_ok=True)
        link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 0)
    finally:
        pythoncom.CoUninitialize()


def configure_dpi():
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
