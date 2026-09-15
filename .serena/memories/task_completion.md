# Task completion checks

- No repository test suite, linter, or formatter is configured and these checks must not be claimed
- Run `python -m compileall -q main.py cameras core ui` in the selected runtime environment
- For non-hardware changes run the synthetic-camera smoke check from `mem:suggested_commands`
- For dependency, startup, or UI changes also run the hardware-free environment report and require a successful exit
- For vision changes add a deterministic check with synthetic NumPy input and exercise the changed fitting or drawing path
- For config changes use a temporary file and do not overwrite `config/config.txt`
- For camera-specific changes use hardware-free paths and explicitly report that physical hardware was not tested
- For packaging changes run the affected batch build and confirm the expected EXE or output directory exists
- Check `git status --short` and preserve unrelated user changes and generated diagnostics
- Serena health requires active project OCRA, Python LSP ready, a valid ignored `.serena/python-env.local.json`, a generated ignored `pyrightconfig.json`, and successful symbol and diagnostic calls
- If the Serena analysis environment is changed, run `.\.serena\select_python_env.ps1` and reactivate OCRA before trusting diagnostics