@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 单文件版通用构建脚本
rem 默认使用本地轻量构建环境以避免打入完整 Conda 科学计算运行库
rem 启用 OCRA_USE_ACTIVE_ENV 开关时允许直接使用当前激活环境
rem 依赖缺失时自动安装
rem 请在终端中运行本脚本

rem 解析项目路径
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "BUILD_ENV=%PROJECT_ROOT%\py_build\.build_env"
set "ENTRY_FILE=%PROJECT_ROOT%\main.py"
set "REQUIREMENTS_FILE=%PROJECT_ROOT%\requirements.txt"
set "ICON_FILE=%PROJECT_ROOT%\py_build\OCRA_icon.ico"
set "RUNTIME_ICON=%PROJECT_ROOT%\py_build\OCRA_icon.ico"
set "ZWO_DLL=%PROJECT_ROOT%\ASICamera2.dll"
set "CONFIG_DIR=%PROJECT_ROOT%\config"
set "DIST_ROOT=%PROJECT_ROOT%\py_build\dist_single"
set "OUTPUT_EXE=%DIST_ROOT%\OCRA_Single.exe"
set "BUILD_ROOT=%PROJECT_ROOT%\py_build\build_single"

echo ===================================================
echo 正在构建 OCRA 单文件版
echo ===================================================

rem 默认复用项目专用的轻量构建环境
set "PYTHON_EXE="
set "PYTHON_SOURCE="
if not "%OCRA_USE_ACTIVE_ENV%"=="1" goto local_build_env

rem 显式设置开关时优先使用当前激活环境
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
if defined PYTHON_EXE set "PYTHON_SOURCE=已激活的 Conda 环境"
if defined PYTHON_EXE goto python_ready
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"
if defined PYTHON_EXE set "PYTHON_SOURCE=已激活的虚拟环境"
if defined PYTHON_EXE goto python_ready

:local_build_env
if exist "%BUILD_ENV%\Scripts\python.exe" set "PYTHON_EXE=%BUILD_ENV%\Scripts\python.exe"
if defined PYTHON_EXE set "PYTHON_SOURCE=本地轻量构建环境"
if defined PYTHON_EXE goto python_ready

rem 本地环境不存在时从可用基础解释器创建
:create_build_env
call :find_base_python
if not defined BASE_PYTHON (
    echo [错误] 未找到可用的 Python
    echo 请安装 64 位 Python 3.10 或更高版本后重试
    exit /b 1
)
echo [信息] 正在创建本地构建环境
"%BASE_PYTHON%" -m venv "%BUILD_ENV%"
if errorlevel 1 (
    echo [错误] 创建本地构建环境失败
    exit /b 1
)
set "PYTHON_EXE=%BUILD_ENV%\Scripts\python.exe"
set "PYTHON_SOURCE=新建的本地构建环境"

:python_ready
echo [信息] 环境来源 %PYTHON_SOURCE%
echo [信息] 解释器路径 %PYTHON_EXE%

rem 检查解释器版本和位数
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [错误] OCRA 要求 Python 3.10 或更高版本
    exit /b 1
)
"%PYTHON_EXE%" -c "import struct; raise SystemExit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [错误] OCRA 要求使用 64 位 Python
    exit /b 1
)

rem 检查必要文件
if not exist "%ENTRY_FILE%" (
    echo [错误] 未找到程序入口文件
    echo %ENTRY_FILE%
    exit /b 1
)
if not exist "%REQUIREMENTS_FILE%" (
    echo [错误] 未找到依赖清单
    echo %REQUIREMENTS_FILE%
    exit /b 1
)
if not exist "%ICON_FILE%" (
    echo [错误] 未找到程序图标
    echo %ICON_FILE%
    exit /b 1
)
if not exist "%RUNTIME_ICON%" (
    echo [错误] 未找到运行时图标
    echo %RUNTIME_ICON%
    exit /b 1
)
if not exist "%ZWO_DLL%" (
    echo [错误] 未找到相机驱动库
    echo %ZWO_DLL%
    exit /b 1
)

rem 检查并准备构建依赖
"%PYTHON_EXE%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装 pip
    "%PYTHON_EXE%" -m ensurepip --upgrade
    if errorlevel 1 (
        echo [错误] 安装 pip 失败
        exit /b 1
    )
)
"%PYTHON_EXE%" -c "import PyInstaller, PyQt6, cv2, numpy, PIL" >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装构建依赖
    "%PYTHON_EXE%" -m pip install -r "%REQUIREMENTS_FILE%" pyinstaller
    if errorlevel 1 (
        echo [错误] 安装构建依赖失败
        exit /b 1
    )
)
"%PYTHON_EXE%" -c "import PyInstaller, PyQt6, cv2, numpy, PIL" >nul 2>&1
if errorlevel 1 (
    echo [错误] 构建依赖检查失败
    exit /b 1
)

rem 创建中间目录
if not exist "%BUILD_ROOT%\spec" mkdir "%BUILD_ROOT%\spec"
if not exist "%BUILD_ROOT%\work" mkdir "%BUILD_ROOT%\work"

