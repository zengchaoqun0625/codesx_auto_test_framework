"""
参数化 API 测试 —— logic 字段 + handler 分发表

特性：
1. 自动扫描 case_data_files/ 下所有 JSON，匹配 ALLURE_CONFIGS 预设
2. 遍历每个 JSON 中所有 test_case（不再只取 test_case_1）
3. 根据 logic 字段分发到对应 handler
4. 动态设置 Allure 标签（suite/epic/sub_suite/tags/severity/title）
5. 数据驱动断言（assertions 字段）
6. 接口依赖链（extract 提取 + ${var} 引用）

logic 字段支持（JSON test_case 层级）:
    - "query"（默认）: 标准请求 → 断言 200
    - "precondition":  先执行前置请求再发正式请求
    - "expect_error":  预期失败，不固定状态码
未来可按需扩展更多 handler，无需修改测试框架。

JSON test_case 支持的扩展字段：
    - expected_status: 期望状态码（默认 200）
    - assertions: 断言列表，元素格式：
        {"response_time": 3.0}                        # 响应时间 ≤ 3s
        {"key": "code", "eq": 0}                       # 顶层键等于
        {"key": "msg", "contains": "成功"}             # 顶层键包含
        {"key": "data.list", "length": 5}              # 键路径长度
        {"jsonpath": "$.data.id", "eq": 100}           # jsonpath 等于
        {"jsonpath": "$.data.name", "contains": "张"}  # jsonpath 包含
        {"jsonpath": "$.data.list", "length": 3}       # jsonpath 长度
        {"jsonpath": "$.data.id", "type": "int"}       # jsonpath 类型
        {"jsonpath": "$.data.token", "not_empty": true}  # jsonpath 非空
    - extract: 提取列表（响应 → 环境变量，供后续用例 ${var} 引用）：
        [{"name": "order_id", "jsonpath": "$.data.orderId"}]
        [{"name": "token", "expression": "$.data.token", "index": 0, "default": ""}]
    - 请求参数（url/params/json/data/formdata/headers）中支持 ${var} 引用：
        {"url": "/api/order/${order_id}"}
"""

import json
import os
import re
import copy
import logging
import allure
import pytest
from jsonpath import jsonpath
from api_project import CASE_DATA_DIR_PATH
from api_project.common.allure_decorator import ALLURE_CONFIGS
from api_project.common.api_request import sanitize_headers

logger = logging.getLogger(__name__)

# 环境变量引用正则：${var_name}
_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


# ============================================================
#  变量引用解析 / 提取器 / 断言执行（数据驱动核心）
# ============================================================

def _resolve_vars(data):
    """
    递归解析数据中的 ${var} 环境变量引用。
    A 接口 extract 提取的变量存在 os.environ 中，B 接口请求参数里
    写 ${order_id} 即可自动替换为 A 接口响应中的值。
    """
    if isinstance(data, str):
        if "${" in data:
            def _replace(match):
                return os.environ.get(match.group(1), "")
            return _VAR_PATTERN.sub(_replace, data)
        return data
    if isinstance(data, list):
        return [_resolve_vars(item) for item in data]
    if isinstance(data, dict):
        return {key: _resolve_vars(value) for key, value in data.items()}
    return data


def _do_extract(case_data, response) -> None:
    """
    响应提取器：将响应中的值提取到 os.environ（跨用例共享）。
    支持 jsonpath / 正则两种表达式：
        {"name": "order_id", "jsonpath": "$.data.orderId"}
        {"name": "token", "regex": "<token>(\\w+)</token>", "index": 0, "default": ""}
    """
    for item in case_data.get("extract", []):
        name = item.get("name")
        if not name:
            continue
        index = item.get("index", 0)
        default = item.get("default", "")
        value = None

        try:
            expr = item.get("jsonpath") or item.get("expression")
            if expr:
                result = jsonpath(response.json(), expr)
                if result:
                    value = result[index] if len(result) > index else default
            elif item.get("regex"):
                import re as _re
                matched = _re.findall(item["regex"], response.text)
                value = matched[index] if len(matched) > index else default
        except Exception as e:
            logger.warning(f"⚠️ 提取 {name} 失败: {str(e)}")

        if value is None:
            value = default
        os.environ[name] = str(value)
        logger.info(f"✅ 已提取 {name} = {str(value)[:80]}（供后续用例 ${name} 引用）")


