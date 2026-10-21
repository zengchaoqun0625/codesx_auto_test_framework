#! /usr/bin/env python

import os
import re
import traceback
import subprocess
import platform
import json
from urllib.parse import urlparse
from tkinter import *
from tkinter import ttk
from tkinter.filedialog import askopenfilename
# 假设这些模块已经存在
from api_project.common.LOG import Logger
from api_project.common.ENV import ENV
from api_project import (
    CASE_CONFIG_PATH, CASE_SCRIPT_DIR_PATH,
    CASE_DATA_DIR_PATH, FEED, CONFIG_DIR_PATH,
    FAVICON_PATH, ALLURE_BIN_PATH
)
from api_project import TAB_SPACE
from saf.utils.Curl2Object import Curl, Template

__version__ = '.'.join(map(str, (0, 1, 5)))


class RequestProcessor:
    """请求处理器，封装请求参数处理的通用逻辑"""

    @staticmethod
    def get_request_type(request):
        """判断请求参数类型"""
        if 'formdata' in request and request['formdata']:
            return 'formdata'
        elif 'json' in request and request['json']:
            return 'json'
        elif 'data' in request and request['data']:
            return 'data'
        return 'default'

    @staticmethod
    def process_request_params(request_type, request_data):
        """处理请求参数，返回请求体和头部信息"""
        headers = request_data.get("headers", {}).copy()
        request_body = {}

        if request_type == 'formdata':
            request_body["data"] = request_data.get("formdata", {})
            headers["Content-Type"] = headers.get("Content-Type", "multipart/form-data")

        elif request_type == 'json':
            request_body["json"] = request_data.get("json", {})
            headers["Content-Type"] = headers.get("Content-Type", "application/json")

        elif request_type == 'data':
            data_content = request_data.get("data", {})
            if isinstance(data_content, str):
                try:
                    # 尝试解析为JSON
                    request_body["json"] = json.loads(data_content)
                    headers["Content-Type"] = headers.get("Content-Type", "application/json")
                except json.JSONDecodeError:
                    # 作为表单数据处理
                    request_body["data"] = data_content
                    headers["Content-Type"] = headers.get("Content-Type", "application/x-www-form-urlencoded")
            else:
                request_body["data"] = data_content

        return request_body, headers


class TestCaseGenerator:
    """测试用例生成器，封装测试代码生成逻辑"""

    @staticmethod
    def _generate_legacy_test_function(file_name_part, constant_name, request_type):
        """生成统一的测试函数模板，遍历所有 test_case（支持单文件多 case）"""
        return f"""
import allure
import pytest
import json
from ..config.user_variable import *
# from ..config.case_config import {constant_name}
#from api_project.testcases.conftest import allure_report,ALLURE_CONFIGS
from api_project.common.allure_decorator import allure_report, ALLURE_CONFIGS, allure_preset

@allure_preset("jqb_login_api")  # 使用预设配置,在commen文件的allure文件配置

@pytest.mark.parametrize("get_case_data", ["{file_name_part}.json"], indirect=True)
def test_{file_name_part.lower()}(get_case_data, api_request, assert_code, base_url, allure_reporter, request_processor):
    # 遍历所有测试用例（支持单文件多 case，按 logic 字段区分执行逻辑）
    for case_name, case in get_case_data["test_cases"].items():
        case_desc = case.get("description", "{file_name_part}接口测试")
        logic = case.get("logic", "query")  # 默认 query
        # allure.dynamic.title(f"{file_name_part}接口测试 - {{case_desc}}")

        full_url = ""
        method = ""
        request_body = {{}}
        request_params = {{}}
        headers = {{}}

        try:
            # 准备请求参数
            request_data = case["data"]
            full_url = f"{{base_url}}{{request_data.get('url', '')}}"
            method = request_data.get("method", "GET")
            request_type = case.get("request_type", "default")
            request_params = request_data.get("params", {{}})

            # 处理请求参数
            request_body, headers = request_processor.process_request_params(request_type, request_data)

            # 隐藏敏感信息的请求头（用于打印）
            safe_headers = {{k: v if k.lower() not in ['authorization', 'token', 'itoken'] else '***' for k, v in headers.items()}}

            # 打印请求参数
            print(f"\\n【请求】{{method}} {{full_url}}")
            if request_params:
                print(f"参数: {{json.dumps(request_params, ensure_ascii=False)}}")
            if request_body:
                print(f"请求体: {{json.dumps(request_body, ensure_ascii=False)}}")
            if headers:
                print(f"请求头: {{json.dumps(safe_headers, ensure_ascii=False)}}")

            # 报告记录请求
            allure.attach(f"{{method}} {{full_url}}", "请求信息", allure.attachment_type.TEXT)
            if request_body:
                allure.attach(json.dumps(request_body, indent=2, ensure_ascii=False), "请求体", allure.attachment_type.JSON)
            if headers:
                allure.attach(json.dumps(safe_headers, indent=2, ensure_ascii=False), "请求头", allure.attachment_type.JSON)

            # 发送请求
            response = api_request.send_request(
                url=full_url,
                method=method,
                verify=False,
                params=request_params,
                headers=headers,
                **request_body
            )

            # 打印响应
            print(f"【响应】状态码: {{response.status_code}}")
            try:
                print(f"响应体: {{json.dumps(response.json(), ensure_ascii=False)[:500]}}")
            except:
                print(f"响应体: {{response.text[:500]}}")

            # 报告记录响应
            allure.attach(str(response.status_code), "响应状态码", allure.attachment_type.TEXT)
            try:
                allure.attach(json.dumps(response.json(), indent=2, ensure_ascii=False), "响应体", allure.attachment_type.JSON)
            except:
                allure.attach(response.text, "响应体", allure.attachment_type.TEXT)

            # 断言（logic="expect_error" 时不固定状态码，此处 assert 200）
            assert_code.status_code(response, 200)
            print(f"✅ {{case_name}} - {{case_desc}} [logic={{logic}}] 执行成功")
            allure_reporter.add_custom_attachment("测试结果", f"✅ 执行成功: {{case_desc}}")

        except Exception as e:
            error_msg = f"❌ {{case_name}} - {{case_desc}} 执行失败: {{str(e)}}"
            print(error_msg)
            print(f"请求URL: {{full_url}}")
            allure_reporter.add_custom_attachment("测试结果", error_msg)

            # 失败时也记录请求信息
            if request_body:
                allure.attach(json.dumps(request_body, indent=2, ensure_ascii=False), "失败-请求体", allure.attachment_type.JSON)
            if headers:
                safe_headers = {{k: v if k.lower() not in ['authorization', 'token', 'itoken'] else '***' for k, v in headers.items()}}
                allure.attach(json.dumps(safe_headers, indent=2, ensure_ascii=False), "失败-请求头", allure.attachment_type.JSON)
            raise
"""

    @staticmethod
    def generate_test_function(file_name_part, constant_name, request_type):
        """Deprecated: JSON cases run only through testcases/test_api.py."""
        return ""


