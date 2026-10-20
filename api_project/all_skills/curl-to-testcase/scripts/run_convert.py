#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
run_convert.py - convert_json.py 的无头包装器

在不启动 Tkinter GUI 的前提下，复用 convert_json.py 中 Controller 的全部转换逻辑，
将 cURL .txt 文件转换为接口测试用例代码和参数数据。

用法:
    python run_convert.py <curl_file_path>
    python run_convert.py <curl_file_path> --url-prefix https://api.example.com

输出:
    - api_project/case_data_files/*.json   接口参数数据
    - api_project/testcases/test_*.py      测试用例代码
    - api_project/config/*.py              host/allure/case 等配置
"""

import sys
import os
import types
import logging
import argparse
import glob as glob_module


# ============================================================
#  Tkinter 桩 (Stub)
#  convert_json.py 顶层有 `from tkinter import *` 等导入，
#  在无显示环境（如 Agent / CI）下会失败。
#  这里注入最小桩模块，使 import 能通过；
#  实际 GUI 类（WinGUI / Win）在无头模式下不会被实例化。
# ============================================================

def _setup_tkinter_stubs():
    """注入 tkinter 桩模块，让 convert_json.py 可以在无 GUI 环境下被 import。"""
    if 'tkinter' in sys.modules:
        return  # 真正的 tkinter 已可用，无需桩

    tk = types.ModuleType('tkinter')
    # WinGUI(Tk) 在模块加载时需要 Tk 存在
    tk.Tk = type('Tk', (), {})
    # StringVar 在 WinGUI.__init__ 中使用，但无头模式不会走到那里
    tk.StringVar = type('StringVar', (), {'__init__': lambda self, *a, **kw: None})
    sys.modules['tkinter'] = tk

    # tkinter.ttk
    ttk = types.ModuleType('tkinter.ttk')
    sys.modules['tkinter.ttk'] = ttk
    tk.ttk = ttk

    # tkinter.filedialog
    filedialog = types.ModuleType('tkinter.filedialog')
    filedialog.askopenfilename = lambda **kw: ''
    sys.modules['tkinter.filedialog'] = filedialog
    tk.filedialog = filedialog


# ============================================================
#  Mock UI
#  替代 Tkinter GUI，提供 Controller 所需的最小接口:
#    - file_path / url_prefix / allure_path  (StringVar 语义: get/set)
#    - tk_text_log                            (Text 语义: insert)
# ============================================================

class _MockStringVar:
    """模拟 tkinter.StringVar，仅保留 get / set。"""

    def __init__(self, value=''):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = str(value) if value is not None else ''


class _MockTextLog:
    """模拟 tkinter.Text，将日志输出到 stdout。"""

    def insert(self, position, text):
        # Controller 调用: self.ui.tk_text_log.insert('end', '...')
        print(text, end='')


class _MockUI:
    """模拟 convert_json.py 中 Win(WinGUI) 实例，供 Controller.init 使用。"""

    def __init__(self):
        self.file_path = _MockStringVar()
        self.url_prefix = _MockStringVar()
        self.allure_path = _MockStringVar()
        self.tk_text_log = _MockTextLog()


# ============================================================
#  主流程
# ============================================================

def _find_project_root():
    """
    从本脚本位置推算项目根目录。

    本脚本位于:
        <project_root>/api_project/all_skills/curl-to-testcase/scripts/run_convert.py
    向上 4 级即为项目根目录。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..', '..'))
    return project_root


def _find_curl_files(search_dir):
    """
    在 search_dir 及其子目录下模糊搜索 *curl*.txt 文件。
    返回匹配文件的绝对路径列表（按修改时间倒序）。
    """
    pattern = os.path.join(search_dir, '**', '*curl*.txt')
    matches = glob_module.glob(pattern, recursive=True)
    # 按修改时间倒序，最新的排前面
    matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return matches


def run_conversion(curl_file_path, url_prefix_override=None):
    """
    执行转换。

    Args:
        curl_file_path:   cURL .txt 文件的绝对路径
        url_prefix_override: 手动指定的 URL 前缀；为 None 时自动检测

    Returns:
        True  转换成功（或至少未抛出未捕获异常）
        False 转换失败
    """
    curl_file_path = os.path.abspath(curl_file_path)
    if not os.path.isfile(curl_file_path):
        print('[ERROR] cURL 文件不存在: {}'.format(curl_file_path))
        return False

    # ---- 1. 注入 tkinter 桩 ----
    _setup_tkinter_stubs()

    # ---- 2. 将项目根目录加入 sys.path ----
    project_root = _find_project_root()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # ---- 3. import convert_json ----
    try:
        import convert_json
    except Exception as e:
        print('[ERROR] 导入 convert_json 失败: {}'.format(e))
        print('        请确保在项目根目录环境下运行，且依赖包已安装。')
        import traceback
        traceback.print_exc()
        return False

    # ---- 4. 创建 logger ----
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )
    logger = logging.getLogger('convert_json')

    # ---- 5. 创建 Controller + MockUI ----
    controller = convert_json.Controller()
    mock_ui = _MockUI()
    controller.init(mock_ui, logger)

    # ---- 6. 设置 cURL 文件路径 ----
    controller.ui.file_path.set(curl_file_path)
    print('[INFO] cURL 文件: {}'.format(curl_file_path))

    # ---- 7. 设置 URL 前缀 ----
    if url_prefix_override:
        controller.ui.url_prefix.set(url_prefix_override)
        print('[INFO] URL 前缀 (手动指定): {}'.format(url_prefix_override))
    else:
        # 自动检测：调用 Controller.get_url_prefix 从 cURL 文件中提取
        controller.get_url_prefix(curl_file_path)
        detected = controller.ui.url_prefix.get()
        if not detected:
            print('[ERROR] 无法从 cURL 文件中自动检测 URL 前缀。')
            print('        请使用 --url-prefix <prefix> 手动指定。')
            return False
        print('[INFO] URL 前缀 (自动检测): {}'.format(detected))

    # ---- 8. 执行转换 ----
    print('[INFO] 开始转换...')
    try:
        controller.run_convert(None)
    except Exception as e:
        print('[ERROR] 转换过程发生未捕获异常: {}'.format(e))
        import traceback
        traceback.print_exc()
        return False

    # ---- 9. 检查输出 ----
    # run_convert 内部会吞掉异常，这里通过检查是否有新文件生成来判断
    case_data_dir = os.path.join(project_root, 'api_project', 'case_data_files')
    testcases_dir = os.path.join(project_root, 'api_project', 'testcases')

    json_count = len(glob_module.glob(os.path.join(case_data_dir, '*.json')))
    py_count = len(glob_module.glob(os.path.join(testcases_dir, 'test_*.py')))

    print('')
    print('[INFO] 转换流程结束。')
    print('       case_data_files/*.json : {} 个'.format(json_count))
    print('       testcases/test_*.py    : {} 个'.format(py_count))
    print('')
    print('[OK] 转换完成。')
    return True


def main():
    parser = argparse.ArgumentParser(
        description='convert_json.py 无头包装器 - 在不启动 GUI 的情况下转换 cURL 文件',
    )
    parser.add_argument(
        'curl_file',
        nargs='?',
        default=None,
        help='待转换的 cURL .txt 文件路径（不传则自动搜索当前目录）',
    )
    parser.add_argument(
        '--url-prefix',
        default=None,
        help='手动指定接口地址前缀 (如 https://api.example.com)，不传则自动检测',
    )
    parser.add_argument(
        '--search-dir',
        default=None,
        help='自动搜索 cURL 文件的根目录（默认为项目根目录）',
    )
    args = parser.parse_args()

    curl_file = args.curl_file

    # 如果未指定文件，自动搜索
    if not curl_file:
        search_dir = args.search_dir or _find_project_root()
        print('[INFO] 未指定 cURL 文件，正在搜索 {} ...'.format(search_dir))
        matches = _find_curl_files(search_dir)
        if not matches:
            print('[ERROR] 未在 {} 及子目录下找到 *curl*.txt 文件。'.format(search_dir))
            print('        请先将 cURL 命令保存为 .txt 文件（文件名包含 curl），再重试。')
            sys.exit(2)
        if len(matches) == 1:
            curl_file = matches[0]
            print('[INFO] 找到 cURL 文件: {}'.format(curl_file))
        else:
            print('[INFO] 找到多个 cURL 文件:')
            for i, f in enumerate(matches, 1):
                print('  [{}] {}'.format(i, f))
            # 默认使用第一个（最新修改的）
            curl_file = matches[0]
            print('[INFO] 默认使用第一个（最新修改）: {}'.format(curl_file))
            print('      如需指定其他文件，请直接传入文件路径。')
        print('')

    success = run_conversion(curl_file, args.url_prefix)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
