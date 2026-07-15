@echo off
:: 设置编码为UTF-8避免中文乱码
chcp 65001 >nul

echo ===================================================
echo                 开始全自动打包 
echo ===================================================

:: 切换到当前脚本所在的 py_build 目录
cd /d "%~dp0"

echo 正在调用 PyInstaller 进行打包，请稍候...

:: 关键参数解释：
:: -n: 指定生成的 exe 文件和文件夹的名称 (这里命名为 OCRA)
:: -D: 目录模式 (生成一个文件夹，包含exe和所有依赖，其他电脑无需装环境，启动快)
:: -w: 隐藏控制台黑框
:: -i: 指定图标所在路径
:: --add-binary: 将 DLL 文件拷贝进去，格式是 "源路径;打包后的存放位置" (. 代表放在生成的 exe 同级目录)

pyinstaller -n "OCRA" -D -w ^
 -i "E:\GitHub\OCRA\py_build\OCRA_icon.ico" ^
 --add-binary "E:\GitHub\OCRA\ASICamera2.dll;." ^
 --add-binary "C:\Windows\System32\vcruntime140.dll;." ^
 --add-binary "C:\Windows\System32\vcruntime140_1.dll;." ^
 --add-binary "C:\Windows\System32\msvcp140.dll;." ^
 "E:\GitHub\OCRA\main.py"

echo ===================================================
echo 打包完成
echo 最终可独立运行的程序文件夹在: dist\OCRA
echo ===================================================
pause