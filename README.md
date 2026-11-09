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

- Average and Dominant Screen Color
- Cinema Sync movie lighting for a single room lamp
- Optional Music Color audio response
- Color Eyedropper
- Custom colour palettes and numeric colour entry
- Keyboard shortcuts and tray power controls
- Saved light states and optional startup restoration
- Multizone colour painting and zone-state restoration

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

`lifxlan` requires `bitstring<4`, which this repository pins. Music Color is
optional; install PyAudio to enable it:

```powershell
python -m pip install PyAudio
```

The other lighting controls work without PyAudio.

# Build Executables (Windows)

This repository builds Windows executables with PyInstaller using `lifx_control_panel/build_all.spec`.

```powershell
cd C:\path\to\LIFX-Control-Panel
.\.venv\Scripts\Activate.ps1
python -m pip install "pyinstaller>=6.19,<7"
.\build_all.bat
```

Build outputs are written to:
- `lifx_control_panel/dist/lifx_control_panel.exe`
- `lifx_control_panel/dist/lifx_control_panel-debug.exe`
- `lifx_control_panel/dist/lifx_control_panel-demo.exe`

Rebuilds replace these files in the same folder. Close the running app before rebuilding.
The demo uses simulated lights and does not discover or control real devices.

The executable stores `config.ini` beside the executable. If no portable
configuration exists yet, settings in the launch directory are used as a legacy fallback.

File logging is **off by default**. **Settings > General > Save diagnostic logs**
enables it when troubleshooting. Diagnostic files stay beside the executable,
rotate at 1 MiB, and retain only one backup (2 MiB total). Individual records are
bounded too, and enabling diagnostics applies the limit to oversized older logs.
Press **OK** to apply; disabling stops file writes without a restart.
Debug-console output does not require file logging.

The interface keeps the original compact window width. **Lights** and **Groups**
tabs above the controls provide live colour indicators and wrapped device names.
Lists show a scrollbar only when their content overflows. The window can be
resized vertically, and its eight action buttons form an equal two-column grid.
Screen colour buttons use the compact labels **Avg. Screen Color** and
**Dominant Screen**. **Screen region...** expands the capture coordinates when needed.

**Settings** is available directly in the toolbar and groups controls into
**General**, **Screen**, **Cinema Sync**, **Shortcuts**, and **Presets & audio** tabs.
The Settings window adjusts its height to the selected tab to avoid empty space.
Both light and dark themes use the same compact layout and visible active/focus states.

Click **Settings** in the toolbar or File menu to open it, and click either
Settings command again to close it. The main controls stay usable while Settings
is open. Closing this way acts like **Cancel**, including restoring unsaved Cinema
Sync slider previews; **OK** saves changes.
Lighting keyboard shortcuts pause while Settings is open and resume when it closes.

Preset and Settings dropdowns share themed fields, clear arrows, and readable
selection states. Long names expand the popup without widening the main window;
long lists show a scrollbar, while short lists fit their content. Scrolling over
a closed dropdown does not change its selection or the lamp. Display choices use
readable names and dimensions while preserving saved capture coordinates.

The **File** menu uses a bordered popup with spaced, grouped commands. Open it
with **Alt+F** or focus **File** and press **Down**; use arrow keys and **Enter** to
choose a command. **Escape**, clicking outside, or switching away dismisses it.
Popups stay within the working area of the display containing their control.

Effects are exclusive for overlapping lights: selecting an effect for a group also
stops effects on its individual lights. Manual colour changes and shortcuts stop
effects on the affected lights. Unrelated lights can run their own effects.

Starting Cinema Sync, Avg. Screen Color, Dominant Screen, Music Color, or Color
Cycle remembers each affected light's original colour, brightness, Kelvin, power,
and strip zones before the effect sends its first colour. Switching between
effects keeps that same original. **Stop effects** restores it, including each
group member's individual state. Switching from a group to a member restores the
other members that are no longer running an effect.

Manual colour and power commands supersede effects and become the starting state
for the next effect. Rapid starts, stops, and manual changes cancel stale work so
an older restore cannot overwrite a newer choice. This memory lasts for the
current app session; **File > Save current state** provides a separate saved state
for later launches.
If restoration fails because a light is unreachable, reconnect it and press
**Stop effects** again to retry its remembered state. Closing the app clears this
temporary memory.

Slider drags send the newest colour at most once every 50 ms, including the final
value after release. Choosing a preset, power control, or effect cancels pending
slider updates on the affected lights.

