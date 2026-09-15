# Camera module

- `BaseCamera` defines `open() -> bool`, `read_frame() -> (bool, Optional[np.ndarray])`, `close() -> None`, and display `name()`.
- `cameras.factory.create_camera(AppConfig)` is the sole backend-selection point: `usb` -> `USBCamera`, `zwo` -> `ZWOCamera`, `qhy` -> placeholder, everything else -> `SyntheticCamera`.
- `list_camera_devices` owns enumeration. Do not add brand conditionals in UI/video code.
- Frames returned to consumers are BGR NumPy arrays.
- ZWO loads `ASICamera2.dll` through ctypes, validates bitness/entrypoints, converts exposure milliseconds to SDK microseconds, and maps UI ISO to ASI OFFSET.
- USB controls are device/driver-dependent; unsupported exposure/gain/ISO/brightness/focus writes are intentionally tolerated.
- QHY currently opens false and returns no frames; retaining a safe placeholder is intentional.
- Synthetic camera is the required hardware-free development and smoke-test backend.
- Read project-wide coding rules in `mem:conventions` and completion checks in `mem:task_completion`.