def _safe_json(response):
    """安全解析响应 JSON，失败返回空字典"""
    try:
        return response.json()
    except Exception:
        return {}


def _do_assertions(case_data, response, assert_code) -> None:
    """
    数据驱动断言执行器：解析 test_case 中的 assertions 字段并逐条断言。
    失败时抛出 AssertionError，由 pytest 统一标记用例失败。
    """
    assertions = case_data.get("assertions", [])
    if not assertions:
        return

    response_json = _safe_json(response)

    for idx, item in enumerate(assertions, start=1):
        tag = f"断言#{idx} {json.dumps(item, ensure_ascii=False)}"

        # 1. 响应时间断言
        if "response_time" in item:
            assert_code.response_time(response, float(item["response_time"]))
            logger.info(f"✅ {tag} 通过")
            continue

        # 2. jsonpath 断言（优先）
        expr = item.get("jsonpath") or item.get("expression")
        if expr:
            result = jsonpath(response_json, expr)
            actual = result[0] if result else None
            _assert_value(tag, expr, actual, item, response)
            continue

        # 3. 简单键断言（支持 a.b.c 点路径）
        key = item.get("key")
        if key:
            actual = _get_by_dot_path(response_json, key)
            _assert_value(tag, key, actual, item, response)
            continue

        logger.warning(f"⚠️ {tag} 缺少 jsonpath/key/response_time 字段，已跳过")


def _get_by_dot_path(data, path: str):
    """按 a.b.c 点路径取值"""
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _assert_value(tag, expr, actual, item, response) -> None:
    """通用值断言：eq / contains / length / type / not_empty"""
    if "eq" in item:
        assert actual == item["eq"], (
            f"❌ {tag} 失败\n预期: {item['eq']} | 实际: {actual}\n"
            f"表达式: {expr}\n响应体: {_safe_text(response)}"
        )
        logger.info(f"✅ {tag} 通过: {actual}")
    elif "contains" in item:
        assert str(item["contains"]) in str(actual), (
            f"❌ {tag} 失败\n预期包含: {item['contains']} | 实际: {actual}\n"
            f"表达式: {expr}\n响应体: {_safe_text(response)}"
        )
        logger.info(f"✅ {tag} 通过: {actual}")
    elif "length" in item:
        assert actual is not None and len(actual) == int(item["length"]), (
            f"❌ {tag} 失败\n预期长度: {item['length']} | 实际长度: "
            f"{len(actual) if actual is not None else 'N/A'}\n表达式: {expr}"
        )
        logger.info(f"✅ {tag} 通过: 长度 {item['length']}")
    elif "type" in item:
        type_map = {"int": int, "str": str, "list": list, "dict": dict,
                    "bool": bool, "float": float}
        expected_type = type_map.get(str(item["type"]).lower())
        assert expected_type and isinstance(actual, expected_type), (
            f"❌ {tag} 失败\n预期类型: {item['type']} | 实际: {type(actual).__name__}({actual})\n"
            f"表达式: {expr}"
        )
        logger.info(f"✅ {tag} 通过: 类型 {item['type']}")
    elif item.get("not_empty"):
        assert actual is not None and actual != "" and actual != [], (
            f"❌ {tag} 失败\n表达式: {expr} 取值为空\n响应体: {_safe_text(response)}"
        )
        logger.info(f"✅ {tag} 通过: 非空")


def _safe_text(response, limit=300):
    """安全截断响应文本用于错误提示"""
    try:
        text = json.dumps(response.json(), ensure_ascii=False)
    except Exception:
        text = response.text
    return text[:limit] + ("..." if len(text) > limit else "")


# ============================================================
#  JSON 文件名 → ALLURE_CONFIGS 预设 自动映射
# ============================================================

