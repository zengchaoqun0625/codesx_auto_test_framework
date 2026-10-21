#! /usr/bin/env python

import webbrowser
import os
import re
import traceback
import subprocess
import platform
import json
import sys
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
        """Generate a thin entry point backed by the shared JSON case executor."""
        return f"""
import pytest
from api_project.common.allure_decorator import allure_preset
from api_project.testcases.test_api import build_case_context, execute_case

@allure_preset("jqb_login_api")
@pytest.mark.parametrize("get_case_data", ["{file_name_part}.json"], indirect=True)
def test_{file_name_part.lower()}(get_case_data, api_request, assert_code, base_url, allure_reporter, request_processor):
    ctx = build_case_context(api_request, assert_code, base_url, allure_reporter, request_processor)
    for case_name, case in get_case_data["test_cases"].items():
        execute_case(case, ctx, case_name)
"""


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
        self.allure_path.set('双击或者右击选择 Allure 路径（必填项）')
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
        # 省略原样式代码，保持原样...
        pass

    def __win(self):
        # 省略窗口初始化代码...
        pass

    def scrollbar_autohide(self, vbar, hbar, widget):
        pass

    def v_scrollbar(self, vbar, widget, x, y, w, h, pw, ph):
        pass

    def h_scrollbar(self, hbar, widget, x, y, w, h, pw, ph):
        pass

    def create_bar(self, master, widget, is_vbar, is_hbar, x, y, w, h, pw, ph):
        pass

    def __tk_input_file_path(self, parent):
        pass

    def __tk_button_choose_file_button(self, parent):
        pass

    def __tk_button_start_button(self, parent):
        pass

    def __tk_text_log(self, parent):
        pass

    def __tk_label_url_prefix_label(self, parent):
        pass

    def __tk_input_url_prefix_input(self, parent):
        pass

    def __tk_label_choose_allure_path_label(self, parent):
        pass

    def __tk_input_choose_allure_path_input(self, parent):
        pass

    def __tk_label_frame_radio_frame(self, parent):
        pass

    def __tk_radio_button_choose_ptest_allure_radio(self, parent):
        pass

    def __tk_radio_button_choose_ptest_allure_at_radio(self, parent):
        pass

    def create_copy_menu(self):
        pass

    def show_copy_menu(self, event):
        pass

    def copy_file_path(self):
        pass


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

            url_counts = {}
            for url in all_urls:
                sp = urlparse(url).path
                if sp:
                    prefix = url.split(sp)[0]
                else:
                    prefix = url
                if prefix not in ['http', 'https', 'http:', 'https:', 'http://', 'https://']:
                    url_counts[prefix] = url_counts.get(prefix, 0) + 1

            if url_counts:
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
        if 'params' in request and isinstance(request['params'], dict):
            for key, value in request['params'].items():
                variables[key] = value
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
        if 'json' in request and isinstance(request['json'], dict):
            for key, value in request['json'].items():
                variables[key] = value
        if 'formdata' in request and isinstance(request['formdata'], dict):
            for key, value in request['formdata'].items():
                variables[key] = value
        return variables

    def normalize_request_data(self, request):
        """标准化请求数据"""
        normalized = request.copy()
        if 'json' in normalized and normalized['json']:
            if isinstance(normalized['json'], str):
                try:
                    normalized['json'] = json.loads(normalized['json'])
                except json.JSONDecodeError:
                    pass
        if 'data' in normalized and normalized['data']:
            if not isinstance(normalized['data'], str):
                normalized['data'] = json.dumps(normalized['data'], ensure_ascii=False)
        if 'formdata' in normalized and normalized['formdata']:
            if isinstance(normalized['formdata'], str):
                try:
                    normalized['formdata'] = json.loads(normalized['formdata'])
                except json.JSONDecodeError:
                    form_data = {}
                    for item in normalized['formdata'].split('&'):
                        if '=' in item:
                            key, value = item.split('=', 1)
                            form_data[key] = value
                    normalized['formdata'] = form_data
        return normalized

    def run_convert(self, evt):
        try:
            ENV.load()
            file_path = self.ui.file_path.get()
            if file_path in ['', '请选择待转换的 cURL 文件...']:
                self.ui.tk_text_log.insert('end', '还未选择需要转换的文件\n')
                self.logger.error('还未选择需要转换的文件')
                return

            url_prefix = self.ui.url_prefix.get()
            if url_prefix in ['', '请输入接口地址的前缀...']:
                self.ui.tk_text_log.insert('end', '接口地址的前缀是必填项，不能为空！\n')
                self.logger.error('接口地址的前缀是必填项，不能为空！')
                return

            self._write_host_config(url_prefix)

            allure_path = self.ui.allure_path.get()
            if allure_path not in ['', '双击或者右击选择 Allure 路径（必填项）']:
                self._write_allure_config(allure_path)

            self.ui.tk_text_log.insert('end', '已经加载环境变量\n')
            self.logger.info('已经加载环境变量')

            curl = Curl()
            curl.load(curl_file_path=file_path)
            self.ui.tk_text_log.insert('end', f'已加载文件[{os.path.split(file_path)[1]}]，正在进行转换\n')
            self.logger.info(f'已加载文件[{os.path.split(file_path)[1]}]，正在进行转换')

            case_config_lines = self._prepare_case_config_header()
            all_variables = {}

            for request in curl.group:
                normalized_request = self.normalize_request_data(request)
                file_name_part = self._generate_file_name(normalized_request)
                for key in ['api_name']:
                    if key in normalized_request:
                        del normalized_request[key]
                constant_name = f"{file_name_part.upper()}_CASE_DATA_PATH"
                case_config_lines.append(
                    f"{constant_name} = os.path.join(CASE_DATA_DIR_PATH, '{file_name_part}.json')"
                )
                variables = self.extract_variables(normalized_request)
                all_variables.update(variables)
                self._generate_test_script(file_name_part, constant_name, normalized_request)
                self._generate_test_data_json(file_name_part, normalized_request)

            self._write_case_config(case_config_lines)
            self._write_user_variables(all_variables)

        except Exception as e:
            self.ui.tk_text_log.insert('end', f"转换过程出错: {str(e)}\n")
            self.logger.error(f"转换过程出错: {traceback.format_exc()}")

    def _write_host_config(self, url_prefix):
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
        return file_name_part.replace('-', '_')

    def _generate_test_script(self, file_name_part, constant_name, request):
        try:
            request_type = RequestProcessor.get_request_type(request)
            CASE_SCRIPT = os.path.join(CASE_SCRIPT_DIR_PATH, f"test_{file_name_part.lower()}.py")
            with open(CASE_SCRIPT, 'w', encoding='utf-8') as fw:
                test_code = TestCaseGenerator.generate_test_function(
                    file_name_part, constant_name, request_type
                )
                fw.write(test_code)
            self.ui.tk_text_log.insert('end', f"test_{file_name_part.lower()}.py 写入成功！\n")
            self.logger.info(f"test_{file_name_part.lower()}.py 写入成功！")
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"test_{file_name_part.lower()}.py 写入失败：{str(e)}\n")
            self.logger.error(f"test_{file_name_part.lower()}.py 写入失败：{traceback.format_exc()}")

    def _generate_test_data_json(self, file_name_part, request):
        try:
            CASE_DATA = os.path.join(CASE_DATA_DIR_PATH, f"{file_name_part}.json")
            if not os.path.isdir(CASE_DATA_DIR_PATH):
                os.makedirs(CASE_DATA_DIR_PATH, exist_ok=True)
            request_type = RequestProcessor.get_request_type(request)
            json_data = {
                "test_cases": {
                    "test_case_1": {
                        "description": f"{file_name_part}接口测试",
                        "request_type": request_type,
                        "logic": "query",
                        "data": request
                    }
                }
            }
            if os.path.isfile(CASE_DATA):
                with open(CASE_DATA, 'r', encoding='utf-8') as fr:
                    existing_data = json.load(fr)
                    is_duplicate = any(
                        case_data["data"] == request
                        for case_data in existing_data["test_cases"].values()
                    )
                    if not is_duplicate:
                        new_case_num = len(existing_data["test_cases"]) + 1
                        new_case_name = f"test_case_{new_case_num}"
                        existing_data["test_cases"][new_case_name] = {
                            "description": f"{file_name_part}接口测试用例{new_case_num}",
                            "request_type": request_type,
                            "logic": "query",
                            "data": request
                        }
                        json_data = existing_data
            with open(CASE_DATA, 'w', encoding='utf-8') as fw:
                json.dump(json_data, fw, ensure_ascii=False, indent=4)
            self.ui.tk_text_log.insert('end', f"{file_name_part}.json 写入成功！\n")
            self.logger.info(f"{file_name_part}.json 写入成功！")
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"{file_name_part}.json 写入失败：{str(e)}\n")
            self.logger.error(f"{file_name_part}.json 写入失败：{traceback.format_exc()}")

    def _write_case_config(self, case_config_lines):
        try:
            with open(os.path.join(CONFIG_DIR_PATH, 'case_config.py'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(case_config_lines))
            self.ui.tk_text_log.insert('end', '已经重写 case_config.py\n')
            self.logger.info('已经重写 case_config.py')
        except Exception as e:
            self.ui.tk_text_log.insert('end', f"写入case配置失败: {str(e)}\n")
            self.logger.error(f"写入case配置失败: {traceback.format_exc()}")

    def _write_user_variables(self, all_variables):
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
            pass
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


# ======================== Web 服务部分 ========================
# 此部分仅在加 --web 参数时启动，不影响原有 GUI 模式。

def start_web_server():
    """启动 Flask Web 服务"""
    from flask import Flask, request, jsonify, render_template_string
    import tempfile

    app = Flask(__name__)
    controller = Controller()

    # 模拟 StringVar，让 controller 能正常调用 .set() / .get()
    class FakeStringVar:
        def __init__(self, value=""):
            self._value = value
        def set(self, value):
            self._value = value
        def get(self):
            return self._value

    class WebFakeUI:
        def __init__(self):
            self.file_path = FakeStringVar("")
            self.url_prefix = FakeStringVar("")
            self.allure_path = FakeStringVar("")
            self.radio_value = 1
            self.tk_text_log = self.FakeTextLog()
        class FakeTextLog:
            def insert(self, *args): pass
            def delete(self, *args): pass

    controller.init(WebFakeUI(), Logger())

    @app.route('/')
    def index():
        return render_template_string(HTML_TEMPLATE)

    @app.route('/api/detect-allure')
    def detect_allure():
        try:
            controller.find_allure_path()
            path = controller.ui.allure_path.get()  # 调用 .get()
            return jsonify({"success": True, "path": path})
        except Exception as e:
            return jsonify({"success": False, "path": None})

    @app.route('/api/convert', methods=['POST'])
    def convert():
        try:
            file = request.files.get('file')
            url_prefix = request.form.get('url_prefix', '')
            allure_path = request.form.get('allure_path', '')
            if not file:
                return jsonify({"success": False, "error": "未上传文件"})

            temp_dir = tempfile.mkdtemp()
            file_path = os.path.join(temp_dir, file.filename)
            file.save(file_path)

            # 用 FakeStringVar 的 .set() 注入参数
            controller.ui.file_path.set(file_path)
            controller.ui.url_prefix.set(url_prefix)
            controller.ui.allure_path.set(allure_path)

            # 确保输出目录存在
            os.makedirs(CONFIG_DIR_PATH, exist_ok=True)
            os.makedirs(CASE_SCRIPT_DIR_PATH, exist_ok=True)
            os.makedirs(CASE_DATA_DIR_PATH, exist_ok=True)

            ENV.load()
            controller.run_convert(None)

            return jsonify({"success": True, "logs": [{"level": "info", "message": "转换完成，请检查输出目录。"}]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
        finally:
            if 'temp_dir' in locals():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    print("Web 服务已启动，浏览器将自动打开...")
    webbrowser.open('http://127.0.0.1:5000')
    app.run(host='127.0.0.1', port=5000, debug=False)

# HTML 模板（浅色主题，含球体增强）
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小曾Api - cURL 转换工具</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --accent: #5E6AD2;
            --accent-hover: #6E78E8;
            --accent-soft: rgba(94,106,210,.12);
            --success: #4CB782;
            --warning: #F2C94C;
            --danger: #EB5757;
            --radius-card: 14px;
            --radius-ctl: 8px;
            --font-ui: "Inter", -apple-system, "Segoe UI", sans-serif;
            --font-mono: "JetBrains Mono", monospace;
        }
        [data-theme="light"] {
            --bg: #F7F8FA;
            --card: #FFFFFF;
            --border: rgba(16,24,40,.08);
            --border-strong: rgba(16,24,40,.16);
            --text: #1B1E24;
            --text-2: #5C6470;
            --text-3: #8A919C;
            --code-bg: #F4F6F9;
            --input-bg: #FFFFFF;
            --nav-bg: rgba(255,255,255,.75);
            --shadow-card: 0 1px 2px rgba(16,24,40,.05), 0 16px 40px -20px rgba(16,24,40,.14);
            --glow-a: rgba(94,106,210,.30);
            --glow-b: rgba(138,99,210,.24);
            --glow-c: rgba(96,165,250,.26);
            --grid-line: rgba(16,24,40,.05);
            color-scheme: light;
        }
        [data-theme="dark"] {
            --bg: #08090A;
            --card: rgba(255,255,255,.025);
            --border: rgba(255,255,255,.07);
            --border-strong: rgba(255,255,255,.14);
            --text: #F2F3F5;
            --text-2: #9BA1A9;
            --text-3: #646A72;
            --code-bg: #0C0E12;
            --input-bg: rgba(255,255,255,.03);
            --nav-bg: rgba(8,9,10,.72);
            --shadow-card: 0 1px 2px rgba(0,0,0,.5), 0 16px 40px -16px rgba(0,0,0,.65);
            --glow-a: rgba(94,106,210,.50);
            --glow-b: rgba(138,99,210,.40);
            --glow-c: rgba(45,75,255,.34);
            --grid-line: rgba(255,255,255,.035);
            color-scheme: dark;
        }
        * { box-sizing: border-box; }
        html, body { margin:0; padding:0; }
        body {
            font-family: var(--font-ui);
            background: var(--bg);
            color: var(--text);
            -webkit-font-smoothing: antialiased;
            min-height: 100vh;
            transition: background .3s, color .3s;
        }
        .bg-stage { position:fixed; inset:0; z-index:-1; overflow:hidden; background:var(--bg); }
        .bg-grid {
            position:absolute; inset:0;
            background-image: linear-gradient(var(--grid-line) 1px,transparent 1px), linear-gradient(90deg,var(--grid-line) 1px,transparent 1px);
            background-size:52px 52px;
            -webkit-mask-image:radial-gradient(ellipse 90% 62% at 50% 0%,#000 25%,transparent 78%);
            mask-image:radial-gradient(ellipse 90% 62% at 50% 0%,#000 25%,transparent 78%);
        }
        .orb { position:absolute; border-radius:50%; filter:blur(90px); will-change:transform; }
        .orb-a { width:580px; height:580px; top:-190px; left:6%; background:radial-gradient(circle,var(--glow-a),transparent 65%); animation:drift-a 26s infinite alternate; }
        .orb-b { width:500px; height:500px; top:8%; right:-130px; background:radial-gradient(circle,var(--glow-b),transparent 65%); animation:drift-b 32s infinite alternate; }
        .orb-c { width:440px; height:440px; bottom:-170px; left:30%; background:radial-gradient(circle,var(--glow-c),transparent 65%); animation:drift-c 24s infinite alternate; }
        @keyframes drift-a { to { transform:translate(90px,60px) scale(1.12); } }
        @keyframes drift-b { to { transform:translate(-70px,90px) scale(.92); } }
        @keyframes drift-c { to { transform:translate(60px,-70px) scale(1.08); } }
        .sphere {
            position:absolute; border-radius:50%; will-change:transform;
            background: radial-gradient(circle at 30% 26%, rgba(255,255,255,.85), rgba(255,255,255,0) 38%),
                        radial-gradient(circle at 72% 82%, rgba(0,0,0,.42), transparent 55%),
                        linear-gradient(135deg, #8A90FF, #5E6AD2 55%, #3D44A8);
            box-shadow: inset -12px -18px 40px rgba(0,0,0,.35), inset 8px 10px 24px rgba(255,255,255,.25),
                        0 30px 60px -18px rgba(94,106,210,.55);
            animation: float-y 9s ease-in-out infinite;
        }
        .sphere-a { width:150px; height:150px; top:130px; right:10%; }
        .sphere-b { width:84px; height:84px; top:360px; left:5%; opacity:.92; animation-delay:-4s; }
        @keyframes float-y { 0%,100%{transform:translateY(0) rotate(0)} 50%{transform:translateY(-22px) rotate(4deg)} }
        @media(prefers-reduced-motion){.orb,.sphere{animation:none}}
        .topbar { position:sticky; top:0; z-index:50; backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); background:var(--nav-bg); border-bottom:1px solid var(--border); }
        .topbar-inner { max-width:1280px; margin:0 auto; height:60px; padding:0 24px; display:flex; align-items:center; justify-content:space-between; }
        .brand { display:flex; align-items:center; gap:10px; }
        .brand-logo { width:30px; height:30px; border-radius:8px; display:grid; place-items:center; color:#fff; background:linear-gradient(135deg,#7C87E8,#5E6AD2 60%,#4A3FA0); box-shadow:0 4px 14px -4px rgba(94,106,210,.6),inset 0 1px 0 rgba(255,255,255,.25); }
        .brand-name { font-weight:650; font-size:15px; color:var(--text); letter-spacing:-.01em; }
        .brand-tag { font-size:11px; color:var(--text-3); border:1px solid var(--border); padding:3px 9px; border-radius:999px; font-family:var(--font-mono); }
        .icon-btn { width:34px; height:34px; border-radius:8px; border:1px solid var(--border); background:transparent; color:var(--text-2); display:grid; place-items:center; cursor:pointer; }
        .icon-btn:hover { color:var(--text); border-color:var(--border-strong); }
        .page { max-width:1280px; margin:0 auto; padding:52px 24px 64px; }
        .hero { text-align:center; margin-bottom:36px; }
        .hero h1 { font-size:33px; font-weight:700; letter-spacing:-.03em; color:var(--text); margin:0 0 10px; }
        .grad { background:linear-gradient(90deg,#7C87E8,#A78BFA); -webkit-background-clip:text; background-clip:text; color:transparent; }
        .hero p { color:var(--text-2); font-size:14px; max-width:600px; margin:0 auto 20px; line-height:1.7; }
        .steps-pills { display:flex; gap:8px; justify-content:center; flex-wrap:wrap; }
        .pill { display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--text-2); border:1px solid var(--border); background:var(--card); padding:6px 13px; border-radius:999px; }
        .pill .num { width:16px; height:16px; border-radius:50%; background:var(--accent-soft); color:var(--accent); font-size:10px; display:grid; place-items:center; font-weight:700; }
        .layout { display:grid; grid-template-columns:1fr 1fr; gap:20px; align-items:start; }
        @media(max-width:1080px){.layout{grid-template-columns:1fr}}
        .card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius-card); box-shadow:var(--shadow-card); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); padding:20px; margin-bottom:20px; }
        .card-head { display:flex; align-items:center; gap:12px; margin-bottom:14px; }
        .card-ico { width:30px; height:30px; border-radius:8px; background:var(--accent-soft); color:var(--accent); display:grid; place-items:center; }
        .input-field { width:100%; padding:10px 14px; border:1px solid var(--border); border-radius:8px; background:var(--input-bg); color:var(--text); font-size:14px; }
        .input-field:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); outline:none; }
        .btn-primary { background:var(--accent); color:#fff; border:none; border-radius:8px; padding:12px 24px; font-weight:600; cursor:pointer; width:100%; font-size:15px; }
        .btn-primary:hover { background:var(--accent-hover); }
        .btn-primary:disabled { opacity:.5; cursor:not-allowed; }
        .log-container { background:var(--code-bg); color:var(--text-2); border:1px solid var(--border); border-radius:8px; padding:16px; max-height:200px; overflow-y:auto; font-family:var(--font-mono); font-size:12px; white-space:pre-wrap; }
        .log-success { color:var(--success); }
        .log-error { color:var(--danger); }
        .file-upload { border:2px dashed var(--border); border-radius:8px; padding:16px; text-align:center; cursor:pointer; }
    </style>
</head>
<body data-theme="light">
    <div class="bg-stage">
        <div class="bg-grid"></div>
        <div class="orb orb-a"></div>
        <div class="orb orb-b"></div>
        <div class="orb orb-c"></div>
        <div class="sphere sphere-a"></div>
        <div class="sphere sphere-b"></div>
    </div>
    <div class="topbar">
        <div class="topbar-inner">
            <div class="brand">
                <div class="brand-logo">Z</div>
                <span class="brand-name">小曾Api</span>
                <span class="brand-tag">v0.1.5</span>
            </div>
            <button class="icon-btn" id="themeToggle">🌓</button>
        </div>
    </div>
    <div class="page">
        <div class="hero">
            <h1>cURL 命令 <span class="grad">→ 自动化测试代码</span></h1>
            <p>上传 cURL 文件，自动生成 pytest + Allure 测试脚本及数据文件。</p>
            <div class="steps-pills">
                <div class="pill"><span class="num">1</span> 上传文件</div>
                <div class="pill"><span class="num">2</span> 配置前缀</div>
                <div class="pill"><span class="num">3</span> 点击转换</div>
            </div>
        </div>
        <div class="layout">
            <div>
                <div class="card">
                    <div class="card-head"><div class="card-ico">📂</div><div><strong>选择 cURL 文件</strong></div></div>
                    <div class="file-upload" id="dropZone">
                        <input type="file" id="fileInput" style="display:none">
                        <div id="fileName">点击或拖拽上传文件</div>
                    </div>
                </div>
                <div class="card">
                    <div class="card-head"><div class="card-ico">⚙️</div><div><strong>URL 前缀</strong></div></div>
                    <input type="text" id="urlPrefix" class="input-field" placeholder="自动提取或手动输入">
                </div>
            </div>
            <div>
                <div class="card">
                    <div class="card-head"><div class="card-ico">🔍</div><div><strong>Allure 路径</strong><span id="allureStatus" style="font-size:12px; color:var(--text-3); margin-left:8px;"></span></div></div>
                    <input type="text" id="allurePath" class="input-field" placeholder="自动检测中...">
                </div>
                <div class="card">
                    <div class="card-head"><div class="card-ico">🚀</div><div><strong>开始转换</strong></div></div>
                    <button class="btn-primary" id="startBtn" disabled>转换</button>
                </div>
            </div>
        </div>
        <div class="card" style="margin-top:20px;">
            <div class="card-head"><div class="card-ico">📋</div><strong>运行日志</strong></div>
            <div class="log-container" id="logContainer"></div>
        </div>
    </div>
    <script>
        const toggle = document.getElementById('themeToggle');
        const body = document.body;
        toggle.addEventListener('click', () => {
            const cur = body.getAttribute('data-theme');
            body.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
        });
        fetch('/api/detect-allure').then(r=>r.json()).then(d=>{
            if(d.success && d.path){
                document.getElementById('allurePath').value = d.path;
                document.getElementById('allureStatus').innerText = '✅ 已检测到';
            } else {
                document.getElementById('allureStatus').innerText = '❌ 未检测到';
            }
        });
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const fileNameDiv = document.getElementById('fileName');
        const urlPrefix = document.getElementById('urlPrefix');
        const startBtn = document.getElementById('startBtn');
        const logContainer = document.getElementById('logContainer');
        let uploadedFile = null;
        dropZone.addEventListener('click', ()=> fileInput.click());
        fileInput.addEventListener('change', handleFile);
        dropZone.addEventListener('dragover', e=>{ e.preventDefault(); dropZone.style.borderColor='var(--accent)'; });
        dropZone.addEventListener('dragleave', ()=> dropZone.style.borderColor='');
        dropZone.addEventListener('drop', e=>{
            e.preventDefault();
            dropZone.style.borderColor='';
            const file = e.dataTransfer.files[0];
            if(file) handleFileFrom(file);
        });
        function handleFile(e){
            const file = e.target.files[0];
            if(file) handleFileFrom(file);
        }
        function handleFileFrom(file){
            uploadedFile = file;
            fileNameDiv.innerText = file.name;
            startBtn.disabled = false;
            const reader = new FileReader();
            reader.onload = function(e){
                const text = e.target.result;
                const matches = text.match(/https?:\/\/[^\s'"]+/g);
                if(matches){
                    const urls = matches.map(u=> { try{ return new URL(u).origin }catch{ return null } }).filter(Boolean);
                    const freq = {};
                    urls.forEach(u=> freq[u]=(freq[u]||0)+1);
                    const most = Object.entries(freq).sort((a,b)=>b[1]-a[1])[0];
                    if(most) urlPrefix.value = most[0];
                }
            };
            reader.readAsText(file);
        }
        startBtn.addEventListener('click', async ()=>{
            if(!uploadedFile) return;
            const form = new FormData();
            form.append('file', uploadedFile);
            form.append('url_prefix', urlPrefix.value);
            form.append('allure_path', document.getElementById('allurePath').value);
            startBtn.disabled = true;
            startBtn.innerText = '转换中...';
            logContainer.innerHTML = '';
            function log(msg, cls=''){
                const div = document.createElement('div');
                div.className = cls;
                div.innerText = msg;
                logContainer.appendChild(div);
                logContainer.scrollTop = logContainer.scrollHeight;
            }
            try{
                const resp = await fetch('/api/convert', { method:'POST', body:form });
                const data = await resp.json();
                if(data.success){
                    log('✅ 转换成功！测试文件和 JSON 数据已生成。', 'log-success');
                } else {
                    log('❌ 转换失败: ' + (data.error||'未知错误'), 'log-error');
                }
            } catch(e){
                log('❌ 请求失败: ' + e.message, 'log-error');
            }
            startBtn.disabled = false;
            startBtn.innerText = '转换';
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    if '--web' in sys.argv:
        # 确保 Flask 已安装
        try:
            import flask
        except ImportError:
            print("错误：需要安装 Flask。请执行 pip install flask")
            sys.exit(1)
        start_web_server()
    else:
        # 启动原有的 Tkinter GUI
        try:
            win = Win(Controller())
            win.mainloop()
        except KeyboardInterrupt:
            print("程序被用户中断")
        except Exception as e:
            print(f"程序运行出错: {str(e)}")
            traceback.print_exc()