rem 定位窗口平台插件
set "PYQT_PATH_FILE=%BUILD_ROOT%\pyqt_path.txt"
"%PYTHON_EXE%" -c "import os, PyQt6; print(os.path.dirname(PyQt6.__file__))" > "%PYQT_PATH_FILE%"
if errorlevel 1 (
    echo [错误] 无法定位 PyQt6 安装目录
    exit /b 1
)
set /p "PYQT_ROOT="<"%PYQT_PATH_FILE%"
del /Q "%PYQT_PATH_FILE%" >nul 2>&1
set "QT_PLUGIN_DIR=%PYQT_ROOT%\Qt6\plugins"
if not exist "%QT_PLUGIN_DIR%\platforms\qwindows.dll" (
    echo [错误] 未找到窗口平台插件
    echo %QT_PLUGIN_DIR%\platforms\qwindows.dll
    exit /b 1
)
if not exist "%QT_PLUGIN_DIR%\styles\qmodernwindowsstyle.dll" (
    echo [错误] 未找到现代窗口样式插件
    echo %QT_PLUGIN_DIR%\styles\qmodernwindowsstyle.dll
    exit /b 1
)

rem 执行单文件版打包
pushd "%PROJECT_ROOT%"
rem 共用入口让 PyInstaller 能找到基础 Conda 环境中的传递依赖
"%PYTHON_EXE%" "%PROJECT_ROOT%\py_build\build_runtime.py" build ^
    --name "OCRA_Single" ^
    --onefile ^
    --windowed ^
    --clean ^
    --noconfirm ^
    --optimize 2 ^
    --icon "%ICON_FILE%" ^
    --additional-hooks-dir "%PROJECT_ROOT%\py_build\hooks" ^
    --exclude-module numpy.testing ^
    --exclude-module PIL.ImageQt ^
    --distpath "%DIST_ROOT%" ^
    --workpath "%BUILD_ROOT%\work" ^
    --specpath "%BUILD_ROOT%\spec" ^
    --add-binary "%ZWO_DLL%;." ^
    --add-binary "%QT_PLUGIN_DIR%\platforms\qwindows.dll;PyQt6\Qt6\plugins\platforms" ^
    --add-binary "%QT_PLUGIN_DIR%\styles\qmodernwindowsstyle.dll;PyQt6\Qt6\plugins\styles" ^
    --add-data "%RUNTIME_ICON%;." ^
    "%ENTRY_FILE%"
set "BUILD_EXIT=%ERRORLEVEL%"
popd

if not "%BUILD_EXIT%"=="0" (
    echo [错误] 打包失败 错误码 %BUILD_EXIT%
    exit /b %BUILD_EXIT%
)
if not exist "%OUTPUT_EXE%" (
    echo [错误] 打包结束但未生成 OCRA_Single.exe
    exit /b 1
)

rem 直接检查 EXE 内部归档，不借用开发机 PATH 中的运行库
"%PYTHON_EXE%" "%PROJECT_ROOT%\py_build\build_runtime.py" verify "%OUTPUT_EXE%"
if errorlevel 1 (
    echo [错误] 单文件版依赖检查失败 请勿发布当前包体
    exit /b 1
)

rem 复制发布所需文件
if exist "%CONFIG_DIR%" (
    xcopy "%CONFIG_DIR%" "%DIST_ROOT%\config\" /E /I /Y >nul
    if errorlevel 1 (
        echo [错误] 复制配置目录失败
        exit /b 1
    )
)
if exist "%PROJECT_ROOT%\LICENSE" copy /Y "%PROJECT_ROOT%\LICENSE" "%DIST_ROOT%\LICENSE" >nul
if exist "%PROJECT_ROOT%\README.md" copy /Y "%PROJECT_ROOT%\README.md" "%DIST_ROOT%\README.md" >nul
if exist "%PROJECT_ROOT%\README_EN.md" copy /Y "%PROJECT_ROOT%\README_EN.md" "%DIST_ROOT%\README_EN.md" >nul
if exist "%PROJECT_ROOT%\THIRD_PARTY_NOTICES.md" copy /Y "%PROJECT_ROOT%\THIRD_PARTY_NOTICES.md" "%DIST_ROOT%\THIRD_PARTY_NOTICES.md" >nul

echo ===================================================
echo [成功] 单文件版已生成
echo %OUTPUT_EXE%
echo 请将 config 目录与 OCRA_Single.exe 一同发布
echo ===================================================
exit /b 0

rem 查找用于创建本地构建环境的基础解释器
:find_base_python
set "BASE_PYTHON="
if defined OCRA_BUILD_PYTHON if exist "%OCRA_BUILD_PYTHON%" set "BASE_PYTHON=%OCRA_BUILD_PYTHON%"
if defined BASE_PYTHON exit /b 0
if exist "D:\miniconda3\envs\Python3.13\python.exe" set "BASE_PYTHON=D:\miniconda3\envs\Python3.13\python.exe"
if defined BASE_PYTHON exit /b 0
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "BASE_PYTHON=%CONDA_PREFIX%\python.exe"
if defined BASE_PYTHON exit /b 0
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "BASE_PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
if defined BASE_PYTHON exit /b 0
where py >nul 2>&1
if errorlevel 1 goto find_python_command
for /f "delims=" %%P in ('py -3.13 -c "import sys; print(sys.executable)" 2^>nul') do if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
for /f "delims=" %%P in ('py -3.10 -c "import sys; print(sys.executable)" 2^>nul') do if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0

:find_python_command
where python >nul 2>&1
if errorlevel 1 exit /b 1
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
exit /b 1