def _build_json_preset_map():
    """扫描 case_data_files 目录，通过命名规则自动匹配预设"""
    mapping = {}
    for fname in os.listdir(CASE_DATA_DIR_PATH):
        if not fname.endswith('.json'):
            continue

        # api_mainChart.json → mainchart
        base = fname.replace('.json', '').lower().replace('-', '_').replace('.', '_')
        matched = None

        for preset in ALLURE_CONFIGS:
            pl = preset.lower()
            if pl.startswith('jqb_') and pl.endswith('_api'):
                middle = pl[4:-4]  # 去掉 jqb_ 前缀和 _api 后缀
                # 忽略所有下划线后比较 → mainchart == mainchart
                if base.replace('_', '') == middle.replace('_', ''):
                    matched = preset
                    break

        mapping[fname] = matched

    return mapping


JSON_PRESET_MAP = _build_json_preset_map()


# ============================================================
#  Handler 分发表
# ============================================================

def _handle_query(case_data, ctx) -> 'requests.Response':
    """
    默认查询 handler — 标准请求 + 变量解析 + 响应提取 + allure 记录

    Returns:
        requests.Response 对象，供外层断言
    """
    # 深拷贝 + 解析 ${var} 环境变量引用（不污染原始 JSON 数据）
    request_data = _resolve_vars(copy.deepcopy(case_data.get("data", {})))
    full_url = f"{ctx['base_url']}{request_data.get('url', '')}"
    method = request_data.get("method", "GET")
    request_type = case_data.get("request_type", "default")
    request_params = request_data.get("params", {})
    request_body, headers = ctx['request_processor'].process_request_params(
        request_type, request_data
    )

    # 打印请求
    safe_headers = sanitize_headers(headers)
    print(f"\n【请求】{method} {full_url}")
    if request_params:
        print(f"参数: {json.dumps(request_params, ensure_ascii=False)}")
    if request_body:
        print(f"请求体: {json.dumps(request_body, ensure_ascii=False)}")
    if headers:
        print(f"请求头: {json.dumps(safe_headers, ensure_ascii=False)}")

    # allure 记录请求
    allure.attach(f"{method} {full_url}", "请求信息", allure.attachment_type.TEXT)
    if request_body:
        allure.attach(
            json.dumps(request_body, indent=2, ensure_ascii=False),
            "请求体", allure.attachment_type.JSON
        )
    if headers:
        allure.attach(
            json.dumps(safe_headers, indent=2, ensure_ascii=False),
            "请求头", allure.attachment_type.JSON
        )

    # 发送请求
    response = ctx['api_request'].send_request(
        url=full_url, method=method,
        params=request_params, headers=headers, **request_body
    )

    # 打印响应
    print(f"【响应】状态码: {response.status_code}")
    try:
        print(f"响应体: {json.dumps(response.json(), ensure_ascii=False)[:500]}")
    except Exception:
        print(f"响应体: {response.text[:500]}")

    # allure 记录响应
    allure.attach(str(response.status_code), "响应状态码", allure.attachment_type.TEXT)
    try:
        allure.attach(
            json.dumps(response.json(), indent=2, ensure_ascii=False),
            "响应体", allure.attachment_type.JSON
        )
    except Exception:
        allure.attach(response.text, "响应体", allure.attachment_type.TEXT)

    # 响应提取（供后续用例 ${var} 引用）
    _do_extract(case_data, response)

    return response


# ---- 扩展 handler 示例（按需取消注释 / 新增） ----

# def _handle_precondition(case_data, ctx):
#     """带前置操作：先执行 case_data["pre_steps"]，再执行正式请求"""
#     for step in case_data.get("pre_steps", []):
#         _handle_query({"data": step}, ctx)
#     return _handle_query({"data": case_data["data"]}, ctx)
#
#
# def _handle_expect_error(case_data, ctx):
#     """预期失败的请求 — 不验证状态码，只验证错误信息"""
#     request_data = case_data["data"]
#     full_url = f"{ctx['base_url']}{request_data.get('url', '')}"
#     method = request_data.get("method", "GET")
#     request_type = case_data.get("request_type", "default")
#     request_params = request_data.get("params", {})
#     request_body, headers = ctx['request_processor'].process_request_params(
#         request_type, request_data
#     )
#
#     # 预期失败场景：去掉 token header
#     headers.pop("iToken", None)
#     headers.pop("Authorization", None)
#
#     response = ctx['api_request'].send_request(
#         url=full_url, method=method, verify=False,
#         params=request_params, headers=headers, **request_body
#     )
#
#     allure.attach(str(response.status_code), "响应状态码", allure.attachment_type.TEXT)
#     try:
#         allure.attach(
#             json.dumps(response.json(), indent=2, ensure_ascii=False),
#             "响应体", allure.attachment_type.JSON
#         )
#     except Exception:
#         allure.attach(response.text, "响应体", allure.attachment_type.TEXT)
#
#     return response


