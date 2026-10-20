#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JDK 环境检测与自动安装脚本。

检测顺序：
  1. JAVA_HOME 环境变量 → 验证 bin/java.exe 是否存在
  2. PATH 中的 java 命令 → 反推 JDK 根目录
  3. 常见安装路径扫描 (C:/Program Files/Java/*, D:/Program Files/Java/*, ...)
  4. 项目内 api_project/bin/jdk/（之前自动安装过的）

如果都没找到，自动下载 Eclipse Temurin JDK 17 (LTS) 便携版并解压到 api_project/bin/jdk/。

用法：
  python check_jdk.py            # 检测或安装，输出 JDK 路径
  python check_jdk.py --quiet    # 只输出路径，不输出过程日志
  python check_jdk.py --version 17  # 指定 JDK 大版本 (默认 17)
"""

import os
import sys
import shutil
import subprocess
import zipfile
import tempfile
import urllib.request
import json
import re

# ── 配置 ──────────────────────────────────────────────
DEFAULT_JDK_VERSION = 17
ADOPTIUM_API = "https://api.adoptium.net/v3"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOCAL_JDK_DIR = os.path.join(PROJECT_ROOT, "api_project", "bin", "jdk")

# Windows 常见 JDK 安装路径
COMMON_JDK_PATHS = [
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Java"),
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Java"),
    r"D:\Program Files\Java",
    r"C:\Java",
    r"D:\Java",
    r"C:\jdk",
    r"D:\jdk",
    LOCAL_JDK_DIR,
]


def log(msg, quiet=False):
    if not quiet:
        print(msg, flush=True)


def find_java_exe(java_home):
    """在 JAVA_HOME 下查找 java.exe，返回完整路径或 None。"""
    if not java_home or not os.path.isdir(java_home):
        return None
    candidates = [
        os.path.join(java_home, "bin", "java.exe"),   # Windows
        os.path.join(java_home, "bin", "java"),        # Linux/Mac
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def check_java_version(java_exe):
    """运行 java -version，返回版本号字符串 (如 '17.0.6') 或 None。"""
    try:
        result = subprocess.run(
            [java_exe, "-version"],
            capture_output=True, text=True, timeout=15
        )
        # java -version 输出到 stderr
        output = result.stderr or result.stdout
        # 匹配: java version "17.0.6" / openjdk version "17.0.6"
        m = re.search(r'version "(\d+)', output)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def detect_jdk(quiet=False):
    """
    按优先级检测 JDK，返回 JAVA_HOME 路径或 None。
    """
    # ── 1. 检查 JAVA_HOME ──
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        java_exe = find_java_exe(java_home)
        if java_exe:
            ver = check_java_version(java_exe)
            log(f"[JDK] JAVA_HOME 已配置: {java_home}" + (f" (Java {ver})" if ver else ""), quiet)
            return java_home
        else:
            log(f"[JDK] JAVA_HOME={java_home} 但未找到 bin/java.exe，继续检测...", quiet)

    # ── 2. 检查 PATH 中的 java ──
    java_in_path = shutil.which("java") or shutil.which("java.exe")
    if java_in_path:
        ver = check_java_version(java_in_path)
        # 反推 JAVA_HOME: java.exe 在 <JDK>/bin/java.exe
        bin_dir = os.path.dirname(java_in_path)
        jdk_home = os.path.dirname(bin_dir)
        # 验证是否真的是 JDK 目录（而非 JRE）
        if find_java_exe(jdk_home):
            log(f"[JDK] 从 PATH 检测到 JDK: {jdk_home}" + (f" (Java {ver})" if ver else ""), quiet)
            return jdk_home
        # 某些情况 java.exe 直接在 bin 下但不是 JDK 结构
        log(f"[JDK] PATH 中的 java 位于 {java_in_path}，但无法确定 JDK 根目录，继续检测...", quiet)

    # ── 3. 扫描常见路径 ──
    for base in COMMON_JDK_PATHS:
        if not os.path.isdir(base):
            continue
        # base 可能直接是 JDK 根 (如 C:\Java\jdk-17) 或包含多个 JDK 子目录
        # 先检查 base 本身
        java_exe = find_java_exe(base)
        if java_exe:
            ver = check_java_version(java_exe)
            log(f"[JDK] 在 {base} 找到 JDK" + (f" (Java {ver})" if ver else ""), quiet)
            return base
        # 再检查子目录
        for name in sorted(os.listdir(base), reverse=True):
            sub = os.path.join(base, name)
            if not os.path.isdir(sub):
                continue
            java_exe = find_java_exe(sub)
            if java_exe:
                ver = check_java_version(java_exe)
                log(f"[JDK] 在 {sub} 找到 JDK" + (f" (Java {ver})" if ver else ""), quiet)
                return sub

    return None


def download_jdk(version=DEFAULT_JDK_VERSION, quiet=False):
    """
    从 Adoptium (Eclipse Temurin) 下载 JDK 便携版并解压到 api_project/bin/jdk/。
    返回解压后的 JDK 根目录路径。
    """
    # 确定操作系统架构
    import platform
    os_name = platform.system().lower()  # windows / linux / darwin
    arch = platform.machine().lower()    # amd64 / arm64

    # Adoptium API 架构映射
    arch_map = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    adoptium_arch = arch_map.get(arch, "x64")

    # 下载链接
    url = f"{ADOPTIUM_API}/binary/latest/{version}/ga/{os_name}/{adoptium_arch}/jdk/hotspot/normal/eclipse"

    log(f"[JDK] 未检测到已安装的 JDK，开始自动下载 Eclipse Temurin JDK {version}...", quiet)
    log(f"[JDK] 下载地址: {url}", quiet)

    # 创建临时文件
    tmp_zip = os.path.join(tempfile.gettempdir(), f"jdk-{version}-download.zip")

    try:
        # 下载
        log(f"[JDK] 正在下载... (文件较大，请耐心等待)", quiet)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB
            with open(tmp_zip, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and not quiet:
                        pct = downloaded * 100 // total
                        # 只在每 10% 时打印一次
                        if pct % 10 == 0:
                            print(f"\r[JDK] 下载进度: {pct}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)", end="", flush=True)
            if not quiet:
                print()  # 换行

        log(f"[JDK] 下载完成，开始解压...", quiet)

        # 解压
        os.makedirs(LOCAL_JDK_DIR, exist_ok=True)
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            zf.extractall(LOCAL_JDK_DIR)

        # 解压后的目录结构: jdk/<jdk-17.0.x+x>/
        # 找到实际 JDK 根目录
        entries = os.listdir(LOCAL_JDK_DIR)
        jdk_root = None
        for entry in entries:
            entry_path = os.path.join(LOCAL_JDK_DIR, entry)
            if os.path.isdir(entry_path) and find_java_exe(entry_path):
                jdk_root = entry_path
                break

        if not jdk_root:
            # 可能解压后直接就是 JDK 根
            if find_java_exe(LOCAL_JDK_DIR):
                jdk_root = LOCAL_JDK_DIR

        if not jdk_root:
            log(f"[JDK][ERROR] 解压完成但未找到 java.exe，目录内容: {entries}", quiet)
            return None

        ver = check_java_version(find_java_exe(jdk_root))
        log(f"[JDK] ✅ JDK 安装完成: {jdk_root}" + (f" (Java {ver})" if ver else ""), quiet)

        return jdk_root

    except Exception as e:
        log(f"[JDK][ERROR] 下载/安装失败: {e}", quiet)
        return None
    finally:
        # 清理临时文件
        if os.path.exists(tmp_zip):
            try:
                os.remove(tmp_zip)
            except Exception:
                pass


def ensure_jdk(version=DEFAULT_JDK_VERSION, quiet=False, auto_install=True):
    """
    主入口：检测 JDK，找不到则自动安装。
    返回 JAVA_HOME 路径或 None（完全失败时）。
    """
    # 先尝试检测
    jdk_home = detect_jdk(quiet=quiet)
    if jdk_home:
        return jdk_home

    # 检测失败，尝试自动安装
    if auto_install:
        jdk_home = download_jdk(version=version, quiet=quiet)
        if jdk_home:
            return jdk_home
        log("[JDK][ERROR] 自动安装 JDK 失败，请手动安装 JDK 17+ 并配置 JAVA_HOME 环境变量。", quiet)
        log("[JDK] 下载地址: https://adoptium.net/temurin/releases/?version=17", quiet)
    else:
        log("[JDK][ERROR] 未检测到 JDK 且未启用自动安装。", quiet)

    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="JDK 环境检测与自动安装")
    parser.add_argument("--version", type=int, default=DEFAULT_JDK_VERSION, help=f"JDK 大版本号 (默认 {DEFAULT_JDK_VERSION})")
    parser.add_argument("--quiet", action="store_true", help="只输出 JDK 路径")
    parser.add_argument("--check-only", action="store_true", help="仅检测不自动安装")
    args = parser.parse_args()

    jdk_home = ensure_jdk(
        version=args.version,
        quiet=args.quiet,
        auto_install=not args.check_only
    )

    if jdk_home:
        if args.quiet:
            print(jdk_home)
        else:
            log(f"\n[JDK] 最终路径: {jdk_home}", args.quiet)
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
