@echo off
:: 设置编码为UTF-8避免中文乱码
chcp 65001 >nul

echo ===================================================
echo             开始全自动打包 (单文件版)
echo ===================================================

:: 切换到当前脚本所在的 py_build 目录
cd /d "%~dp0"

echo 正在调用 PyInstaller 进行单文件打包，请稍候...

:: 关键参数解释：
:: -n: 指定生成的 exe 文件的名称
:: -F: 单文件模式 (生成一个独立的exe文件，包含所有依赖)
:: -w: 隐藏控制台黑框
:: -i: 指定图标所在路径
:: --distpath: 指定最终生成的 exe 存放文件夹，用于与原目录模式隔离
:: --workpath: 指定打包过程中的临时缓存文件夹，用于隔离
:: --add-binary: 将 DLL 文件打包进 exe，程序运行时会自动释放到临时目录调用

pyinstaller -n "OCRA_Single" -F -w ^
 -i "E:\GitHub\OCRA\py_build\OCRA_icon.ico" ^
 --distpath "dist_single" ^
 --workpath "build_single" ^
 --add-binary "E:\GitHub\OCRA\ASICamera2.dll;." ^
 --add-binary "C:\Windows\System32\vcruntime140.dll;." ^
 --add-binary "C:\Windows\System32\vcruntime140_1.dll;." ^
 --add-binary "C:\Windows\System32\msvcp140.dll;." ^
 "E:\GitHub\OCRA\main.py"

echo ===================================================
echo 打包完成
echo 单文件版可执行程序位于: dist_single\OCRA_Single.exe
echo ===================================================
pause