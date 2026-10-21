#!/usr/bin/env python3
"""
自动安装 Python 依赖脚本（支持交互式菜单 & 命令行参数）
功能：
  1. 扫描当前目录所有 .py 文件，自动提取第三方导入并安装
  2. 安装指定包或 requirements.txt 中的依赖
  3. 自适应镜像源（清华→华为→豆瓣→官方），自动重试
  4. 交互式菜单（无参数时启动），10秒无操作默认选1
"""
import os
import re
import sys
import subprocess
import argparse
import platform
import time
from importlib.metadata import distributions

# Windows 传统控制台可能仍使用 GBK，直接打印 emoji 会触发
# UnicodeEncodeError，使只读的 ``--check`` 命令异常退出。保留当前
# 控制台编码，仅将无法表示的字符替换，确保依赖检查始终能返回结果。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

# ===================== 镜像源配置（优先级从高到低） =====================
MIRRORS = [
    {"name": "清华", "url": "https://pypi.tuna.tsinghua.edu.cn/simple"},
    {"name": "华为", "url": "https://mirrors.huaweicloud.com/repository/pypi/simple"},
    {"name": "豆瓣", "url": "https://pypi.douban.com/simple"},
    {"name": "默认源", "url": "https://pypi.org/simple"},
]

# ===================== 标准库名单 =====================
STDLIB = {
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio", "asyncore",
    "atexit", "audioop", "base64", "bdb", "binascii", "binhex", "bisect", "builtins",
    "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs",
    "codeop", "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "cProfile", "crypt", "csv",
    "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
    "dis", "distutils", "doctest", "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
    "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nis",
    "nntplib", "numbers", "operator", "optparse", "os", "ossaudiodev", "pathlib",
    "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "posixpath", "pprint", "profile", "pstats", "pty", "pwd",
    "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random", "re",
    "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched",
    "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal",
    "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "sqlite3",
    "ssl", "stat", "statistics", "string", "stringprep", "struct", "subprocess",
    "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
    "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "trace", "traceback",
    "tracemalloc", "tty", "turtle", "turtledemo", "types", "typing",
    "unicodedata", "unittest", "urllib", "uu", "uuid", "venv", "warnings",
    "wave", "weakref", "webbrowser", "winreg", "winsound", "wsgiref",
    "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    "_thread", "__future__"
}

# ===================== 工具函数 =====================
def normalize_pkg_name(name: str) -> str:
    """PEP 503 包名规范化：requests_toolbelt -> requests-toolbelt，PyYAML -> pyyaml。
    避免因下划线/连字符/大小写差异把已安装的包误判为缺失，从而误触发联网安装。"""
    return re.sub(r'[-_.]+', '-', name).strip().lower()

def get_installed_packages():
    """返回当前环境中已安装的包名（PEP 503 规范化）集合"""
    return {normalize_pkg_name(dist.metadata["Name"]) for dist in distributions()}

def is_standard_lib(module_name):
    """判断模块名是否为标准库"""
    top_level = module_name.split('.')[0]
    return top_level in STDLIB

