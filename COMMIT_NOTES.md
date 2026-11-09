# Change record: stability, device controls, and Cinema Sync

Base commit: `ac245dd`. Recorded on 2026-11-03.

- Restore themed effect-button backgrounds when effects stop.
- Keep preset labels readable against their selected colours.
- Disable empty custom-preset menus.
- Prevent Windows screen capture from flickering the mouse cursor.
- Make continuous effects exclusive within each light panel.
- Stop competing effects on overlapping groups and individual lights.
- Discard stale effect calculations after stopping or switching effects.
- Preserve independent colour-slider variables for each light panel.
- Prevent duplicate polling timers when reopening light panels.
- Keep only the latest queued device state for the interface.
- Prevent slow device queries from accumulating polling batches.
- Give each rescan its own polling cancellation event.
- Read device state concurrently with a bounded worker pool during discovery.
- Reuse prefetched device state when constructing light panels.
- Build groups from discovered devices without repeating LAN discovery.
- Retry transient discovery and device-state failures.
- Bound Windows UDP reset handling by the original receive timeout.
- Recover multizone devices incorrectly classified as ordinary lights.
- Skip unreachable devices without closing the application.
- Register clickable device icons only after their panels are built.
- Preserve the working interface after failed network discovery.
- Tolerate missing icon-cache entries after rescanning.
- Limit continuous effects to twenty updates per second.
- Coalesce slider drags while retaining the final colour value.
- Cancel pending slider writes when another control takes over.
- Reuse screen-capture resources within each effect worker.
- Avoid large colour-histogram allocations during dominant-colour capture.
- Support dominant-colour sampling from very small screen regions.
- Apply edited screen regions when restarting screen-following effects.
- Reject invalid screen-capture dimensions before starting effects.
- Add screen-following brightness caps and dark-scene cutoffs.
- Add an adjustable near-black colour-noise filter.
- Keep screen-following brightness limits separate from other effects.
- Restore original keyboard-shortcut callbacks after closing Settings.
- Remove only keyboard hooks owned by the application.
- Prevent deleted keyboard shortcuts from returning after Settings closes.
- Dispatch tray and shortcut callbacks through the Tk event queue.
- Stop competing effects before applying keyboard colour shortcuts.
- Allow Settings to open when no lights are discovered.
- Validate shortcut selections before registering them.
- Store portable settings beside the executable using atomic file replacement.
- Keep application logs beside the executable.
- Close the previous audio stream when switching inputs.
- Support mono audio inputs and exclude output-only devices.
- Drain buffered audio to keep music effects current.
- Allow startup without the optional PyAudio dependency.
- Close effects, keyboard hooks, audio streams and the tray icon on shutdown.
- Make eyedropper selection cancellable without background Tk calls.
- Preserve slider positions when their widgets are resized.
- Correct colour-scale reads for nonzero minimum values.
- Package only the intended entry point in each executable.
- Make the demo use simulated devices without discovering real lights.
- Repair test imports and populate meaningful dummy-device fixtures.
- Add regressions for effect cancellation, discovery, settings and lifecycle behaviour.
- Rebuild all executable variants in the existing distribution folder.

