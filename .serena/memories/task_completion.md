# Task completion checks

- No repository test suite/linter/formatter is configured. Do not claim those checks ran.
- Always run: `.\.venv\python.exe -m compileall -q main.py cameras core ui`.
- For non-hardware changes, run the synthetic-camera smoke command from `mem:suggested_commands`.
- For dependency/startup/UI changes, also run the hardware-free environment report from `mem:suggested_commands`; it must exit 0.
- For vision changes, add a focused deterministic script/check using synthetic NumPy input and exercise the changed fitting/drawing path.
- For config changes, load then save through `ConfigManager` using a temporary path and confirm round-trip behavior; do not overwrite the user's `config/config.txt`.
- For camera-specific changes, use hardware-free paths locally and explicitly report untested physical-camera behavior.
- For packaging changes, run the affected batch build and confirm the expected EXE/output directory exists.
- Check `git status --short`; preserve unrelated user changes and generated diagnostics.
- Serena health: active project must be OCRA, language server status ready, imports resolve via `pyrightconfig.json` + `.venv`, and basic symbol/reference/diagnostic calls must succeed.