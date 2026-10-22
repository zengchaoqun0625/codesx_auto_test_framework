# -*- coding: utf-8 -*-
# api_project/common/allure_decorator.py
"""
Allure 报告装饰器模块
提供统一的 Allure 标签配置和装饰器工具
"""

import time
import json
import logging
from pathlib import Path
from functools import wraps
from typing import Dict, Any, Optional, Union, List, Callable
from requests import Response
import allure
import pytest

from api_project.common.api_request import sanitize_for_display, sanitize_headers, sanitize_url

logger = logging.getLogger(__name__)

# ==============================
# Allure报告配置预设（可根据项目扩展）
# ==============================
ALLURE_CONFIGS: Dict[str, Dict[str, Any]] = {
"jqb_login_api": {
        "suite": "进钱吧测试项目",  # 套件名称（替代模块名）
        "epic": "进钱吧项目",
        "sub_suite": "登录认证模块",
        "tags": ["账号密码登录", "登录接口", "API测试", "正向用例"],
        "severity": allure.severity_level.CRITICAL,
        "title": "登录接口测试"
    },
"jqb_query_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["信息查询", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "查询接口测试"
    },
"jqb_logout_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "登录认证模块",
        "tags": ["退出登录", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "退出登录接口测试"
    },
"jqb_payment_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "支付模块",
        "tags": ["支付接口", "API测试", "核心流程"],
        "severity": allure.severity_level.BLOCKER,
        "title": "支付接口测试"
    },
"jqb_balance_api": {
        "suite": "进钱吧测试项目",  # 补充 suite
        "epic": "进钱吧项目",
        "sub_suite": "余额模块",
        "tags": ["余额查询", "API测试"],
        "severity": allure.severity_level.CRITICAL,
        "title": "余额查询测试"
    },
"jqb_anon_siteinfos_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "登录认证模块",
        "tags": ['匿名访问', '查询接口', 'API测试'],
        "severity": allure.severity_level.CRITICAL,
        "title": "站点信息查询接口测试"
    },
"jqb_api_agents_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ['代理管理', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "代理列表查询接口测试"
    },
"jqb_api_isvinfo_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ['服务商信息', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "ISV信息查询接口测试"
    },
"jqb_api_mchinfo_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ['商户信息', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "商户信息查询接口测试"
    },
"jqb_api_payifdefines_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "支付模块",
        "tags": ['支付定义', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "支付定义查询接口测试"
    },
"jqb_api_payorder_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "订单模块",
        "tags": ['支付订单', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "支付订单查询接口测试"
    },
"jqb_api_payways_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "支付模块",
        "tags": ['支付方式', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "支付方式查询接口测试"
    },
"jqb_complaints_guidancequantity_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ['投诉管理', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "投诉指引数量查询接口测试"
    },
"jqb_current_user_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ['用户信息', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "当前用户信息查询接口测试"
    },
"jqb_mchapply_applycreatedby_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "商户申请模块",
        "tags": ['商户申请', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "商户申请创建人查询接口测试"
    },
"jqb_mchapply_getallarea_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "商户申请模块",
        "tags": ['商户申请', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "商户申请地区查询接口测试"
    },
"jqb_mchapply_mchlist_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "商户申请模块",
        "tags": ['商户申请', '提交接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "商户申请列表查询接口测试"
    },
"jqb_mchpolling_list_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ['商户轮询', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "商户轮询列表查询接口测试"
    },
"jqb_payifdefines_get_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "支付模块",
        "tags": ['支付定义', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "支付定义获取接口测试"
    },
"jqb_payorder_count_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "订单模块",
        "tags": ['支付订单', '查询接口', 'API测试'],
        "severity": allure.severity_level.NORMAL,
        "title": "支付订单数量查询接口测试"
    },
    "jqb_api_mainchart_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["首页图表", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "主图表查询接口测试"
    },
    "jqb_api_mchqrcodes_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["商户二维码", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "商户二维码查询接口测试"
    },
    "jqb_api_terminal_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "终端管理模块",
        "tags": ["终端查询", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "终端查询接口测试"
    },
    "jqb_api_payways_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "支付模块",
        "tags": ["支付方式", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "支付方式查询接口测试"
    },
    "jqb_api_refundorder_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["退款订单", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "退款订单查询接口测试"
    },
    "jqb_api_sysarticles_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["系统文章", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "系统文章查询接口测试"
    },
    "jqb_api_transferorders_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["转账订单", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "转账订单查询接口测试"
    },
    "jqb_current_user_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["用户信息", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "当前用户信息查询接口测试"
    },
    "jqb_mainchart_paycount_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "统计报表模块",
        "tags": ["支付统计", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "主图表支付统计接口测试"
    },
    "jqb_mainchart_paydaycount_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "统计报表模块",
        "tags": ["支付统计", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "主图表每日支付统计接口测试"
    },
    "jqb_mainchart_paytrendcount_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "统计报表模块",
        "tags": ["支付趋势", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "主图表支付趋势统计接口测试"
    },
    "jqb_mainchart_paytypecount_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "统计报表模块",
        "tags": ["支付类型", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "主图表支付类型统计接口测试"
    },
    "jqb_mchstore_alllist_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["商户门店", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "商户门店列表查询接口测试"
    },
    "jqb_payorder_list_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "订单模块",
        "tags": ["支付订单", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "支付订单列表查询接口测试"
    },
    "jqb_payorder_paycount_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "订单模块",
        "tags": ["支付订单", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "支付订单统计接口测试"
    },
    "jqb_store_device_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "查询模块",
        "tags": ["门店设备", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "门店设备查询接口测试"
    },
    "jqb_total_getquerydate_api": {
        "suite": "进钱吧测试项目",
        "epic": "进钱吧项目",
        "sub_suite": "统计报表模块",
        "tags": ["统计报表", "查询接口", "API测试"],
        "severity": allure.severity_level.NORMAL,
        "title": "统计查询日期接口测试"
    },
}

