# Suggested commands (Windows PowerShell, project root)

- Local interpreter: `.venv` is a gitignored junction to `D:\miniconda3\envs\Python3.13`; verify with `Get-Item .venv | Select-Object LinkType,Target`.
- Install/update dependencies in that environment: `.\.venv\python.exe -m pip install -r requirements.txt`
- Run from source: `.\.venv\python.exe main.py`
- Syntax/import compilation: `.\.venv\python.exe -m compileall -q main.py cameras core ui`
- Hardware-free environment report: `.\.venv\python.exe -c "from core.app_state import AppConfig; from core.environment_check import run_environment_check; r=run_environment_check(AppConfig(), probe_hardware=False); print(r.to_text()); raise SystemExit(1 if r.has_errors else 0)"`
- Synthetic-camera smoke test: `.\.venv\python.exe -c "from core.app_state import AppConfig; from cameras.factory import create_camera; c=create_camera(AppConfig()); assert c.open(); ok, frame=c.read_frame(); assert ok and frame is not None; c.close(); print(frame.shape)"`
- Build directory distribution: `.\py_build\build_exe.bat`
- Build single EXE: `.\py_build\build_single_exe.bat`
- Outputs: `py_build\dist\OCRA\OCRA.exe` and `py_build\dist_single\OCRA_Single.exe`.
- No activation is required; invoke `.\.venv\python.exe` directly. If the junction is absent, use `D:\miniconda3\envs\Python3.13\python.exe`.
- Serena memory reference audit: `serena memories check`.
- Windows equivalents used during inspection: `Get-ChildItem` for listing; `rg`/`rg --files` for search.