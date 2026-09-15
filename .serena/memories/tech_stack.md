# Technology stack

- Python desktop application targeting 64-bit Windows
- Supported source runtime is Python 3.12 or 3.13 while the startup guard accepts Python 3.10 or newer
- GUI dependencies are pinned to PyQt6 6.8.1 and PyQt6-Qt6 6.8.1 to avoid the Conda ICU entry-point conflict observed with 6.10 and 6.11
- Vision and capture use opencv-python-headless 4.8 or newer and NumPy 1.24 or newer
- Text rendering uses Pillow 10 or newer
- ZWO support uses bundled `ASICamera2.dll` through `ctypes`; USB/UVC uses OpenCV `VideoCapture`
- PyInstaller batch scripts use the dedicated ignored `py_build/.build_env` by default
- Serena uses Pyright through the Python LSP
- Shared Pyright settings live in tracked `pyrightconfig.base.json`
- Local environment selection lives in ignored `.serena/python-env.local.json` and generates ignored `pyrightconfig.json`
- Serena activation runs `.serena/select_python_env.ps1` before the LSP starts
- The optional `.venv` junction is only a runtime convenience and is not part of Serena import resolution