# 控制台扩展预设保存在独立 JSON 文件中，避免网页操作改写本模块的内置配置。
def _load_console_presets():
    path = Path(__file__).resolve().parents[1] / "config" / "allure_presets.json"
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(store, dict):
        return
    for key in store.get("deleted", []):
        if isinstance(key, str):
            ALLURE_CONFIGS.pop(key, None)
    for key, config in store.get("presets", {}).items():
        if not isinstance(key, str) or not isinstance(config, dict):
            continue
        item = dict(config)
        severity = str(item.get("severity", "normal")).upper()
        item["severity"] = getattr(allure.severity_level, severity, allure.severity_level.NORMAL)
        item["tags"] = [str(tag) for tag in item.get("tags", []) if str(tag).strip()]
        ALLURE_CONFIGS[key] = item


_load_console_presets()


# ==============================
# Allure报告装饰器（全局）- 静态版本
# ==============================
def allure_report(config: Dict[str, Any]) -> Callable:
    """
    使用静态装饰器，确保 Allure 标签生效

    支持的配置字段：
        - suite: 套件名称（替代默认的模块名，如 api_project.testcases）
        - epic: 史诗级别（模块/项目）
        - sub_suite: 子套件（业务模块，替代 feature）
        - tags: 标签列表（包含 story 信息）
        - severity: 严重级别（BLOCKER, CRITICAL, NORMAL, MINOR, TRIVIAL）
        - title: 测试标题

    使用示例：
        @allure_report({
            "suite": "进钱吧测试项目",
            "epic": "进钱吧项目",
            "sub_suite": "登录认证模块",
            "tags": ["账号密码登录", "API测试"],
            "severity": allure.severity_level.CRITICAL,
            "title": "登录接口测试"
        })
        def test_login():
            pass
    """

    def decorator(func: Callable) -> Callable:
        # 创建静态装饰器链
        decorated = func

        # 注意：装饰器应用顺序（从内到外）
        # 最内层的装饰器会先被应用，在报告中显示在更底层

        # 1. 设置标题（最具体）
        if config.get("title"):
            decorated = allure.title(config["title"])(decorated)

        # 2. 设置子套件（替代 feature）
        if config.get("sub_suite"):
            decorated = allure.sub_suite(config["sub_suite"])(decorated)

        # 3. 设置史诗级别
        if config.get("epic"):
            decorated = allure.epic(config["epic"])(decorated)

        # 4. 设置严重级别
        if config.get("severity"):
            decorated = allure.severity(config["severity"])(decorated)

        # 5. 设置标签
        if config.get("tags"):
            for tag in config.get("tags", []):
                decorated = allure.tag(tag)(decorated)

        # 6. 设置套件（最外层，替代默认的模块名 api_project.testcases）
        # 注意：suite 必须放在最后（最外层），才能覆盖默认的模块名
        if config.get("suite"):
            decorated = allure.suite(config["suite"])(decorated)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.debug(f"✅ Allure 标签已设置：{func.__name__}")
            return decorated(*args, **kwargs)

        return wrapper

    return decorator


# ==============================
# 便捷装饰器（推荐使用）
# ==============================
def allure_preset(preset_name: str, **override_config) -> Callable:
    """
    使用预设配置的便捷装饰器

    Args:
        preset_name: 预设配置名称（如 "jqb_login_api"）
        **override_config: 覆盖预设配置的参数

    Returns:
        装饰器函数

    使用示例：
        # 基础用法
        @allure_preset("jqb_login_api")
        def test_login():
            pass

        # 覆盖部分配置
        @allure_preset("jqb_login_api", title="自定义标题", tags=["额外标签"])
        def test_login_custom():
            pass
    """
    if preset_name not in ALLURE_CONFIGS:
        raise ValueError(
            f"未找到预设配置: {preset_name}，"
            f"可用的预设: {list(ALLURE_CONFIGS.keys())}"
        )

    # 获取预设配置并覆盖自定义配置
    config = ALLURE_CONFIGS[preset_name].copy()
    config.update(override_config)
    return allure_report(config)