- Serialize writes to each physical light across effects and background actions.
- Invalidate superseded queued actions when another control takes over.
- Add manual saving of light states keyed by MAC address.
- Restore saved colours and power after light labels change.
- Save and restore individual multizone colours.
- Add opt-in restoration of saved lights on application startup.
- Add opt-in Windows startup registration using native shortcuts.
- Add individual and all-light power controls to the tray menu.
- Add power-toggle and brightness-adjustment keyboard shortcuts.
- Turn mixed-power groups off together when toggling group power.
- Add validated numeric entry for hue, saturation, brightness and Kelvin.
- Preserve typed colour values while their entry has focus.
- Add multizone painting that commits colours on mouse release.
- Keep multizone sliders as a paint palette instead of repainting the strip.
- Add explicit zone refresh without repeatedly polling every zone.
- Batch extended-zone writes into packets of up to eighty-two colours.
- Split extended writes across multiple packets for longer strips.
- Coalesce equal neighbouring colours in legacy zone writes.
- Retry lost zone acknowledgements without reporting recovered attempts as failures.
- Cancel remaining zone retries after a newer action takes over.
- Avoid guessing extended-zone support when firmware detection fails.
- Verify multizone packet layout and inclusive legacy zone ranges.
- Scale custom icons and colour controls for high-resolution displays.
- Wrap complete device names instead of truncating them to eight characters.
- Expand icon rows to contain the full wrapped device label.
- Avoid repeated colour conversions while rendering scaled bulb icons.
- Replace audioop with portable sixteen-bit PCM RMS calculation.
- Replace deprecated Tk variable traces with trace_add callbacks.
- Use the native Python thread-exception hook.
- Make PyAudio an optional package extra.
- Remove the unused numexpr dependency.
- Pin the screen-capture version used by the cursor-flicker workaround.
- Add a Windows CI test matrix for Python 3.12 and Python 3.14.
- Update CI actions and remove obsolete SWIG installation steps.
- Build executables with the supported PyInstaller 6 workflow.
- Preserve all queued light updates during overlapping-group batch actions.
- Skip network reads for superseded queued group shortcuts.
- Normalize initial and polled colour values before comparing cached device states.
- Add end-to-end saved-state and tray-action regression checks.
- Exercise startup shortcuts in a temporary folder without changing Windows startup.
- Add an exclusive Cinema Sync effect for dynamic movie lighting on a room lamp.
- Blend supported illuminated colours without averaging opposing colours to grey.
- Combine scene exposure and highlight area to reflect bright action without normalizing dark scenes.
- Discount paired black bars and conservatively filter thin white subtitle-shaped regions.
- Follow abrupt colour changes quickly and provide adjustable brightness attack and decay.
- Preserve the previous colour while fading to black and prevent brightness offsets from keeping black scenes lit.
- Add Impact, Response, and Decay controls with defaults of 80 percent, 90 percent, and 180 milliseconds.
- Apply existing screen brightness caps and cutoffs to Cinema Sync while retaining the selected Kelvin value.
- Reset Cinema Sync analysis history on every start.
- Limit Cinema Sync analysis to a small frame and reuse the existing cursor-friendly capture worker.
- Rename the shared capture area to Screen Region for all screen lighting modes.
- Add synthetic movie-scene, effect switching, worker restart, and Cinema Sync settings regressions.
- Document Cinema Sync tuning and the remaining live movie and HDR qualification limits.
- Smooth Cinema Sync colour and brightness updates with short response-dependent lamp transitions.
- Add an overall Cinema Sync brightness slider that scales output after screen brightness limits.
- Apply saved Cinema Sync brightness changes to running effects without restarting them.
- Cover interpolated transitions and brightness scaling with simulated-device regressions.
- Preview all four Cinema Sync sliders live while the Settings window remains open.
- Keep live previews separate from saved configuration until OK is pressed.
- Restore saved Cinema Sync settings when preview changes are cancelled or the window closes.
- Verify live slider updates reach the existing effect worker without restarting capture.
- Reduce the sustained brightness of small highlights in otherwise dark scenes.
- Reserve strong highlight boosts for sudden increases in illumination and pronounced colour changes.
- Avoid retriggering highlight impacts when a steady light source moves across the screen.
- Add sustained-headlight, moving-headlight, white-strobe, and localized police-light regressions.
- Rename the effect to Cinema Sync while preserving existing slider settings.
- Replace abrupt dominant-colour handoffs with progressive hue and saturation blending.
- Keep transitions smooth through balanced and nearly complementary colour mixtures.
- Base fast colour response on screen changes instead of the distance between output hues.
- Add gradual blue-to-red, white-reveal, and multicolour transition regressions.
- Remove the live-preview explanatory line from the Settings window.
- Poll a strip's representative colour without repeatedly downloading its full zone palette.
- Remove unused imports and obsolete demo logging setup.
- Declare the Windows runtime dependency in package metadata and remove an obsolete platform classifier.
- Refresh the feature overview, audio installation instructions, and Cinema Sync control documentation.
- Remove superseded build and test scratch logs while retaining the current build receipt.
- Pin the formatting hook to the verified Black release instead of a mutable reference.

## UI refresh after 7c13557