def extract_imports(file_path):
    """从 Python 文件中提取 import 的模块名，返回第三方顶层包名集合"""
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return imports

    patterns = [
        r'^\s*import\s+([\w\.]+)',
        r'^\s*from\s+([\w\.]+)\s+import'
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            module = match.group(1)
            top = module.split('.')[0]
            imports.add(top)

    return {name for name in imports if name and not name.startswith('.') and not is_standard_lib(name)}

def install_package(package_name, mirrors):
    """尝试安装单个包，按镜像源顺序重试，返回 (成功?, 使用的源名称)。
    每个源带 180s 超时，避免网络挂起时无限等待。"""
    for mirror in mirrors:
        url = mirror["url"]
        host = url.split("//")[1].split("/")[0]
        cmd = [sys.executable, "-m", "pip", "install", package_name,
               "-i", url, "--trusted-host", host]
        print(f"  尝试从 {mirror['name']} 源安装 {package_name} ...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                print(f"  ✓ {package_name} 安装成功 (来源: {mirror['name']})")
                return True, mirror["name"]
            else:
                err_msg = result.stderr.strip().split('\n')[-1] if result.stderr.strip() else "未知错误"
                print(f"  ✗ 安装失败: {err_msg}")
        except subprocess.TimeoutExpired:
            print(f"  ✗ 安装超时（180s），跳过该源: {package_name} ({mirror['name']})")
        except Exception as e:
            print(f"  ✗ 安装异常: {e}")
    print(f"  ❌ 所有镜像源均无法安装 {package_name}")
    return False, "所有源"

def install_packages(packages, mirrors, skip_installed=True):
    """批量安装包，返回 (成功列表, 失败列表)"""
    installed = get_installed_packages()
    success, failed = [], []
    for pkg in packages:
        pkg_norm = normalize_pkg_name(pkg)
        if skip_installed and pkg_norm in installed:
            print(f"⏭️ 跳过已安装: {pkg}")
            continue
        ok, source = install_package(pkg, mirrors)
        if ok:
            success.append(pkg)
        else:
            failed.append((pkg, source))
    return success, failed

# ===================== 主要功能函数 =====================
def scan_and_install(directory=".", mirrors=MIRRORS, skip_installed=True):
    """扫描目录下所有 .py 文件，提取并安装第三方依赖"""
    print(f"🔍 扫描目录: {os.path.abspath(directory)}")
    py_files = []

    # 需要跳过的目录（忽略大小写）
    skip_dirs = {
        'venv', '.venv', 'env', '.env', 'virtualenv',      # 虚拟环境
        '__pycache__', '.git', '.svn', '.hg',              # 缓存/版本控制
        'node_modules', '.idea', '.vscode', 'dist', 'build' # IDE/构建
    }

    for root, dirs, files in os.walk(directory):
        # 过滤掉不需要遍历的目录（直接修改 dirs 列表可避免进入这些目录）
        dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]

        try:
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))
        except PermissionError as e:
            print(f"  ⚠️ 跳过无权限目录: {root} ({e})")
            continue

        # 每扫描 100 个文件打印一次进度（避免看起来像卡死）
        if len(py_files) % 100 == 0 and py_files:
            print(f"  ... 已发现 {len(py_files)} 个 Python 文件")

    if not py_files:
        print("⚠️ 当前目录无 .py 文件")
        return

    print(f"📁 共找到 {len(py_files)} 个 Python 文件，开始提取依赖...")
    all_imports = set()
    for i, f in enumerate(py_files, 1):
        if i % 50 == 0:
            print(f"  ... 已分析 {i}/{len(py_files)} 个文件")
        imports = extract_imports(f)
        all_imports.update(imports)

    all_imports.discard("__future__")
    if not all_imports:
        print("ℹ️ 未检测到需要安装的第三方依赖")
        return

    print(f"📦 检测到依赖: {', '.join(sorted(all_imports))}")
    success, failed = install_packages(list(all_imports), mirrors, skip_installed)
    print(f"\n✅ 安装成功: {len(success)} 个")
    if failed:
        print(f"❌ 安装失败: {len(failed)} 个 => {[p for p,_ in failed]}")

def parse_requirements(file_path):
    """解析 requirements.txt，返回包名列表（去掉版本约束与注释）"""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    packages = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            pkg = re.split(r'[><=!~;]', line)[0].strip()
            if pkg:
                packages.append(pkg)
    return packages

def check_requirements(file_path):
    """仅检查依赖是否齐全（不联网、不安装、不调 pip）。
    返回 (是否齐全, 缺失包列表)；全部已装时输出跳过信息。"""
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False, [os.path.basename(file_path) + "(文件缺失)"]

    packages = parse_requirements(file_path)
    if not packages:
        print("⚠️ 文件中未找到有效依赖")
        return True, []

    installed = get_installed_packages()
    missing = [pkg for pkg in packages if normalize_pkg_name(pkg) not in installed]
    if missing:
        print(f"🔍 依赖检查：共 {len(packages)} 个，缺少 {len(missing)} 个 → {', '.join(missing)}")
        return False, missing
    print(f"✅ 依赖齐全：{len(packages)} 个均已安装，无需安装，跳过该步骤")
    return True, []

