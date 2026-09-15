# Core module

- `AppConfig` is shared runtime state for UI, video thread, cameras, and vision. Add persistent settings there first.
- `ConfigManager` maps flat `config/config.txt` keys to `AppConfig` and nested circle/star values; UI should update AppConfig then save through the manager.
- `VisionEngine` owns overlay/HUD rendering, measurements, robust circle fitting, outer-edge and secondary-edge snapping. UI owns orchestration/state-machine decisions, not fitting math.
- Outer circle establishes reference center. Middle/inner/secondary centers are independent unless their concentric-with-outer mode is enabled.
- Outer-edge finalization combines three independent rounds and applies RANSAC, Huber IRLS, MAD rejection, angular coverage, and condition-number checks; do not reduce it to three-point fitting or simple averaging.
- `startup_guard.py` runs before importing/creating Qt, normalizes source/frozen paths, configures Windows DLL/Qt plugin lookup, and writes startup diagnostics.
- `environment_check.py` provides software/storage/camera checks; use `probe_hardware=False` for CI/development.
- `i18n.py` is the single catalog for Chinese/English UI strings.
- Read commands in `mem:suggested_commands` and UI ownership in `mem:ui/core`.