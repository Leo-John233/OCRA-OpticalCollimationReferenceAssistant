# Technology stack

- Python desktop application; supported source runtime is 64-bit Python 3.12 or 3.13 (startup guard accepts >=3.10; README recommends 3.12/3.13).
- GUI: PyQt6 >=6.6. Vision/capture: opencv-python-headless >=4.8, NumPy >=1.24. Text rendering: Pillow >=10.
- ZWO integration uses bundled official `ASICamera2.dll` directly through `ctypes`; no `zwoasi` wrapper. USB/UVC uses OpenCV `VideoCapture`.
- Dependencies are declared in `requirements.txt`; no `pyproject.toml`, lockfile, test framework, linter, formatter, or static-check command is configured.
- Packaging: Windows batch scripts drive PyInstaller; scripts prefer an active venv/Conda env, otherwise reuse/create `py_build/.build_env`.
- Serena/Pyright resolves `.venv` through `pyrightconfig.json`. On this workstation `.venv` is a gitignored junction to `D:\miniconda3\envs\Python3.13`; its interpreter is `.venv\python.exe` (Conda layout, not `.venv\Scripts\python.exe`).