- Arrange all eight effect and tool buttons in an equal four-row, two-column grid.
- Replace horizontal bitmap icon strips with compact device lists and live colour indicators.
- Place light and group navigation in compact tabs above the controls to preserve the original window width.
- Show navigation scrollbars only when content overflows and clamp scrolling after resizing.
- Preserve full device names with wrapping and ignore clicks on empty navigation space.
- Group Settings into five compact tabs without changing saved values or live Cinema Sync previews.
- Fit the Settings window height to the active tab instead of reserving empty space for every page.
- Prevent short shortcut tables from scrolling past their content.
- Collapse advanced screen-region controls until they are needed.
- Add a direct Settings toolbar button and allow vertical window resizing without widening the default layout.
- Use consistent typography, flat controls, subtle borders, and readable light and dark palettes.
- Keep active effects, hover text, keyboard focus, and colour previews readable in both themes.
- Cancel owned polling and queued UI callbacks when their windows are destroyed.
- Add geometry, label-fit, scrolling, theme, and timer-cleanup regressions.
- Restore compact sliders and shorten screen-effect button labels to fit the original width.
- Fit multizone controls within the same compact window width.
- Check full light, group, and strip panels against the pre-refresh width in both themes.
- Disable file logging by default and make diagnostic logging an explicit General setting.
- Limit diagnostic logging to a one-megabyte file and one backup with bounded UTF-8 records.
- Apply diagnostic retention limits to oversized legacy files when logging is enabled.
- Stop diagnostic writes immediately when disabled and avoid duplicate logging handlers.
- Test disabled logging, retention, UTF-8 rotation, oversized records, and repeated reconfiguration.

## Dropdown and menu polish after f9a2b02

- Replace legacy preset and Settings dropdowns with consistently styled readonly selectors.
- Use clear arrows, balanced insets, and readable selection and disabled states in both themes.
- Display friendly preset and monitor labels while preserving stored values and capture coordinates.
- Fit long names in the popup without widening the main window.
- Show dropdown scrollbars only when their choices overflow the available rows.
- Prevent mouse-wheel movement over a closed dropdown from changing settings or the lamp.
- Preserve repeated preset selection so the same colour can be applied again.
- Disable empty selectors with useful placeholder text instead of an empty or None choice.
- Refresh choices without triggering actions and remove variable traces when controls are destroyed.
- Keep newly created dropdowns consistent with the selected app theme after rescans.
- Give File, Settings, and About matching compact toolbar controls.
- Replace the File menu overlay with a bordered popup containing spaced and grouped commands.
- Support keyboard menu navigation, Escape dismissal, outside clicks, focus changes, and window minimization.
- Release menu grabs before running commands and clean up owned bindings and delayed callbacks.
- Keep popups within their display's working area, including displays with negative desktop coordinates.
- Scale dropdown arrows, popup insets, and menu rows with display density.
- Preserve the accepted 293-pixel main-window width at the same display scaling.
- Add offline regressions for dropdown selection, themes, geometry, scrolling, monitor values, and menu lifecycle.

Validation for this pass:

- Pass 121 tests with two existing skips and no Tk callback errors.
- Measure light, group, and strip panels at 293 pixels wide before and after the change at 96 DPI.
- Measure widths of 407 versus 410 pixels at 150 percent Tk scaling and 518 versus 528 pixels at 200 percent Tk scaling.
- Verify the final UI through automated widget checks without desktop input.
- Rebuild normal, debug, and offline demo executables in the existing dist folder.
- Verify packaged UI code and entrypoints against source and confirm diagnostic logging remains disabled by default.

Normal executable SHA-256: `bdc3e719254afaf802c80db763ae4c5a439888eee68414d8f8535b806d69ef2b`.

## Settings toggle and effect-state recall

- Toggle one Settings window from either the toolbar or File menu without opening duplicates.
- Keep the main controls usable while Settings is open.
- Document that lighting keyboard shortcuts pause until Settings closes.
- Treat toggling Settings closed as Cancel and restore unsaved Cinema Sync previews.
- Preserve OK saving and release Settings listeners, timers, and references on every close path.
- Capture each physical light's colour, brightness, Kelvin, power, and strip zones before an effect starts.
- Retain the original light state when switching or reselecting any of the five effects.
- Restore original states when Stop effects is pressed, including individual states within groups.
- Restore unused group members when an effect moves from a group to a member.
- Let manual commands supersede effects and establish a fresh baseline for the next effect.
- Read and restore light states off the UI thread using the existing ordered device commands.
- Prevent delayed captures, restores, and UI previews from overriding newer user choices.
- Cancel pending effect starts when stopped or when their panel is destroyed.
- Report snapshot failures before starting an effect and retain failed restores for a Stop effects retry.
- Keep effect-state recall in session memory without creating another file.
- Document failed-restore retries and the lifetime of temporary effect-state memory.
- Add regressions for all effect modes, rapid handoffs, cancellation, groups, zones, failures, and Settings lifecycle.

Validation: 139 tests passed with two existing skips, including the unchanged compact-width checks and retrying a failed group restore from the same member's Stop button.

Rebuilt all three executables in the existing dist folder and verified packaged code and default-off diagnostic logging against source.

Normal executable SHA-256: `3235fa72f64a632a4228883dddf1ce275f81c0b9262a08c475a66c7c6b152f00`.
