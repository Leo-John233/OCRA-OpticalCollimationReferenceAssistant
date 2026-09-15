# Serena troubleshooting on Windows

- Serena and Pyright no longer depend on the optional project-root `.venv` junction
- The tracked `pyrightconfig.base.json` contains shared analysis scope while the generated `pyrightconfig.json` contains local environment paths and is ignored by Git
- The local selection is stored in ignored `.serena/python-env.local.json`
- `.serena/select_python_env.ps1` validates the interpreter and required imports before atomically replacing the local state and Pyright configuration
- Serena runs that selector automatically through `.serena/project.yml` `activation_command` before starting the language server
- List environments with `.\.serena\select_python_env.ps1 -List`
- Select an analysis environment with `.\.serena\select_python_env.ps1 -Name Python3.13`
- Override the root with `-EnvRoot` or `SERENA_ENV_ROOT` and the name with `SERENA_PYTHON_ENV`
- A rejected environment does not overwrite the last valid selection
- If diagnostics remain stale after a valid switch, reactivate OCRA to start a clean language-server session
- The selector is UTF-8 BOM with CRLF because Windows PowerShell 5.1 can misparse UTF-8 Chinese text without a BOM
- For uv cache permission errors in restricted sessions set `UV_CACHE_DIR` to `$PWD\.serena\cache\uv`
- For Serena home permission errors set `SERENA_HOME` to `$PWD\.serena\cache\cli-home`
- For Chinese console encoding errors set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`
- Serena is healthy when OCRA is active, the Python LSP reports ready, and diagnostics contain no missing-import errors