**Cinema Sync** adds dynamic movie lighting for a single room lamp. It blends
supported illuminated colours according to their strength, keeping saturated
colours vivid instead of averaging them to grey. Pans and gradual reveals move
progressively between colours without waiting for a new dominant colour to win.
Fast colour response follows sudden changes on screen; ordinary transitions stay
smooth. Scene exposure plus highlight area set brightness. Bright flashes rise
quickly and then decay. Neutral scenes can still produce white light.
Small, sustained highlights contribute modestly so
headlights in a dark scene do not keep the whole room brightly lit. Sudden increases
in light and strong colour changes receive a brief extra boost; repeated flashes
can retrigger it. Moving an otherwise steady light across the picture does not
retrigger that boost. Broadly bright scenes retain their sustained brightness.
Paired black bars and thin, white subtitle-shaped regions are discounted
conservatively; these pixel heuristics do not recognize
objects or guarantee that every subtitle is excluded.

Select your movie display in **Screen Region**, turn on the room lamp, and click
**Cinema Sync**. It replaces any other effect on that lamp. Settings offers:

- **Impact (%)**, default 80, adjusts how strongly highlights raise room brightness
  and slightly changes the weighting of illuminated colours.
- **Response (%)**, default 90, adjusts attack speed, smaller colour transitions,
  and short lamp-side fades that smooth movement between screen updates.
- **Decay (ms)**, default 180, adjusts the brightness falloff after an impact.
  Dimming begins immediately; this controls the fade rather than a hold time.
  Fades to complete black use a shorter tail so the room does not stay illuminated.
- **Brightness (%)**, default 100, scales the whole effect from 0 (dark) to 100
  (full effect output), preserving scene contrast instead of clipping highlights.

All four Cinema Sync sliders preview live while Settings stays open, without
restarting the effect. **OK** saves the previewed values. **Cancel**, Escape, or
closing Settings restores the saved values; previews are not written to disk.

Cinema Sync retains the lamp's selected Kelvin value and uses the existing screen
brightness offset, maximum, and dark cutoff before applying its overall brightness
percentage. Complete black can reach zero even with a positive offset.
It analyses a small frame at up to 20 updates per second;
capture and device latency still affect the visible response. SDR/sRGB is the
working assumption. HDR capture and colour accuracy still need live qualification.
The defaults have synthetic-scene coverage and need tuning against real films.

Settings includes these screen controls:

- **Screen max brightness (%)** caps brightness after the existing brightness offset.
- **Screen dark cutoff (%)** turns brightness below the cutoff to zero, after the offset.
- **Near-black threshold (0–255)** desaturates very dark RGB noise; the default is 10,
  and 0 disables this filter. Maximum brightness defaults to 100% and the cutoff to 0%.

The cap and cutoff apply to all three screen modes. The near-black threshold is for
Average and Dominant Screen Color; Cinema Sync has its own dark-pixel handling.
These controls do not change Music Color, Color Cycle, or manually selected colours.

Discovery retries transient failures, fetches state for up to eight devices concurrently,
and reuses the results to build panels and groups. A failed device read does not close
the app. These changes selectively adapt upstream work through
[`6f3301a`](https://github.com/samclane/LIFX-Control-Panel/commit/6f3301a14dc91b23c41332df37901d704cc3b741)
while retaining this fork's theme, cancellation, and polling fixes.

File offers **Save current state** and **Restore saved state**. States are keyed by
MAC address, so renaming a light does not lose its saved colours or power. Strips
also retain their individual zone colours. Saving is manual; **Restore saved lights
on startup** is an opt-in Settings checkbox and defaults to off. **Launch with
Windows** is a separate opt-in checkbox that manages this app's startup shortcut.

The tray menu controls individual lights and all lights. Keyboard shortcuts also
support **Toggle Power**, **Brightness Up**, and **Brightness Down**. Toggling a
mixed-power group turns the whole group off. Numeric colour entries use degrees,
percentages and Kelvin, and clamp values to the light's supported range.

Multizone panels show a strip of swatches. Sliders choose the paint colour without
changing the strip; click or drag the swatches and release to commit the stroke.
Presets and Pick Color still colour the whole strip. **Read zones** refreshes the
strip explicitly. Extended-capable firmware uses batches of up to 82 zones per
packet; older firmware uses coalesced inclusive ranges with bounded retries.
Zone editing and saved zone restoration still need acceptance testing on actual
Beam/Z hardware; the packet and UI regressions use simulated devices.

Source installations require Python 3.12 or later. CI is configured to test 3.12
and 3.14; the local executable build is verified on 3.12. Music Color remains optional:
install the `audio` extra or PyAudio to enable it. MSS is pinned to the version used
to verify the Windows cursor-flicker workaround.

[COMMIT_NOTES.md](COMMIT_NOTES.md) preserves the detailed change record for this update.

Run the offline test suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s lifx_control_panel/test -p "*test*.py" -v
```

# Attribution

Original project by Sawyer McLane and contributors.

This project also uses a fork of `lifxlan`:
- https://github.com/samclane/lifxlan

# License

MIT License. See `LICENSE.txt`.