def install_from_file(file_path, mirrors=MIRRORS, skip_installed=True):
    """从 requirements.txt 文件安装依赖"""
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return

    packages = parse_requirements(file_path)

    if not packages:
        print("⚠️ 文件中未找到有效依赖")
        return

    print(f"📋 从 {file_path} 读取到 {len(packages)} 个依赖")
    success, failed = install_packages(packages, mirrors, skip_installed)
    print(f"\n✅ 安装成功: {len(success)} 个")
    if failed:
        print(f"❌ 安装失败: {len(failed)} 个 => {[p for p,_ in failed]}")

# ===================== 超时输入函数 =====================
def input_with_timeout(prompt, timeout=10, default='1'):
    """带超时的 input 函数，超时返回默认值"""
    print(prompt, end='', flush=True)
    if platform.system() == 'Windows':
        import msvcrt
        result = []
        start = time.time()
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch == '\r':  # Enter
                    print()
                    break
                elif ch == '\b':  # 退格
                    if result:
                        result.pop()
                        print('\b \b', end='', flush=True)
                else:
                    result.append(ch)
                    print(ch, end='', flush=True)
            else:
                time.sleep(0.05)
                if time.time() - start > timeout:
                    print(f"\n⏳ 超时，自动选择默认选项 [{default}]")
                    return default
        return ''.join(result)
    else:
        import select
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if rlist:
            return sys.stdin.readline().strip()
        else:
            print(f"\n⏳ 超时，自动选择默认选项 [{default}]")
            return default

# ===================== 交互式菜单 =====================
def interactive_mode():
    """显示交互式菜单，10秒无操作默认选择1，执行后退出"""
    print("\n" + "=" * 50)
    print("          Python 依赖自动安装工具")
    print("=" * 50)
    print("  [1] 默认模式（优先 requirements.txt，否则扫描代码）")
    print("  [2] 扫描代码安装（强制扫描 .py 文件）")
    print("  [3] 安装指定包（输入包名）")
    print("  [4] 安装指定文件（输入 requirements.txt 路径）")
    print("  [5] 强制重装所有依赖（不跳过已安装）")
    print("  [6] 不使用镜像源（仅官方 PyPI）")
    print("  [0] 退出")
    print("-" * 50)

    choice = input_with_timeout("请输入选项 [0-6] (10秒超时默认选1): ", timeout=10, default='1').strip()

    mirrors = MIRRORS
    skip_installed = True

    if choice == "0":
        print("👋 已退出")
        return
    elif choice == "1":
        req_file = os.path.join(".", "requirements.txt")
        if os.path.exists(req_file):
            print("📄 发现 requirements.txt，优先使用")
            install_from_file(req_file, mirrors, skip_installed)
        else:
            print("🔎 未找到 requirements.txt，将扫描代码安装依赖")
            scan_and_install(".", mirrors, skip_installed)
    elif choice == "2":
        scan_and_install(".", mirrors, skip_installed)
    elif choice == "3":
        pkgs = input("请输入要安装的包名（多个用空格分隔）: ").strip().split()
        if pkgs:
            install_packages(pkgs, mirrors, skip_installed)
        else:
            print("⚠️ 未输入包名")
    elif choice == "4":
        path = input("请输入 requirements.txt 文件路径: ").strip()
        install_from_file(path, mirrors, skip_installed)
    elif choice == "5":
        sub_choice = input("强制重装模式：\n  [a] 使用 requirements.txt\n  [b] 扫描代码\n  [c] 输入包名\n请选择: ").strip()
        if sub_choice == "a":
            path = input("requirements.txt 路径（默认 ./requirements.txt）: ").strip() or "requirements.txt"
            install_from_file(path, mirrors, skip_installed=False)
        elif sub_choice == "b":
            scan_and_install(".", mirrors, skip_installed=False)
        elif sub_choice == "c":
            pkgs = input("包名（多个用空格分隔）: ").strip().split()
            if pkgs:
                install_packages(pkgs, mirrors, skip_installed=False)
    elif choice == "6":
        mirrors = [MIRRORS[-1]]
        print("⚠️ 已切换到仅官方源模式")
        sub = input("请选择安装方式 [1/2/3/4]: ").strip()
        if sub == "1":
            req_file = os.path.join(".", "requirements.txt")
            if os.path.exists(req_file):
                install_from_file(req_file, mirrors, skip_installed)
            else:
                scan_and_install(".", mirrors, skip_installed)
        elif sub == "2":
            scan_and_install(".", mirrors, skip_installed)
        elif sub == "3":
            pkgs = input("包名: ").strip().split()
            if pkgs:
                install_packages(pkgs, mirrors, skip_installed)
        elif sub == "4":
            path = input("文件路径: ").strip()
            install_from_file(path, mirrors, skip_installed)
    else:
        print("❌ 无效选项，退出")

    print("🎉 所有操作完成")