# ==============================
# 动态标题装饰器
# ==============================
def allure_dynamic_title(title_func: Callable) -> Callable:
    """
    支持动态标题的装饰器（用于从 JSON 数据中获取标题）

    Args:
        title_func: 返回标题字符串的函数，接收测试函数的参数

    使用示例：
        @allure_dynamic_title(lambda get_case_data, **kwargs:
                              f"登录测试 - {get_case_data['test_cases']['test_case_1']['data'].get('description', '')}")
        def test_login(get_case_data):
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 执行前设置动态标题
            try:
                title = title_func(*args, **kwargs)
                if title:
                    allure.dynamic.title(title)
                    logger.debug(f"📝 动态标题已设置: {title}")
            except Exception as e:
                logger.warning(f"⚠️ 设置动态标题失败: {e}")
            return func(*args, **kwargs)

        return wrapper

    return decorator


# ==============================
# Allure 附件工具类
# ==============================
class AllureAttachments:
    """Allure 附件工具类，提供统一的附件添加方法"""

    @staticmethod
    def attach_text(content: str, name: str = "文本信息", attachment_type: Any = allure.attachment_type.TEXT):
        """添加文本附件"""
        allure.attach(str(sanitize_for_display(content)), name, attachment_type)

    @staticmethod
    def attach_json(data: Dict, name: str = "JSON数据"):
        """添加 JSON 附件"""
        allure.attach(
            json.dumps(sanitize_for_display(data), indent=2, ensure_ascii=False),
            name,
            allure.attachment_type.JSON
        )

    @staticmethod
    def attach_response(response: Response, name: str = "响应信息"):
        """添加响应附件"""
        try:
            allure.attach(str(response.status_code), f"{name} - 状态码", allure.attachment_type.TEXT)
            try:
                allure.attach(
                    json.dumps(sanitize_for_display(response.json()), indent=2, ensure_ascii=False),
                    f"{name} - 响应体",
                    allure.attachment_type.JSON
                )
            except:
                allure.attach(str(sanitize_for_display(response.text)), f"{name} - 响应体", allure.attachment_type.TEXT)
        except Exception as e:
            logger.warning(f"添加响应附件失败: {e}")

    @staticmethod
    def attach_request(method: str, url: str, headers: Dict = None, body: Dict = None, params: Dict = None):
        """添加请求附件"""
        request_info = f"{method} {sanitize_url(url)}"
        allure.attach(request_info, "请求信息", allure.attachment_type.TEXT)

        if params:
            allure.attach(json.dumps(sanitize_for_display(params), indent=2, ensure_ascii=False), "请求参数", allure.attachment_type.JSON)

        if headers:
            safe_headers = sanitize_headers(headers)
            allure.attach(json.dumps(safe_headers, indent=2, ensure_ascii=False), "请求头", allure.attachment_type.JSON)

        if body:
            allure.attach(json.dumps(sanitize_for_display(body), indent=2, ensure_ascii=False), "请求体", allure.attachment_type.JSON)

    @staticmethod
    def attach_screenshot(screenshot_bytes: bytes, name: str = "截图"):
        """添加截图附件"""
        allure.attach(screenshot_bytes, name, allure.attachment_type.PNG)

    @staticmethod
    def attach_html(html_content: str, name: str = "HTML内容"):
        """添加 HTML 附件"""
        allure.attach(html_content, name, allure.attachment_type.HTML)


# ==============================
# 断言失败时的自动附件
# ==============================
def auto_attach_on_failure(func: Callable) -> Callable:
    """
    断言失败时自动添加附件的装饰器

    使用示例：
        @auto_attach_on_failure
        def test_login():
            assert response.status_code == 200
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AssertionError as e:
            # 断言失败时，尝试从参数中提取响应信息
            for arg in args:
                if hasattr(arg, 'json') and callable(arg.json):
                    AllureAttachments.attach_response(arg, "失败时响应")
                elif hasattr(arg, 'status_code'):
                    AllureAttachments.attach_response(arg, "失败时响应")
            # 重新抛出异常
            raise e

    return wrapper


# ==============================
# 测试用例步骤装饰器
# ==============================
def allure_step(step_name: str):
    """
    Allure 测试步骤装饰器

    使用示例：
        @allure_step("用户登录操作")
        def login():
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with allure.step(step_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# ==============================
# 导出公共接口
# ==============================
__all__ = [
    'ALLURE_CONFIGS',
    'allure_report',
    'allure_preset',
    'allure_dynamic_title',
    'AllureAttachments',
    'auto_attach_on_failure',
    'allure_step'
]
