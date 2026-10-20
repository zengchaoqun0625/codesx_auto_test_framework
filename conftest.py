#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
根目录 conftest.py — 全局环境变量配置

功能：
  - 在 pytest 启动前自动检测并配置 JAVA_HOME / PATH / Allure 路径
  - 优先级：JAVA_HOME → PATH 中的 java → 常见安装路径 → 项目内自动安装的 JDK
  - 找不到则自动调用 check_jdk.py 下载 Eclipse Temurin JDK 17 便携版

此文件由 pytest 自动加载，无需手动 import。
python run_testcases.py 和直接 pytest 命令都会触发。
"""

import os
import sys
import shutil
import subprocess
import logging

logger = logging.getLogger("conftest.root")


def _configure_utf8_console():
    """Keep Chinese and emoji output safe on legacy Windows consoles.

    pytest captures output, but ``-s`` and the post-test notification flow
    still write to the process streams directly.  Windows may expose these as
    GBK streams, which turns an otherwise successful test into a
    ``UnicodeEncodeError`` when logging a status emoji.
    """
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                # Some redirected streams cannot be reconfigured.  Their
                # existing encoding is still preferable to failing startup.
                pass


_configure_utf8_console()


def _find_jdk():
    """检测 JDK 路径，返回 JAVA_HOME 或 None。"""
    # 1. 检查 JAVA_HOME 是否已正确配置
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home and os.path.isfile(os.path.join(java_home, "bin", "java.exe")):
        return java_home

    # 2. 检查 PATH 中的 java 命令
    java_in_path = shutil.which("java") or shutil.which("java.exe")
    if java_in_path:
        bin_dir = os.path.dirname(java_in_path)
        candidate = os.path.dirname(bin_dir)
        if os.path.isfile(os.path.join(candidate, "bin", "java.exe")):
            return candidate

    # 3. 扫描常见路径
    common_paths = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Java"),
        r"D:\Program Files\Java",
        r"C:\Java",
        r"D:\Java",
    ]
    for base in common_paths:
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base), reverse=True):
            sub = os.path.join(base, name)
            if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "bin", "java.exe")):
                return sub

    # 4. 检查项目内自动安装的 JDK
    project_root = os.path.dirname(os.path.abspath(__file__))
    local_jdk = os.path.join(project_root, "api_project", "bin", "jdk")
    if os.path.isdir(local_jdk):
        for name in sorted(os.listdir(local_jdk), reverse=True):
            sub = os.path.join(local_jdk, name)
            if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "bin", "java.exe")):
                return sub

    # 5. 调用 check_jdk.py 自动下载安装
    check_script = os.path.join(
        project_root, "api_project", "all_skills", "curl-to-testcase", "scripts", "check_jdk.py"
    )
    if os.path.isfile(check_script):
        try:
            result = subprocess.run(
                [sys.executable, check_script, "--quiet"],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.warning(f"自动安装 JDK 失败: {e}")

    return None


def _setup_env():
    """配置 Java 和 Allure 环境变量。"""
    project_root = os.path.dirname(os.path.abspath(__file__))

    # ── Java / JDK ──
    jdk_home = _find_jdk()
    if jdk_home:
        os.environ["JAVA_HOME"] = jdk_home
        os.environ["PATH"] = os.path.join(jdk_home, "bin") + ";" + os.environ.get("PATH", "")
        logger.info(f"JAVA_HOME = {jdk_home}")
    else:
        logger.error("未检测到 JDK，Allure 报告生成可能失败！请安装 JDK 17+ 并配置 JAVA_HOME")

    # ── Allure（固定路径）──
    allure_bin = os.path.join(project_root, "api_project", "bin", "allure", "bin")
    if os.path.isdir(allure_bin):
        os.environ["PATH"] = allure_bin + ";" + os.environ.get("PATH", "")
        logger.info(f"Allure PATH = {allure_bin}")
    else:
        logger.warning(f"Allure 目录不存在: {allure_bin}")


# ── pytest 钩子：在任何测试收集之前执行 ──
def pytest_configure(config):
    """pytest 启动时自动配置环境变量。"""
    _setup_env()
