# Suggested commands on Windows PowerShell

- List Serena analysis environments: `.\.serena\select_python_env.ps1 -List`
- Select the stable analysis environment: `.\.serena\select_python_env.ps1 -Name Python3.13`
- Select an environment from another root: `.\.serena\select_python_env.ps1 -Name <name> -EnvRoot <path>`
- Install project dependencies into a target environment: `& "D:\miniconda3\envs\<name>\python.exe" -m pip install -r requirements.txt`
- Actual runtime environments may be activated independently with Conda and do not change Serena analysis
- Optional local runtime alias: `.venv` may point to `D:\miniconda3\envs\Python3.13`, but Serena does not depend on it
- Run from source in an activated environment: `python main.py`
- Compile check in an activated environment: `python -m compileall -q main.py cameras core ui`
- Build directory distribution: `.\py_build\build_exe.bat`
- Build single EXE: `.\py_build\build_single_exe.bat`
- Outputs: `py_build\dist\OCRA\OCRA.exe` and `py_build\dist_single\OCRA_Single.exe`
- Serena memory reference audit: `serena memories check`
- Use `rg` and `rg --files` for project search