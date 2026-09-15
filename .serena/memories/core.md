# OCRA project map

- Windows desktop telescope-collimation assistant; source-only entrypoint `main.py`, packaged with PyInstaller.
- Runtime layers: camera adapters in `cameras/`; shared state/config, startup checks, i18n, and computer vision in `core/`; Qt widgets/threading in `ui/`.
- Read `mem:tech_stack` for runtime/build dependencies and version expectations.
- Read `mem:suggested_commands` for Windows setup, run, smoke-check, and packaging commands.
- Read `mem:conventions` before changing cross-layer APIs or configuration.
- Read `mem:task_completion` before handing off code changes.
- Local Serena/Pyright interpreter setup and Windows error recovery: `mem:serena_troubleshooting`.
- Camera abstraction/factory and hardware constraints: `mem:cameras/core`.
- State, persistence, startup diagnostics, vision ownership: `mem:core_module/core`.
- Qt main window, video-thread backpressure, and interaction ownership: `mem:ui/core`.
- Project invariants: images are BGR NumPy arrays; camera implementations are selected only by `cameras.factory.create_camera`; UI/video/vision consume `AppConfig`; QHY is intentionally a safe placeholder; default synthetic camera enables hardware-free operation.
- Runtime asset paths must work both from source and frozen PyInstaller layouts. Preserve Windows DLL/Qt plugin startup guards.