class WinGUI(Tk):
    def __init__(self):
        super().__init__()
        self.setup_style()
        self.__win()
        self.file_path = StringVar()
        self.file_path.set('请选择待转换的 cURL 文件...')
        self.tk_input_file_path = self.__tk_input_file_path(self)
        self.tk_button_choose_file_button = self.__tk_button_choose_file_button(self)
        self.tk_button_start_button = self.__tk_button_start_button(self)
        self.tk_text_log = self.__tk_text_log(self)
        self.tk_label_url_prefix_label = self.__tk_label_url_prefix_label(self)
        self.url_prefix = StringVar()
        self.url_prefix.set('请输入接口地址的前缀...')
        self.tk_input_url_prefix_input = self.__tk_input_url_prefix_input(self)
        self.tk_label_choose_allure_path_label = self.__tk_label_choose_allure_path_label(self)
        self.allure_path = StringVar()
        self.allure_path.set('双击或者右击选择 Allure 路径（必填项')
        self.tk_input_choose_allure_path_input = self.__tk_input_choose_allure_path_input(self)
        self.tk_label_frame_radio_frame = self.__tk_label_frame_radio_frame(self)
        self.radio_value = IntVar()
        self.radio_value.set(1)
        self.tk_radio_button_choose_ptest_allure_radio = self.__tk_radio_button_choose_ptest_allure_radio(
            self.tk_label_frame_radio_frame)
        self.tk_radio_button_choose_ptest_allure_at_radio = self.__tk_radio_button_choose_ptest_allure_at_radio(
            self.tk_label_frame_radio_frame)
        self.create_copy_menu()

    def setup_style(self):
        """设置现代风格的 UI 样式和主题"""
        style = ttk.Style()
        style.theme_use('clam')

        # 调色板
        bg_color = "#f8f9fa"
        primary_color = "#2e7d32"
        secondary_color = "#4caf50"  # 浅绿色
        accent_color = "#ff6f00"
        success_color = "#4caf50"
        info_color = "#26a69a"
        warning_color = "#ffd600"
        danger_color = "#d32f2f"
        light_color = "#ffffff"
        dark_color = "#212121"

        # 全局样式
        style.configure('.',
                        background=bg_color,
                        foreground=dark_color,
                        font=('Microsoft YaHei', 10),
                        borderwidth=1)

        # 框架样式
        style.configure('TFrame', background=bg_color)
        style.configure('Card.TFrame',
                        background=light_color,
                        bordercolor="#e0e0e0",
                        relief="solid",
                        borderwidth=1)

        # 标签样式
        style.configure('TLabel',
                        background=bg_color,
                        font=('Microsoft YaHei', 10))
        style.configure('Title.TLabel',
                        font=('Microsoft YaHei', 14, 'bold'),
                        foreground=primary_color)

        # 按钮样式
        button_settings = {
            'padding': (12, 4),
            'relief': 'flat',
            'focuscolor': 'none',
            'borderwidth': 0,
            'font': ('Microsoft YaHei', 10, 'bold'),
            'borderradius': 20  # 设置按钮圆角
        }

        style.map('TButton',
                  background=[('active', primary_color), ('!disabled', primary_color)],
                  foreground=[('!disabled', light_color)])

        for color_style, color in [
            ('primary', primary_color),
            ('success', success_color),
            ('info', info_color),
            ('warning', warning_color),
            ('danger', danger_color)
        ]:
            style.map(f'{color_style}.TButton',
                      background=[('active', color), ('!disabled', color)],
                      foreground=[('!disabled', light_color)])
        style.configure('TButton', **button_settings)

        # 输入控件样式
        entry_config = {
            'padding': 8,
            'relief': 'flat',
            'fieldbackground': light_color,
            'bordercolor': '#e0e0e0',
            'lightcolor': '#e0e0e0',
            'darkcolor': '#e0e0e0',
            'borderradius': 20  # 设置输入框圆角
        }
        style.configure('TEntry', **entry_config)

        # 下拉框样式 - 设置为浅绿色背景
        combobox_config = {
            'padding': 8,
            'relief': 'flat',
            'fieldbackground': '#e8f5e9',  # 浅绿色背景
            'bordercolor': '#e0e0e0',
            'lightcolor': '#e0e0e0',
            'darkcolor': '#e0e0e0',
            'arrowsize': 14,
            'arrowcolor': primary_color,
            'borderradius': 20  # 设置下拉框圆角
        }
        style.configure('TCombobox', **combobox_config)
        style.map('TCombobox',
                  fieldbackground=[('readonly', '#e8f5e9')],
                  selectbackground=[('readonly', '#e8f5e9')],
                  selectforeground=[('!disabled', dark_color)])

        # 进度条样式
        style.configure('TProgressbar',
                        thickness=24,
                        troughcolor='#eeeeee',
                        background=primary_color,
                        bordercolor='#eeeeee',
                        lightcolor=primary_color,
                        darkcolor=primary_color)

        # Treeview 样式
        treeview_config = {
            'background': light_color,
            'fieldbackground': light_color,
            'foreground': dark_color,
            'rowheight': 34,
            'bordercolor': '#e0e0e0',
            'font': ('Microsoft YaHei', 10),
            'padding': 5,
            'highlightthickness': 0
        }

        style.configure('Treeview', **treeview_config)
        style.configure('Treeview.Heading',
                        background=primary_color,
                        foreground=light_color,
                        padding=8,
                        relief='flat',
                        font=('Microsoft YaHei', 10, 'bold'))
        style.map('Treeview',
                  background=[('selected', '#e8f5e9')],
                  foreground=[('selected', dark_color)])

        # 标签框架样式
        style.configure('TLabelframe',
                        background=bg_color,
                        bordercolor='#e0e0e0',
                        relief='solid',
                        borderwidth=1)
        style.configure('TLabelframe.Label',
                        background=bg_color,
                        foreground=primary_color,
                        font=('Microsoft YaHei', 11, 'bold'))

        # 滚动条样式
        style.configure('Vertical.TScrollbar',
                        background=secondary_color,
                        troughcolor=light_color,
                        bordercolor=secondary_color,
                        arrowsize=14,
                        gripcount=0)

        style.configure('Horizontal.TScrollbar',
                        background=secondary_color,
                        troughcolor=light_color,
                        bordercolor=secondary_color,
                        arrowsize=14,
                        gripcount=0)

        style.map('TScrollbar',
                  background=[('active', primary_color), ('!disabled', secondary_color)],
                  troughcolor=[('!disabled', light_color)])

    def __win(self):
        self.title("小曾Api")
        try:
            self.iconbitmap(FAVICON_PATH)
        except Exception as e:
            # 处理图标加载失败的情况
            print(f"图标加载失败: {e}")

        # 设置窗口大小、居中
        width = 800
        height = 700
        screenwidth = self.winfo_screenwidth()
        screenheight = self.winfo_screenheight()
        geometry = '%dx%d+%d+%d' % (width, height, (screenwidth - width) / 2, (screenheight - height) / 2)
        self.geometry(geometry)

        self.minsize(width=width, height=height)

    def scrollbar_autohide(self, vbar, hbar, widget):
        """自动隐藏滚动条"""

        def show():
            if vbar:
                vbar.lift(widget)
            if hbar:
                hbar.lift(widget)

        def hide():
            if vbar:
                vbar.lower(widget)
            if hbar:
                hbar.lower(widget)

        hide()
        widget.bind("<Enter>", lambda e: show())
        if vbar:
            vbar.bind("<Enter>", lambda e: show())
        if vbar:
            vbar.bind("<Leave>", lambda e: hide())
        if hbar:
            hbar.bind("<Enter>", lambda e: show())
        if hbar:
            hbar.bind("<Leave>", lambda e: hide())
        widget.bind("<Leave>", lambda e: hide())

    def v_scrollbar(self, vbar, widget, x, y, w, h, pw, ph):
        widget.configure(yscrollcommand=vbar.set)
        vbar.config(command=widget.yview)
        vbar.place(relx=(w + x) / pw, rely=y / ph, relheight=h / ph, anchor='ne')

    def h_scrollbar(self, hbar, widget, x, y, w, h, pw, ph):
        widget.configure(xscrollcommand=hbar.set)
        hbar.config(command=widget.xview)
        hbar.place(relx=x / pw, rely=(y + h) / ph, relwidth=w / pw, anchor='sw')

    def create_bar(self, master, widget, is_vbar, is_hbar, x, y, w, h, pw, ph):
        vbar, hbar = None, None
        if is_vbar:
            vbar = Scrollbar(master)
            self.v_scrollbar(vbar, widget, x, y, w, h, pw, ph)
        if is_hbar:
            hbar = Scrollbar(master, orient="horizontal")
            self.h_scrollbar(hbar, widget, x, y, w, h, pw, ph)
        self.scrollbar_autohide(vbar, hbar, widget)

    def __tk_input_file_path(self, parent):
        ipt = ttk.Entry(parent, textvariable=self.file_path)
        ipt.place(relx=0.0500, rely=0.0270, relwidth=0.7025, relheight=0.0811)
        ipt.bind("<Button-3>", self.show_copy_menu)
        return ipt

    def __tk_button_choose_file_button(self, parent):
        btn = ttk.Button(parent, text="选择文件", takefocus=False, style='primary.TButton')
        btn.place(relx=0.7750, rely=0.0270, relwidth=0.1725, relheight=0.0811)
        return btn

    def __tk_button_start_button(self, parent):
        btn = ttk.Button(parent, text="开 始", takefocus=False, style='primary.TButton')
        btn.place(relx=0.5525, rely=0.4324, relwidth=0.3925, relheight=0.2243)
        return btn

    def __tk_text_log(self, parent):
        text = Text(parent)
        text.place(relx=0.0000, rely=0.7297, relwidth=1.0000, relheight=0.2703)
        self.create_bar(parent, text, True, True, 0, 270, 400, 100, 400, 370)
        return text

    def __tk_label_url_prefix_label(self, parent):
        label = ttk.Label(parent, text="URL 前缀：", anchor="center")
        label.place(relx=0.0500, rely=0.1541, relwidth=0.1625, relheight=0.0811)
        return label

    def __tk_input_url_prefix_input(self, parent):
        ipt = ttk.Entry(parent, textvariable=self.url_prefix)
        ipt.place(relx=0.2125, rely=0.1541, relwidth=0.7325, relheight=0.0811)
        return ipt

    def __tk_label_choose_allure_path_label(self, parent):
        label = ttk.Label(parent, text="Allure 配置：", anchor="center")
        label.place(relx=0.0500, rely=0.2811, relwidth=0.1630, relheight=0.0811)
        return label

    def __tk_input_choose_allure_path_input(self, parent):
        ipt = ttk.Entry(parent, textvariable=self.allure_path)
        ipt.place(relx=0.2150, rely=0.2811, relwidth=0.7325, relheight=0.0811)
        ipt.bind("<Button-3>", self.show_copy_menu)
        return ipt

    def __tk_label_frame_radio_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="模板选择")
        frame.place(relx=0.0500, rely=0.3919, relwidth=0.4400, relheight=0.3000)
        return frame

    def __tk_radio_button_choose_ptest_allure_radio(self, parent):
        rb = Radiobutton(parent, text="pytest_allure", value=1, variable=self.radio_value)
        rb.place(relx=0.1136, rely=0.0180, relwidth=0.7614, relheight=0.2703)
        return rb

    def __tk_radio_button_choose_ptest_allure_at_radio(self, parent):
        rb = Radiobutton(parent, text="pytest_allure_at", value=2, variable=self.radio_value)
        rb.place(relx=0.1136, rely=0.4505, relwidth=0.7841, relheight=0.2703)
        return rb

    def create_copy_menu(self):
        self.copy_menu = Menu(self, tearoff=0)
        self.copy_menu.add_command(label="复制", command=self.copy_file_path)

    def show_copy_menu(self, event):
        self.copy_menu.post(event.x_root, event.y_root)

    def copy_file_path(self):
        widget = self.focus_get()
        if isinstance(widget, ttk.Entry):
            file_path = widget.get()
            self.clipboard_clear()
            self.clipboard_append(file_path)


