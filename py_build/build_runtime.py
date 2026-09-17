"""为打包补齐基础解释器的 DLL 搜索路径并检查发布包依赖

只收集实际被引用的运行库，不复制整个 Conda 的 Library/bin
目录版和单文件版共用同一套检查，避免两种包体行为不一致
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Iterable


_DLL_HANDLES: list[object] = []
_VC_RUNTIME = re.compile(r"^(?:msvcp|vcruntime|concrt)\d", re.IGNORECASE)


def runtime_directories() -> list[Path]:
    """从当前解释器和基础解释器定位 DLL，不借用其他已激活环境"""
    result: list[Path] = []
    for prefix in (sys.prefix, sys.base_prefix):
        root = Path(prefix).resolve()
        for candidate in (root / "Library" / "bin", root / "DLLs", root):
            if candidate.is_dir() and candidate not in result:
                result.append(candidate)
    return result


def configure_build_search(directories: Iterable[Path]) -> None:
    """同时配置 Windows Loader 和 PyInstaller 子进程的 DLL 搜索路径"""
    directories = list(directories)
    existing_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([*(str(path) for path in directories), existing_path])
    for directory in directories:
        if hasattr(os, "add_dll_directory"):
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    print("[信息] 已注册基础解释器运行库目录", flush=True)
    for directory in directories:
        print(f"  {directory}", flush=True)


def normalize_name(name: str) -> str:
    """统一归档路径的分隔符和大小写以兼容 Windows 文件名"""
    return name.replace("\\", "/").casefold()


def find_missing_dependencies(
    imports: dict[str, set[str]],
    bundled: set[str],
    system_libraries: set[str],
    private_libraries: set[str],
) -> list[tuple[str, str]]:
    """检查普通 PE 导入表，不把 PATH 或其他 Python 环境当成包内依赖"""
    bundled = {normalize_name(name) for name in bundled}
    missing: list[tuple[str, str]] = []
    for owner, dependencies in imports.items():
        parent = PurePosixPath(normalize_name(owner)).parent
        for dependency in sorted(dependencies):
            name = normalize_name(dependency)
            # API Set 是由 Windows 解析的系统契约，不是需要复制的普通 DLL
            if name.startswith(("api-ms-", "ext-ms-")):
                continue
            candidates = {name, str(parent / name), f"pyqt6/qt6/bin/{name}"}
            # NumPy 的初始化模块会显式注册其 wheel 自带的 numpy.libs 目录
            if normalize_name(owner).startswith("numpy/"):
                candidates.add(f"numpy.libs/{name}")
            if candidates & bundled:
                continue
            # Conda 私有库和 VC 运行库必须随包提供，不能依赖开发机恰好已安装
            portable = name in private_libraries or _VC_RUNTIME.match(name)
            if name in system_libraries and not portable:
                continue
            missing.append((owner, dependency))
    return missing


def package_binaries(output: Path):
    """读取目录版文件或单文件 EXE 归档中的全部 DLL 和 Python 扩展"""
    if output.is_dir():
        root = output / "_internal" if (output / "_internal").is_dir() else output
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.casefold() in {".dll", ".pyd"}:
                yield path.relative_to(root).as_posix(), path.read_bytes()
        for path in output.glob("*.exe"):
            yield path.name, path.read_bytes()
    else:
        from PyInstaller.archive.readers import CArchiveReader

        archive = CArchiveReader(str(output))
        for name in archive.toc:
            if PurePosixPath(normalize_name(name)).suffix in {".dll", ".pyd"}:
                yield name, archive.extract(name)
        yield output.name, output.read_bytes()


def verify_package(output: Path) -> None:
    """校验完整的直接和传递依赖，缺失时阻止脚本显示构建成功"""
    import pefile

    if not output.exists():
        raise RuntimeError(f"发布包不存在: {output}")
    imports: dict[str, set[str]] = {}
    for name, data in package_binaries(output):
        pe = pefile.PE(data=data, fast_load=True)
        try:
            # 延迟导入可能对应可选硬件功能，此处只校验启动所需的普通导入表
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            imports[name] = {
                entry.dll.decode("ascii") for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
            }
        finally:
            pe.close()

    bundled = {normalize_name(name) for name in imports}
    required = {"_ctypes.pyd", "pyqt6/qt6/bin/qt6core.dll", "pyqt6/qt6/bin/qt6widgets.dll"}
    absent = required - bundled
    if absent:
        raise RuntimeError("发布包缺少关键文件: " + ", ".join(sorted(absent)))

    system_dir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    system_libraries = {path.name.casefold() for path in system_dir.glob("*.dll")}
    private_libraries = {
        path.name.casefold() for directory in runtime_directories() for path in directory.glob("*.dll")
    }
    missing = find_missing_dependencies(imports, bundled, system_libraries, private_libraries)
    if missing:
        detail = "\n".join(f"  {owner} -> {dependency}" for owner, dependency in missing)
        raise RuntimeError("发布包仍有缺失的底层 DLL，禁止发布\n" + detail)
    print(f"[通过] 已检查 {len(imports)} 个原生文件，普通导入表依赖完整", flush=True)


def main() -> int:
    """提供共用的构建入口和发布包检查入口"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if os.name != "nt":
        print("[错误] 此构建检查入口仅支持 Windows", file=sys.stderr)
        return 1
    try:
        if len(sys.argv) < 3:
            raise RuntimeError("用法: build_runtime.py build <PyInstaller 参数> 或 verify <发布包路径>")
        if sys.argv[1] == "build":
            # 必须先注册 DLL 目录，再导入 PyInstaller 及其 ctypes 依赖
            configure_build_search(runtime_directories())
            from PyInstaller.__main__ import run

            run(sys.argv[2:])
        elif sys.argv[1] == "verify" and len(sys.argv) == 3:
            configure_build_search(runtime_directories())
            verify_package(Path(sys.argv[2]).resolve())
        else:
            raise RuntimeError("无效的构建检查参数")
    except Exception as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
