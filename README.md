# LIFX Control Panel (Fork)

Maintained fork of the original project:
- Upstream: https://github.com/samclane/LIFX-Control-Panel
- This fork: https://github.com/Darojax/LIFX-Control-Panel

Upstream maintainer note:
- Development of the original project is being continued in Mantle: https://github.com/samclane/mantle
- This fork maintains and improves the classic LIFX Control Panel codebase.

This fork continues development of the classic Tkinter-based LIFX Control Panel app and includes recent fixes for:
- Windows theme support (light, dark, system)
- startup and dialog stability
- modern PyInstaller 6 build compatibility

# Support

Use this fork's issue tracker for bugs and feature requests:
- https://github.com/Darojax/LIFX-Control-Panel/issues

# Features

- Average Screen Color
- Color Eyedropper
- Custom color palette
- Keybindings

# Quick Start

1. Clone this repository.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Run the app.

```powershell
cd C:\path\to\LIFX-Control-Panel
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m lifx_control_panel
```

Note:
- `lifxlan` requires `bitstring<4` and this repository pins that.
- If `pyaudio` installation fails on Windows, use:

```powershell
python -m pip install pipwin
pipwin install pyaudio
```

# Build Executables (Windows)

This repository builds Windows executables with PyInstaller using `lifx_control_panel/build_all.spec`.

```powershell
cd C:\path\to\LIFX-Control-Panel
.\.venv\Scripts\Activate.ps1
python -m pip install pyinstaller
.\build_all.bat
```

Build outputs are written to:
- `lifx_control_panel/dist/lifx_control_panel.exe`
- `lifx_control_panel/dist/lifx_control_panel-debug.exe`
- `lifx_control_panel/dist/lifx_control_panel-demo.exe`

# Attribution

Original project by Sawyer McLane and contributors.

This project also uses a fork of `lifxlan`:
- https://github.com/samclane/lifxlan

# License

MIT License. See `LICENSE.txt`.