# ---- 注册表: logic 字段值 → (handler_func, 默认期望状态码) ----
HANDLERS = {
    "query": (_handle_query, 200),
    # 未来扩展:
    # "precondition": (_handle_precondition, 200),
    # "expect_error": (_handle_expect_error, None),  # None 表示不固定
}


# ============================================================
#  参数化用例构建
# ============================================================

def _build_all_case_params():
    """
    扫描所有 JSON → 展开 test_cases → 生成 pytest.param 列表

    每个 param 包含: json_file, preset_name, case_name, case_data, logic
    """
    params = []
    for fname in sorted(JSON_PRESET_MAP.keys()):
        preset = JSON_PRESET_MAP[fname]
        if not preset:
            continue

        fpath = os.path.join(CASE_DATA_DIR_PATH, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for case_name, case_data in data.get('test_cases', {}).items():
            logic = case_data.get('logic', 'query')
            params.append(pytest.param(
                fname, preset, case_name, case_data, logic,
                id=f"{fname.replace('.json', '')}/{case_name}"
            ))

    return params


# ============================================================
#  参数化测试函数
# ============================================================

@pytest.mark.parametrize(
    "json_file, preset_name, case_name, case_data, logic",
    _build_all_case_params()
)
def test_api(
    json_file, preset_name, case_name, case_data, logic,
    api_request, assert_code, base_url, allure_reporter, request_processor
):
    """
    统一参数化测试入口

    根据 JSON test_case 中的 logic 字段，自动分发到对应 handler。
    默认 logic="query"，执行标准请求 + 断言 200。
    """
    # 1. 动态设置 Allure 标签
    config = ALLURE_CONFIGS.get(preset_name, {})
    if config:
        if config.get('suite'):
            allure.dynamic.suite(config['suite'])
        if config.get('epic'):
            allure.dynamic.epic(config['epic'])
        if config.get('sub_suite'):
            allure.dynamic.sub_suite(config['sub_suite'])
        if config.get('severity'):
            allure.dynamic.severity(config['severity'])
        for tag in config.get('tags', []):
            allure.dynamic.tag(tag)

        base_title = config.get('title', '')
        # 提取用例编号: "test_case_1" → 1
        case_num = case_name.replace('test_case_', '') if case_name.startswith('test_case_') else case_name
        # 格式: #1商户申请创建人查询接口测试'mchApply_applyCreatedBy.json
        allure.dynamic.title(f"#{case_num}{base_title}'{json_file}")

    # 2. 获取 handler
    handler, default_expected_code = HANDLERS.get(logic, (_handle_query, 200))

    # 3. 构建上下文
    ctx = {
        'api_request': api_request,
        'assert_code': assert_code,
        'base_url': base_url,
        'allure_reporter': allure_reporter,
        'request_processor': request_processor,
    }

    # 4. 执行
    try:
        response = handler(case_data, ctx)
    except Exception as e:
        error_msg = f"❌ {case_name} - {case_data.get('description', '')} 执行失败: {str(e)}"
        print(error_msg)
        allure_reporter.add_custom_attachment("测试结果", error_msg)
        raise

    # 5. 断言状态码
    expected_code = case_data.get('expected_status', default_expected_code)
    if expected_code is not None:
        assert_code.status_code(response, expected_code)

    # 6. 数据驱动断言（assertions 字段：jsonpath/key/response_time 等）
    _do_assertions(case_data, response, assert_code)

    desc = case_data.get('description', case_name)
    print(f"✅ {case_name} - {desc} 执行成功")
    allure_reporter.add_custom_attachment("测试结果", f"✅ 执行成功: {desc}")
