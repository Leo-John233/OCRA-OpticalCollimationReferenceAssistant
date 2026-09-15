# Serena troubleshooting (Windows/local setup)

- Current project config: `.serena/project.yml`, language server `python`, UTF-8, workspace root `.`; `pyrightconfig.json` selects `.venv`.
- On this workstation `.venv` is a gitignored directory junction to `D:\miniconda3\envs\Python3.13`. That environment contains PyQt6/OpenCV/NumPy/Pillow and uses `.venv\python.exe`.
- Pyright `reportMissingImports`: verify the junction target and imports with `& .\.venv\python.exe -c "import PyQt6, cv2, numpy, PIL"`; then restart the Serena Python language server. Switching to another project and reactivating OCRA also forces a clean server start when the restart tool is unavailable.
- A stale language-server process can retain diagnostics created before the environment/config existed; a clean restart is required after changing `pyrightconfig.json` or interpreter paths.
- uv `Failed to initialize cache ... PermissionError` in a restricted session: set `$env:UV_CACHE_DIR="$PWD\.serena\cache\uv"`; the cache path is project-writable and ignored.
- Serena CLI `PermissionError: C:\Users\...\.serena` in a restricted session: set `$env:SERENA_HOME="$PWD\.serena\cache\cli-home"`. This override has its own config/project registry.
- Serena CLI `UnicodeEncodeError: gbk ... ✓` on Chinese Windows: set `$env:PYTHONUTF8="1"` and `$env:PYTHONIOENCODING="utf-8"` before the CLI call.
- Verified memory audit form in this session: `serena memories check <absolute-project-path> --include-unmarked --fuzzy-matching`; result had no integrity issues.
- Serena is healthy when `get_current_config` reports active project OCRA / LSP ready and symbol lookup, reference lookup, and diagnostics calls all return normally.