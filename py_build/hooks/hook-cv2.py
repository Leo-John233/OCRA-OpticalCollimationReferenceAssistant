"""收集 OCRA 需要的 OpenCV 运行文件

USB 相机使用 Windows 原生视频接口
不打包仅用于视频文件编解码的 FFmpeg 动态库
"""

import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = ["numpy", "cv2.cv2"]
hiddenimports += collect_submodules("cv2", filter=lambda name: name != "cv2.load_config_py2")
excludedimports = ["cv2.load_config_py2"]
datas = collect_data_files(
    "cv2",
    include_py_files=True,
    includes=[
        "config.py",
        f"config-{sys.version_info[0]}.{sys.version_info[1]}.py",
        "config-3.py",
        "load_config_py3.py",
    ],
)
module_collection_mode = "py"