# ===================== 主入口 =====================
def main():
    # 如果没有提供任何命令行参数，则进入交互模式（带超时）
    if len(sys.argv) == 1:
        interactive_mode()
        return

    # 原有命令行模式
    parser = argparse.ArgumentParser(
        description="自动安装 Python 依赖（自适应镜像源）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python auto_install.py                  # 交互式菜单（10秒超时默认选1）
  python auto_install.py -p flask requests  # 安装指定包
  python auto_install.py -r req.txt         # 安装指定文件中的依赖
  python auto_install.py -r req.txt --check # 仅检查依赖是否齐全，不安装
  python auto_install.py --scan              # 强制扫描代码安装
  python auto_install.py --force-reinstall   # 强制重装所有包
        """
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-p", "--packages", nargs="+", metavar="PKG",
                       help="指定要安装的包名（可多个）")
    group.add_argument("-r", "--requirement", metavar="FILE",
                       help="指定 requirements.txt 文件")
    group.add_argument("--scan", action="store_true",
                       help="强制扫描当前目录所有 .py 文件并安装依赖")
    parser.add_argument("--force-reinstall", action="store_true",
                        help="强制重新安装所有依赖（不跳过已安装的包）")
    parser.add_argument("--check", action="store_true",
                        help="仅检查依赖是否齐全（不联网不安装）：全部已装退出码 0，有缺失退出码 1")
    parser.add_argument("--no-mirror", action="store_true",
                        help="不使用镜像源，仅用默认 PyPI")

    args = parser.parse_args()

    # 选择镜像源
    mirrors = MIRRORS if not args.no_mirror else [MIRRORS[-1]]
    skip_installed = not args.force_reinstall

    # 仅检查模式：不联网、不安装，按退出码区分结果
    if args.check:
        req_file = args.requirement or os.path.join(".", "requirements.txt")
        ok, _missing = check_requirements(req_file)
        sys.exit(0 if ok else 1)

    print("🚀 开始自动安装依赖...")
    if args.packages:
        print(f"📦 安装指定包: {args.packages}")
        install_packages(args.packages, mirrors, skip_installed)
    elif args.requirement:
        install_from_file(args.requirement, mirrors, skip_installed)
    elif args.scan:
        scan_and_install(".", mirrors, skip_installed)
    else:
        # 默认行为：优先 requirements.txt，否则扫描
        req_file = os.path.join(".", "requirements.txt")
        if os.path.exists(req_file):
            print("📄 发现 requirements.txt，优先使用")
            install_from_file(req_file, mirrors, skip_installed)
        else:
            print("🔎 未找到 requirements.txt，将扫描代码安装依赖")
            scan_and_install(".", mirrors, skip_installed)

    print("🎉 所有操作完成")

if __name__ == "__main__":
    main()