class Win(WinGUI):
    def __init__(self, controller):
        self.ctl = controller
        super().__init__()
        self.__event_bind()
        self.__style_config()
        self.ctl.init(self, Logger())

    def __event_bind(self):
        self.tk_button_choose_file_button.bind('<Button-1>', self.ctl.choose_file)
        self.tk_button_start_button.bind('<Button-1>', self.ctl.run_convert)
        self.tk_text_log.bind('<Delete>', self.ctl.clear_log)
        self.tk_input_choose_allure_path_input.bind('<Button-3>', self.ctl.choose_allure_path)
        self.tk_input_choose_allure_path_input.bind('<Double-Button-1>', self.ctl.choose_allure_path)

    def __style_config(self):
        pass


class Controller:
    ui: Win
    logger: Logger

    def __init__(self):
        pass

    def init(self, ui, logger):
        """初始化控制器"""
        self.ui = ui
        self.logger = logger
        self.find_allure_path()

    def get_url_prefix(self, file_path):
        '''正则获取全部 URL 的前缀中最多的一个'''
        all_urls = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines:
                    if '-H' not in line and '--header' not in line:
                        match = re.search(r'http[^\'"\s]+|https[^\'"\s]+', line)
                        if match:
                            all_urls.append(match.group())

            # 统计每个链接的前缀次数
            url_counts = {}
            for url in all_urls:
                parsed = urlparse(url)
                prefix = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ''
                if prefix:
                    url_counts[prefix] = url_counts.get(prefix, 0) + 1

            if url_counts:  # 检查是否有有效前缀
                max_count_url = max(url_counts, key=url_counts.get)
                if max_count_url.endswith('/'):
                    max_count_url = max_count_url[:-1]
                self.ui.url_prefix.set(max_count_url)

        except Exception as e:
            self.ui.tk_text_log.insert('end', f"提取URL前缀失败: {str(e)}\n")
            self.logger.error(f"提取URL前缀失败: {traceback.format_exc()}")

    def choose_file(self, evt):
        try:
            self.file_path = askopenfilename(
                initialdir='~/Desktop',
                title='打开 cURL 命令文件',
                filetypes=[('All Files', '*.*')]
            )
            if self.file_path:
                self.ui.file_path.set(self.file_path)
                self.ui.tk_text_log.insert('end', f"您选择的文件是：{self.file_path}\n")
                self.logger.info(f"您选择的文件是：{self.file_path}")
                # 读取文件内容获取所有 url 的前缀
                self.get_url_prefix(self.file_path)
            else:
                self.ui.tk_text_log.insert('end', "您取消了选择\n")
                self.logger.info("您取消了选择")
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"选择文件失败: {str(e)}\n")
            self.logger.error(f"选择文件失败: {traceback.format_exc()}")

    def extract_variables(self, request):
        """提取请求中的变量，兼容多种数据类型"""
        variables = {}

        # 处理params
        if 'params' in request and isinstance(request['params'], dict):
            for key, value in request['params'].items():
                variables[key] = value

        # 处理data（支持字典、列表、字符串）
        if 'data' in request:
            data = request['data']
            if isinstance(data, dict):
                for key, value in data.items():
                    variables[key] = value
            elif isinstance(data, list):
                for idx, item in enumerate(data):
                    variables[f"item_{idx}"] = item
            elif isinstance(data, str):
                try:
                    data_obj = json.loads(data)
                    if isinstance(data_obj, dict):
                        for key, value in data_obj.items():
                            variables[key] = value
                    elif isinstance(data_obj, list):
                        for idx, item in enumerate(data_obj):
                            variables[f"item_{idx}"] = item
                except json.JSONDecodeError:
                    variables['raw_data'] = data

        # 处理json
        if 'json' in request and isinstance(request['json'], dict):
            for key, value in request['json'].items():
                variables[key] = value

        # 处理formdata
        if 'formdata' in request and isinstance(request['formdata'], dict):
            for key, value in request['formdata'].items():
                variables[key] = value

        return variables

    def normalize_request_data(self, request):
        """标准化请求数据，确保JSON、data、formdata格式正确"""
        normalized = request.copy()

        # 处理JSON数据
        if 'json' in normalized and normalized['json']:
            # 如果是字符串，尝试解析为JSON对象
            if isinstance(normalized['json'], str):
                try:
                    normalized['json'] = json.loads(normalized['json'])
                except json.JSONDecodeError:
                    # 如果解析失败，保留原始字符串
                    pass

        # 处理data数据
        if 'data' in normalized and normalized['data']:
            # 保持data为字符串格式，不解析
            if not isinstance(normalized['data'], str):
                # 如果不是字符串，转换为JSON字符串
                normalized['data'] = json.dumps(normalized['data'], ensure_ascii=False)

        # 处理formdata数据
        if 'formdata' in normalized and normalized['formdata']:
            # 确保formdata是字典格式
            if isinstance(normalized['formdata'], str):
                try:
                    # 尝试从字符串解析为字典
                    normalized['formdata'] = json.loads(normalized['formdata'])
                except json.JSONDecodeError:
                    # 如果解析失败，创建键值对字典
                    form_data = {}
                    for item in normalized['formdata'].split('&'):
                        if '=' in item:
                            key, value = item.split('=', 1)
                            form_data[key] = value
                    normalized['formdata'] = form_data

        # cURL 抓包通常携带真实鉴权凭据。测试资产只能保留环境变量
        # 引用，避免 token、Cookie 或 API key 被写入 JSON / 报告 / Git。
        headers = normalized.get('headers')
        if isinstance(headers, dict):
            sensitive_header_envs = {
                'authorization': '${API_TOKEN}',
                'token': '${API_ITOKEN}',
                'itoken': '${API_ITOKEN}',
                'cookie': '${API_COOKIE}',
                'x-api-key': '${API_KEY}',
                'api-key': '${API_KEY}',
                'x-auth-token': '${API_TOKEN}',
            }
            normalized['headers'] = {
                key: sensitive_header_envs.get(str(key).strip().lower(), value)
                for key, value in headers.items()
            }

        return normalized

    def run_convert(self, evt):
        try:
            ENV.load()
            file_path = self.ui.file_path.get()

            if file_path in ['', '请选择待转换的 cURL 文件...']:
                self.ui.tk_text_log.insert('end', '还未选择需要转换的文件\n')
                self.logger.error('还未选择需要转换的文件')
                return

            # Curl2Object needs HOST while parsing but the converter must not
            # persist it into host_config.py.  Keep the captured origin in the
            # generated JSON so the case remains executable without changing
            # the active environment configuration.
            url_prefix = self.ui.url_prefix.get().rstrip('/')
            if url_prefix in ['', '请输入接口地址的前缀...']:
                raise ValueError('接口地址前缀不能为空；请通过 --url-prefix 指定')

            # Conversion is data-only.  Host selection, Allure paths and
            # user variables belong to the configuration layer and must not
            # be overwritten from a captured request.

            self.ui.tk_text_log.insert('end', '已经加载环境变量\n')
            self.logger.info('已经加载环境变量')

            # 加载并转换cURL文件
            curl = Curl()
            previous_host = os.environ.get('HOST')
            os.environ['HOST'] = url_prefix
            try:
                curl.load(curl_file_path=file_path)
            finally:
                if previous_host is None:
                    os.environ.pop('HOST', None)
                else:
                    os.environ['HOST'] = previous_host
            self.ui.tk_text_log.insert('end', f'已加载文件[{os.path.split(file_path)[1]}]，正在进行转换\n')
            self.logger.info(f'已加载文件[{os.path.split(file_path)[1]}]，正在进行转换')

            generated_case_files = []

            for request in curl.group:
                # 标准化请求数据，确保格式正确
                normalized_request = self.normalize_request_data(request)
                request_path = str(normalized_request.get('url', ''))
                if not request_path.startswith(('http://', 'https://')):
                    normalized_request['url'] = f"{url_prefix}/{request_path.lstrip('/')}"

                # 生成文件名
                file_name_part = self._generate_file_name(normalized_request)

                # 移除不需要的键
                for key in ['api_name']:
                    if key in normalized_request:
                        del normalized_request[key]

                # 生成测试数据JSON
                case_file = self._generate_test_data_json(
                    file_name_part, normalized_request
                )
                if not case_file:
                    raise RuntimeError(f"未能生成用例数据: {file_name_part}.json")
                generated_case_files.append(case_file)

            if not generated_case_files:
                raise RuntimeError("cURL 文件中没有可转换的请求")
            return {"case_files": generated_case_files}

        except Exception as e:
            self.ui.tk_text_log.insert('end', f"转换过程出错: {str(e)}\n")
            self.logger.error(f"转换过程出错: {traceback.format_exc()}")
            raise

    def _write_host_config(self, url_prefix):
        """写入host配置文件"""
        try:
            code = f'{FEED}'.join([
                "#! /usr/bin/env python",
                "'''",
                "Auther      : alvin.zeng",
                "Email       : zengjiangtaoasd@qq.com",
                "createTime  : 2024/11/21 19:24",
                "fileName    : host_config.py",
                "'''",
                "",
                "class HOST(object):",
                f"{TAB_SPACE}TEST_HOST: str = '{url_prefix}'",
                f"{TAB_SPACE}PRO_HOST: str = '{url_prefix}'",
                f"{TAB_SPACE}CURRENT_HOST: str = TEST_HOST",
            ])
            with open(os.path.join(CONFIG_DIR_PATH, 'host_config.py'), 'w', encoding='utf-8') as f:
                f.write(code)
            self.ui.tk_text_log.insert('end', '已经重写 host_config.py\n')
            self.logger.info('已经重写 host_config.py')
            os.environ['HOST'] = url_prefix
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"写入host配置失败: {str(e)}\n")
            self.logger.error(f"写入host配置失败: {traceback.format_exc()}")

    def _write_allure_config(self, allure_path):
        """写入allure配置文件"""
        try:
            code = f'{FEED}'.join([
                "#! /usr/bin/env python",
                "'''",
                "Auther      : alvin.zeng",
                "Email       : zengjiangtaoasd@qq.com",
                "createTime  : 2024/11/25 10:51",
                "fileName    : allure_config.py",
                "'''",
                "",
                "from ..common.Network import get_local_ip",
                "",
                "class Allure(object):",
                f"{TAB_SPACE}PATH    : str = r'{allure_path}'",
                f"{TAB_SPACE}IP      : str = get_local_ip()",
                f"{TAB_SPACE}PORT    : int = 9797",
            ])
            with open(os.path.join(CONFIG_DIR_PATH, 'allure_config.py'), 'w', encoding='utf-8') as f:
                f.write(code)
            self.ui.tk_text_log.insert('end', '已经重写 allure_config.py\n')
            self.logger.info('已经重写 allure_config.py')
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"写入allure配置失败: {str(e)}\n")
            self.logger.error(f"写入allure配置失败: {traceback.format_exc()}")

    def _prepare_case_config_header(self):
        """准备case配置文件头部"""
        return [
            "#! /usr/bin/env python",
            "'''",
            "Auther      : alvin.zeng",
            "Email       : zengjiangtaoasd@qq.com",
            "createTime  : 2024/11/21 19:24",
            "fileName    : case_config.py",
            "'''",
            "import os",
            f"from api_project import CASE_DATA_DIR_PATH",
            ""
        ]

    def _generate_file_name(self, request):
        """生成文件名"""
        url = request.get('url', '')
        if url:
            path_parts = urlparse(url).path.strip('/').split('/')
            if len(path_parts) >= 2:
                file_name_part = "_".join(path_parts[-2:])
            elif len(path_parts) == 1:
                file_name_part = f"_{path_parts[0]}"
            else:
                file_name_part = "_default"
        else:
            file_name_part = "_default"

        # 处理特殊字符
        return file_name_part.replace('-', '_')

    def _generate_test_script(self, file_name_part, constant_name, request):
        """生成测试脚本文件"""
        try:
            request_type = RequestProcessor.get_request_type(request)
            CASE_SCRIPT = os.path.join(CASE_SCRIPT_DIR_PATH, f"test_{file_name_part.lower()}.py")

            with open(CASE_SCRIPT, 'w', encoding='utf-8') as fw:
                # 写入通用测试函数模板
                test_code = TestCaseGenerator.generate_test_function(
                    file_name_part, constant_name, request_type
                )
                fw.write(test_code)

            self.ui.tk_text_log.insert('end', f"test_{file_name_part.lower()}.py 写入成功！\n")
            self.logger.info(f"test_{file_name_part.lower()}.py 写入成功！")

        except Exception as e:
            self.ui.tk_text_log.insert('end',
                                       f"test_{file_name_part.lower()}.py 写入失败：{str(e)}\n")
            self.logger.error(f"test_{file_name_part.lower()}.py 写入失败：{traceback.format_exc()}")

    def _generate_test_data_json(self, file_name_part, request):
        """生成测试数据JSON文件，确保JSON、data、formdata格式正确"""
        try:
            CASE_DATA = os.path.join(CASE_DATA_DIR_PATH, f"{file_name_part}.json")
            if not os.path.isdir(CASE_DATA_DIR_PATH):
                os.makedirs(CASE_DATA_DIR_PATH, exist_ok=True)

            # 获取请求类型
            request_type = RequestProcessor.get_request_type(request)

            # 创建JSON数据结构，确保各种参数格式正确
            json_data = {
                "test_cases": {
                    "test_case_1": {
                        "description": f"{file_name_part}接口测试",
                        "request_type": request_type,
                        "logic": "query",
                        "data": request  # 已标准化的请求数据
                    }
                }
            }

            # 检查文件是否存在，如果存在则读取并追加数据
            if os.path.isfile(CASE_DATA):
                with open(CASE_DATA, 'r', encoding='utf-8') as fr:
                    existing_data = json.load(fr)

                    # 检查是否已存在相同数据
                    is_duplicate = any(
                        case_data["data"] == request
                        for case_data in existing_data["test_cases"].values()
                    )

                    if not is_duplicate:
                        # 生成新的测试用例名称
                        new_case_num = len(existing_data["test_cases"]) + 1
                        new_case_name = f"test_case_{new_case_num}"
                        existing_data["test_cases"][new_case_name] = {
                            "description": f"{file_name_part}接口测试用例{new_case_num}",
                            "request_type": request_type,
                            "logic": "query",
                            "data": request
                        }
                        json_data = existing_data

            # 写入JSON文件，确保缩进和编码正确
            with open(CASE_DATA, 'w', encoding='utf-8') as fw:
                json.dump(json_data, fw, ensure_ascii=False, indent=4)

            self.ui.tk_text_log.insert('end', f"{file_name_part}.json 写入成功！\n")
            self.logger.info(f"{file_name_part}.json 写入成功！")
            return CASE_DATA

        except Exception as e:
            self.ui.tk_text_log.insert('end', f"{file_name_part}.json 写入失败：{str(e)}\n")
            self.logger.error(f"{file_name_part}.json 写入失败：{traceback.format_exc()}")
            return None

    def _write_case_config(self, case_config_lines):
        """写入case配置文件"""
        try:
            with open(os.path.join(CONFIG_DIR_PATH, 'case_config.py'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(case_config_lines))
            self.ui.tk_text_log.insert('end', '已经重写 case_config.py\n')
            self.logger.info('已经重写 case_config.py')
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"写入case配置失败: {str(e)}\n")
            self.logger.error(f"写入case配置失败: {traceback.format_exc()}")

    def _write_user_variables(self, all_variables):
        """写入用户变量文件"""
        try:
            user_variable_lines = [
                "#! /usr/bin/env python",
                "'''",
                "Auther      : alvin.zeng",
                "Email       : zengjiangtaoasd@qq.com",
                "createTime  : 2024/11/21 19:24",
                "fileName    : user_variable.py",
                "'''",
                ""
            ]
            for key, value in all_variables.items():
                user_variable_lines.append(f"{key} = {repr(value)}")

            with open(os.path.join(CONFIG_DIR_PATH, 'user_variable.py'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(user_variable_lines))

            self.ui.tk_text_log.insert('end', '已经生成 user_variable.py\n')
            self.logger.info('已经生成 user_variable.py')

        except Exception as e:
            self.ui.tk_text_log.insert('end', f"写入用户变量失败: {str(e)}\n")
            self.logger.error(f"写入用户变量失败: {traceback.format_exc()}")

    def clear_log(self, evt):
        try:
            self.ui.tk_text_log.delete('1.0', END)
        except Exception as e:
            print(f"清除日志失败: {e}")

    def find_allure_path(self):
        try:
            if ALLURE_BIN_PATH:
                self.ui.allure_path.set(ALLURE_BIN_PATH)
            else:
                system = platform.system()
                if system == "Windows":
                    result = subprocess.run(
                        ["where", "allure.bat"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    paths = result.stdout.strip().split("\n")
                    allure_path = next((x for x in paths if str(x).endswith('allure.bat')), None)
                    if allure_path:
                        self.ui.allure_path.set(allure_path)

                elif system in ["Linux", "Darwin"]:
                    result = subprocess.run(
                        ["which", "allure"],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    paths = [result.stdout.strip()]
                    allure_path = next((x for x in paths if str(x).endswith('allure')), None)
                    if allure_path:
                        self.ui.allure_path.set(allure_path)

        except subprocess.CalledProcessError:
            pass  # Allure未找到，保持默认值
        except Exception as e:
            self.logger.warning(f"自动查找Allure路径失败: {e}")

    def choose_allure_path(self, evt):
        try:
            file_path = askopenfilename(
                initialdir='~/Desktop',
                title='打开 Allure 文件',
                filetypes=[('All Files', '*.*')]
            )
            if file_path:
                self.ui.allure_path.set(file_path)
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"选择Allure路径失败: {str(e)}\n")
            self.logger.error(f"选择Allure路径失败: {traceback.format_exc()}")


if __name__ == "__main__":
    try:
        win = Win(Controller())
        win.mainloop()
    except KeyboardInterrupt:
        print("程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {str(e)}")
        traceback.print_exc()
