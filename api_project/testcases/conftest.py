#! /usr/bin/env python
# -*- coding: utf-8 -*-
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@qq.com
createTime  : 2026/08/06  23:28
fileName    : conftest.py
Description : API测试框架核心配置文件，提供全局Fixture、请求封装、断言工具、Allure报告支持
'''
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from urllib.parse import urlparse
from functools import wraps

import allure
import pytest
import requests
from requests import Response


# ------------------------------
# 1. 第三方及项目模块导入（优化路径可读性）
# ------------------------------
try:
    from ..common.BUG import ZenTaoService, JiraService
except ImportError as e:
    raise ImportError(
        f"项目模块导入失败！请检查目录结构是否正确：{str(e)}\n"
        "预期目录结构：\n"
        "api_project/\n"
        "  ├─ config/ (包含bug_config.py、message_config.py)\n"
        "  ├─ common/ (包含BUG.py、Message.py)\n"
        "  └─ testcases/ (当前conftest.py所在目录)"
    ) from e


# ------------------------------
# 2. 日志配置（优化日志格式与输出）
# ------------------------------
def setup_logger() -> logging.Logger:
    """初始化日志配置，统一日志格式"""
    logger = logging.getLogger(__name__)
    if logger.handlers:  # 避免重复添加处理器
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台输出处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()


# ------------------------------
# 3. 主机配置加载器（已提取到 common/host_config.py）
# ------------------------------
from api_project.common.host_config import HostConfig

# ------------------------------
# 3b. 通知模块导入（已提取到 common/notifications/）
# ------------------------------
from api_project.common.notifications.builders import (
    _build_notification_content, _submit_bug,
    _status_emoji, _build_report_links_md,
    TEST_EXECUTOR, EMERGENCY_CONTACT, EMERGENCY_PHONE,
    PASSED_DISPLAY_LIMIT, ALLURE_URL, ALLURE_URLS,
    NOTIFICATION_MODE,
)
from api_project.common.performance_manager import (
    append_performance_records, evaluate_cases,
)
from api_project.common.notifications.senders import (
    _send_robot_notification, _send_phone_call,
)
from api_project.common.upload_service import upload_test_report
from api_project.common.api_request import sanitize_for_display, sanitize_headers
from api_project.common.reporting import (
    collect_worker_results,
    is_report_upload_enabled,
    is_xdist_worker,
    publish_worker_results,
)
from api_project.common.session_reporting import SessionReporter


# ------------------------------
# 3. 按模块/接口筛选测试
# ------------------------------
# 使用方式（二选一，环境变量优先）：
#   1. 终端环境变量: set RUN_MODULE=查询模块       （支持模块名、接口预设名、逗号分隔）
#   2. 代码直接配置: 修改下方 RUN_MODULE_CONFIG 的值即可
#   3. 查看可用项:   set RUN_MODULE=list

import glob as _glob

# 代码配置：直接修改此变量按模块/接口筛选运行
# 支持: 模块名("查询模块")、接口预设名("jqb_login_api")、逗号分隔多值、"list"
# 优先级: 环境变量 RUN_MODULE > 此配置 > 全量执行
RUN_MODULE_CONFIG = ""


def _load_preset_info():
    """加载 ALLURE_CONFIGS，返回 (preset→sub_suite 映射, preset 列表)"""
    try:
        from api_project.common.allure_decorator import ALLURE_CONFIGS
        return (
            {k: v.get("sub_suite", "") for k, v in ALLURE_CONFIGS.items()},
            list(ALLURE_CONFIGS.keys()),
            ALLURE_CONFIGS
        )
    except Exception as e:
        logging.getLogger(__name__).warning(f"加载 ALLURE_CONFIGS 失败: {e}")
        return {}, [], {}


def _build_file_preset_map():
    """扫描 testcases/ 目录，构建 文件绝对路径 → 使用的preset名 的映射"""
    import os as _os
    case_dir = _os.path.dirname(_os.path.abspath(__file__))
    preset_sub_suite_map, preset_list, _ = _load_preset_info()
    if not preset_list:
        return {}

    file_preset_map = {}
    for f in sorted(_glob.glob(_os.path.join(case_dir, "test_*.py"))):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                content = fh.read()
            for preset_name in preset_list:
                if preset_name in content:
                    file_preset_map[_os.path.normcase(_os.path.abspath(f))] = preset_name
                    break
        except Exception:
            pass
    return file_preset_map


def _get_run_module():
    """获取 RUN_MODULE 值：环境变量优先，代码配置兜底"""
    return os.getenv("RUN_MODULE", RUN_MODULE_CONFIG).strip()


def _list_available_modules_and_apis():
    """打印所有可用模块和接口"""
    _, preset_list, all_configs = _load_preset_info()
    if not all_configs:
        return

    modules = sorted({cfg.get("sub_suite", "") for cfg in all_configs.values()})
    logger.info("=" * 60)
    logger.info(f"📋 可用业务模块 ({len(modules)}):")
    for m in modules:
        count = sum(1 for cfg in all_configs.values() if cfg.get("sub_suite") == m)
        logger.info(f"   [{count}个接口] {m}")
    logger.info(f"📋 可用接口预设 ({len(preset_list)}):")
    for p in preset_list:
        logger.info(f"   {p}")
    logger.info("=" * 60)


def _get_preset_for_param_id(param_id):
    """从 parametrize id 反查 preset: 'test_api[api_mainChart/test_case_1]' → 'jqb_api_mainchart_api'"""
    # 提取括号内的第一个 / 之前的部分 → json 文件基础名
    bracket_content = param_id.split('[')[-1].rstrip(']') if '[' in param_id else ''
    json_base = bracket_content.split('/')[0] if '/' in bracket_content else ''
    if not json_base:
        return None

    # 与 test_api.py 中 _build_json_preset_map 相同的匹配逻辑
    base = json_base.lower().replace('-', '_')
    _, _, all_configs = _load_preset_info()
    for pk in (all_configs or {}):
        pl = pk.lower()
        if pl.startswith('jqb_') and pl.endswith('_api'):
            middle = pl[4:-4]
            if base.replace('_', '') == middle.replace('_', ''):
                return pk
    return None


def _deduplicate_param_test(config, items):
    """如果 test_api.py 参数化测试存在，自动跳过被其覆盖的单独 test_*.py 避免重复运行"""
    # 检查 items 中是否有 test_api.py
    has_param = any(
        hasattr(item, 'fspath') and os.path.basename(str(item.fspath)) == 'test_api.py'
        for item in items
    )
    if not has_param:
        return

    # Only generated per-endpoint scripts with a known preset duplicate the
    # parameterized entry point.  Keep hand-written framework/unit tests.
    file_preset_map = _build_file_preset_map()
    deselected = []
    for item in items[:]:
        if not hasattr(item, 'fspath'):
            continue
        fname = os.path.basename(str(item.fspath))
        item_path = os.path.normcase(os.path.abspath(str(item.fspath)))
        # test_api.py 自身保留；只移除已映射到 JSON 预设的生成脚本。
        if fname != 'test_api.py' and item_path in file_preset_map:
            items.remove(item)
            deselected.append(item)

    if deselected:
        logger.info(f"🔄 test_api.py 参数化测试已覆盖，自动跳过 {len(deselected)} 个重复文件")
        config.hook.pytest_deselected(items=deselected)


def pytest_collection_modifyitems(config, items):
    # 去重：test_api.py 存在时自动跳过被其覆盖的单独 test_*.py
    _deduplicate_param_test(config, items)

    """pytest 收集钩子：根据 RUN_MODULE 筛选测试"""
    requested_files = {name.strip() for name in os.getenv("RUN_CASE_FILES", "").split(",") if name.strip()}
    if requested_files:
        selected, deselected = [], []
        for item in items:
            is_parameterized_api_case = (
                hasattr(item, "fspath")
                and os.path.basename(str(item.fspath)) == "test_api.py"
                and any(f"[{filename}/" in item.name for filename in requested_files)
            )
            (selected if is_parameterized_api_case else deselected).append(item)
        if selected:
            items[:] = selected
            config.hook.pytest_deselected(items=deselected)
            logger.info(f"🏷️ 按文件筛选测试: {sorted(requested_files)}")
            return
        logger.warning("⚠️ RUN_CASE_FILES 未匹配到参数化用例，执行全量测试")

    run_module = _get_run_module()
    if not run_module:
        return

    # --list 模式
    if run_module.lower() == "list":
        _list_available_modules_and_apis()
        return

    # 解析筛选值
    filter_names = [m.strip() for m in run_module.split(",") if m.strip()]
    if not filter_names:
        return

    logger.info(f"🏷️ 测试筛选: {filter_names}")

    # 查找目标 preset 名（先按 sub_suite 匹配，再按 key 直接匹配）
    _, _, all_configs = _load_preset_info()
    if not all_configs:
        return

    target_presets = set()
    for name in filter_names:
        found = False
        for pk, cfg in all_configs.items():
            if cfg.get("sub_suite") == name or pk == name:
                target_presets.add(pk)
                found = True
        if not found:
            logger.warning(f"   ⚠️ 未找到匹配 '{name}' 的模块或接口")

    if not target_presets:
        logger.warning("⚠️ 无有效匹配项，执行全量测试")
        return

    logger.info(f"   匹配到 preset: {sorted(target_presets)}")

    # 查找目标文件
    file_preset_map = _build_file_preset_map()
    target_files = {f for f, p in file_preset_map.items() if p in target_presets}

    has_param_target = any(
        hasattr(item, 'fspath')
        and os.path.basename(str(item.fspath)) == 'test_api.py'
        and _get_preset_for_param_id(item.name) in target_presets
        for item in items
    )
    if not target_files and not has_param_target:
        logger.warning("⚠️ 未找到匹配的测试文件或参数化用例，执行全量")
        return

    # 筛选测试项
    selected, deselected = [], []
    for item in items:
        item_path = os.path.normcase(str(item.fspath)) if hasattr(item, 'fspath') else ""

        # 普通文件：按文件路径匹配
        if item_path in target_files:
            selected.append(item)
            continue

        # 参数化测试 (test_api.py)：按 parametrize id 反查 preset
        if item_path.endswith('test_api.py') and '[' in item.name:
            param_preset = _get_preset_for_param_id(item.name)
            if param_preset and param_preset in target_presets:
                selected.append(item)
                continue

        deselected.append(item)

    items[:] = selected
    config.hook.pytest_deselected(items=deselected)

    logger.info(
        f"   ✅ 匹配 {len(selected)} 个测试: "
        f"{[os.path.basename(f) for f in sorted(target_files)]}"
    )


# ------------------------------
# 4. 命令行参数配置（优化参数说明）
# ------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    """添加pytest命令行参数与配置项"""
    # 1. 主机地址参数
    parser.addoption(
        "--api-host",
        action="store",
        default=None,
        help="指定API测试主机地址（优先级最高），示例：--host https://api.example.com"
    )

    # 2. 配置文件base_url项
    parser.addini(
        "base_url",
        type="string",
        default="",
        help="API测试默认主机地址（优先级：低于--host，高于host_config.py）"
    )


# ------------------------------
# 5. API请求封装（已提取到 common/api_request.py）
# ------------------------------
from api_project.common.api_request import ApiRequest


# ------------------------------
# 6. API断言工具（优化断言可读性与扩展性）
# ------------------------------
from api_project.common.api_assertions import ApiAssert


# ------------------------------
# 7. 请求参数处理器（优化兼容性与日志）
# ------------------------------
from api_project.common.param_processor import RequestProcessor


# ------------------------------
# 8. 全局Fixture定义（优化作用域与资源清理）
# ------------------------------
@pytest.fixture(scope="session")
def base_url(pytestconfig: pytest.Config) -> str:
    """
    全局BaseURL Fixture（作用域：整个测试会话）
    - 从多渠道获取主机地址（优先级见HostConfig）
    - 会话内缓存结果（避免重复加载）
    """
    return HostConfig.get_host(pytestconfig)


@pytest.fixture(scope="function")
def api_request() -> ApiRequest:
    """
    API请求工具Fixture（作用域：每个测试函数）
    - 每个用例独立Session（避免用例间状态污染）
    - 自动清理资源（测试结束后关闭Session）
    """
    request_obj = ApiRequest()
    yield request_obj
    # 测试结束后关闭Session（释放连接）
    request_obj.session.close()
    logger.info("ℹ️ 测试函数结束，关闭API请求Session")


@pytest.fixture(scope="function")
def assert_code() -> ApiAssert:
    """
    API断言工具Fixture（作用域：每个测试函数）
    - 提供链式断言能力（简化代码）
    """
    return ApiAssert


@pytest.fixture(scope="session")
def logger_fixture() -> logging.Logger:
    """
    日志工具Fixture（作用域：整个测试会话）
    - 全局统一日志配置（避免重复初始化）
    """
    return logger


@pytest.fixture(scope="function")
def request_processor() -> RequestProcessor:
    """
    请求参数处理器Fixture（作用域：每个测试函数）
    - 统一处理请求参数格式（兼容多类型）
    """
    return RequestProcessor


@pytest.fixture(scope="function")
def get_case_data(request: pytest.FixtureRequest) -> Dict[str, Any]:
    """
    测试用例数据Fixture（作用域：每个测试函数）
    - 从case_data_files目录加载JSON用例数据
    - 支持参数化（通过@pytest.mark.parametrize传递文件名）
    """
    # 获取参数化传递的JSON文件名（如："detail_getContent.json"）
    filename = request.param
    if not isinstance(filename, str) or not filename.endswith(".json"):
        raise ValueError(
            f"❌ 无效的用例数据文件名: {filename}\n"
            "要求：字符串类型且以.json结尾，示例：'user_login.json'"
        )

    # 计算用例数据文件的绝对路径（适配不同运行环境）
    case_data_dir = Path(__file__).resolve().parent.parent / "case_data_files"
    case_data_path = case_data_dir / filename

    # 检查目录是否存在（自动创建不存在的目录）
    if not case_data_dir.exists():
        case_data_dir.mkdir(parents=True, exist_ok=True)
        logger.warning(f"⚠️ 用例数据目录不存在，已自动创建: {str(case_data_dir)}")

    # 检查文件是否存在
    if not case_data_path.exists():
        raise FileNotFoundError(
            f"❌ 测试用例数据文件不存在: {str(case_data_path)}\n"
            "请确认文件路径或重新生成用例数据"
        )

    # 读取并解析JSON文件
    try:
        with open(case_data_path, "r", encoding="utf-8") as f:
            case_data = json.load(f)

        # 验证JSON结构（确保包含test_cases层级）
        if "test_cases" not in case_data or not isinstance(case_data["test_cases"], dict):
            raise ValueError(
                f"❌ 用例数据JSON结构无效: {str(case_data_path)}\n"
                "要求结构：{\"test_cases\": {\"test_case_1\": { ... }}}"
            )

        logger.info(f"✅ 加载测试用例数据成功: {filename}（用例数：{len(case_data['test_cases'])}）")
        return case_data

    except json.JSONDecodeError as e:
        raise ValueError(
            f"❌ 用例数据JSON解析失败: {str(case_data_path)}\n"
            f"错误位置: 行{e.lineno} 列{e.colno} | 错误原因: {e.msg}"
        ) from e
    except Exception as e:
        raise Exception(
            f"❌ 加载测试用例数据失败: {str(case_data_path)}\n"
            f"错误原因: {str(e)}"
        ) from e

@pytest.fixture(autouse=True)
def record_request_response(request, api_request):
    """
    在每个测试函数执行后，将 ApiRequest 中记录的请求/响应信息存储到 request.node 上，
    供 pytest_runtest_makereport 钩子使用。
    """
    yield
    # 测试执行结束后，将信息存到 node 的自定义属性中
    request.node._request_info = getattr(api_request, 'last_request_info', None)
    request.node._response_info = getattr(api_request, 'last_response_info', None)


# ------------------------------
# 9. Allure报告工具（优化稳定性与用户体验）
# ------------------------------

import time
import json
import logging
from typing import Dict, Any, Optional, Union, List, Callable
from requests import Response
import allure
import pytest

# 从公共模块导入配置和装饰器（避免重复定义）
from api_project.common.allure_decorator import ALLURE_CONFIGS, allure_preset

logger = logging.getLogger(__name__)


# ------------------------------
# Allure报告生成器Fixture
# ------------------------------
@pytest.fixture(scope="function")
def allure_reporter() -> "AllureReporter":
    """
    Allure报告生成器Fixture（作用域：每个测试函数）
    - 记录请求/响应详情（便于问题定位）
    - 支持自定义步骤、附件（丰富报告内容）
    - 测试结束后自动清理资源（避免内存泄漏）
    """

    class AllureReporter:
        def __init__(self):
            self.start_time: Optional[float] = None  # 请求开始时间（用于计算响应时间）
            self.request_info: Dict[str, Any] = {}  # 存储请求信息
            self.response_info: Dict[str, Any] = {}  # 存储响应信息

        def start_timer(self) -> None:
            """开始计时（需在发送请求前调用）"""
            self.start_time = time.time()
            logger.debug("ℹ️ Allure报告计时器已启动")

        def record_request(
                self,
                url: str,
                method: str,
                params: Optional[Dict[str, Any]] = None,
                data: Optional[Union[Dict[str, Any], str]] = None,
                headers: Optional[Dict[str, str]] = None
        ) -> None:
            """
            记录请求信息并附加到Allure报告
            :param url: 请求URL
            :param method: 请求方法（GET/POST等）
            :param params: URL参数（query string）
            :param data: 请求体（form-data格式）
            :param headers: 请求头
            """
            try:
                # 隐藏敏感信息
                safe_headers = sanitize_headers(headers)

                # 整理请求信息（兼容非JSON序列化数据）
                self.request_info = {
                    "url": url,
                    "method": method.upper(),
                    "params": self._safe_serialize(sanitize_for_display(params)),
                    "data": self._safe_serialize(sanitize_for_display(data)),
                    "headers": self._safe_serialize(safe_headers),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }

                # 附加到Allure报告
                with allure.step("📨 请求详情"):
                    allure.attach(
                        json.dumps(self.request_info, ensure_ascii=False, indent=2),
                        name="请求信息",
                        attachment_type=allure.attachment_type.JSON
                    )
                logger.debug("ℹ️ Allure报告已记录请求信息")

            except Exception as e:
                self._add_error_attachment("记录请求信息失败", str(e))

        def record_response(self, response: Optional[Response]) -> None:
            """
            记录响应信息并附加到Allure报告
            :param response: requests.Response对象
            """
            if not response:
                self._add_error_attachment("记录响应信息失败", "响应对象为空")
                return

            try:
                # 计算响应时间
                response_time = round(time.time() - self.start_time, 3) if self.start_time else 0

                # 整理响应信息
                self.response_info = {
                    "status_code": response.status_code,
                    "response_time": f"{response_time}s",
                    "headers": self._safe_serialize(sanitize_headers(response.headers)),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }

                # 附加基础信息到Allure报告
                with allure.step("📩 响应详情"):
                    # 1. 基础状态信息
                    allure.attach(
                        f"状态码: {response.status_code}\n响应时间: {response_time}s",
                        name="基础信息",
                        attachment_type=allure.attachment_type.TEXT
                    )

                    # 2. 响应头
                    headers_str = "\n".join([f"{k}: {v}" for k, v in sanitize_headers(response.headers).items()])
                    allure.attach(
                        headers_str,
                        name="响应头",
                        attachment_type=allure.attachment_type.TEXT
                    )

                    # 3. 响应体（区分JSON和普通文本）
                    try:
                        response_json = response.json()
                        allure.attach(
                            json.dumps(sanitize_for_display(response_json), ensure_ascii=False, indent=2),
                            name="响应体(JSON)",
                            attachment_type=allure.attachment_type.JSON
                        )
                    except json.JSONDecodeError:
                        # 截断过长的文本（避免报告体积过大）
                        response_text = str(sanitize_for_display(response.text))[:1000] + ("..." if len(response.text) > 1000 else "")
                        allure.attach(
                            response_text,
                            name="响应体(文本)",
                            attachment_type=allure.attachment_type.TEXT
                        )

                logger.debug(f"ℹ️ Allure报告已记录响应信息（状态码: {response.status_code}）")

            except Exception as e:
                self._add_error_attachment("记录响应信息失败", str(e))

        def add_custom_attachment(
                self,
                name: str,
                content: Any,
                attachment_type: allure.attachment_type = allure.attachment_type.TEXT
        ) -> None:
            """添加自定义附件到Allure报告"""
            try:
                # 确保内容可序列化
                content_str = self._safe_serialize(content)
                allure.attach(
                    content_str,
                    name=name,
                    attachment_type=attachment_type
                )
                logger.debug(f"ℹ️ Allure报告已添加自定义附件: {name}")
            except Exception as e:
                self._add_error_attachment(f"添加自定义附件失败({name})", str(e))

        def add_step(self, step_name: str, step_content: Optional[Any] = None) -> None:
            """添加测试步骤到Allure报告"""
            with allure.step(step_name):
                if step_content is not None:
                    try:
                        content_str = self._safe_serialize(step_content)
                        allure.attach(
                            content_str,
                            name=step_name,
                            attachment_type=allure.attachment_type.TEXT
                        )
                    except Exception as e:
                        self._add_error_attachment(f"添加步骤内容失败({step_name})", str(e))
            logger.debug(f"ℹ️ Allure报告已添加步骤: {step_name}")

        def apply_config(self, preset_name: str, **override_config) -> None:
            """
            应用预设的Allure报告配置（使用 sub_suite + tags 替代 feature/story）

            Args:
                preset_name: 预设配置名称（如 "jqb_login_api"）
                **override_config: 可覆盖的配置参数（title, tags, severity等）

            使用示例：
                allure_reporter.apply_config("jqb_login_api")
                allure_reporter.apply_config("jqb_login_api", title="自定义标题")
            """
            if preset_name not in ALLURE_CONFIGS:
                error_msg = (
                    f"未找到Allure配置: {preset_name}\n"
                    f"可用配置: {list(ALLURE_CONFIGS.keys())}"
                )
                self._add_error_attachment("应用Allure配置失败", error_msg)
                raise ValueError(error_msg)

            # 获取配置并支持覆盖
            config = ALLURE_CONFIGS[preset_name].copy()
            config.update(override_config)

            # 使用静态方法设置 Allure 标签（确保生效）
            # 注意：这里使用 dynamic 是因为在 fixture 中无法使用静态装饰器

            # 设置 epic
            if config.get("epic"):
                allure.dynamic.epic(config["epic"])

            # 设置 sub_suite（替代 feature）
            if config.get("sub_suite"):
                allure.dynamic.sub_suite(config["sub_suite"])

            # 设置严重级别
            if config.get("severity"):
                allure.dynamic.severity(config["severity"])

            # 设置标题（如果提供）
            if config.get("title"):
                allure.dynamic.title(config["title"])

            # 设置标签（包含 story 信息）
            for tag in config.get("tags", []):
                allure.dynamic.tag(tag)

            logger.info(f"ℹ️ Allure报告已应用配置: {preset_name}")

        def _safe_serialize(self, data: Any) -> str:
            """安全序列化数据（处理非JSON可序列化类型）"""
            if data is None:
                return "null"
            try:
                return json.dumps(sanitize_for_display(data), ensure_ascii=False, default=str)
            except Exception:
                return str(sanitize_for_display(data))  # 序列化失败时转为字符串

        def _add_error_attachment(self, title: str, error_msg: str) -> None:
            """添加错误信息到Allure报告（内部工具方法）"""
            allure.attach(
                error_msg,
                name=title,
                attachment_type=allure.attachment_type.TEXT
            )
            logger.error(f"❌ {title}: {error_msg}")

        def clear(self) -> None:
            """清理资源（测试结束时调用）"""
            self.start_time = None
            self.request_info.clear()
            self.response_info.clear()
            logger.debug("ℹ️ Allure报告资源已清理")

    # 初始化并返回AllureReporter实例
    try:
        reporter = AllureReporter()
        yield reporter
    except Exception as e:
        logger.error(f"❌ AllureReporter初始化失败: {str(e)}", exc_info=True)
        raise
    finally:
        # 无论是否异常，都清理资源
        if 'reporter' in locals():
            reporter.clear()

# ------------------------------
# 11. 测试结果处理钩子（实现在 common.session_reporting）
# ------------------------------
_session_reporter = SessionReporter(logger)


def pytest_sessionstart(session):
    _session_reporter.start()


def pytest_testnodedown(node, error):
    _session_reporter.merge_worker_results(node)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    outcome = yield
    report = outcome.get_result()
    # ``call`` is the ordinary test result.  setup/teardown are also captured
    # when they fail or skip, otherwise fixture failures disappear from the
    # summary and notification flow.
    if call.when == "call" or report.failed or report.skipped:
        _session_reporter.capture_report(item, report)


def pytest_sessionfinish(session, exitstatus):
    _session_reporter.finish(session.config)


def send_post_report_notifications(html_report_path=None):
    """Send pytest notifications after final report generation completes."""
    _session_reporter.notify_after_reports(html_report_path)


# ------------------------------
# 13. 用例执行前设置 Allure 标签
# ------------------------------
from api_project.config.allure_model import setup_allure_marker

def pytest_runtest_setup(item):
    """
    每个用例执行前调用，设置Allure标签
    """
    setup_allure_marker(item)
