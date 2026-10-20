
import allure
import pytest
import json
from ..config.user_variable import *
# from ..config.case_config import PAYORDER_LIST_CASE_DATA_PATH
#from api_project.testcases.conftest import allure_report,ALLURE_CONFIGS
from api_project.common.allure_decorator import allure_report, ALLURE_CONFIGS, allure_preset

@allure_preset("jqb_login_api")  # 使用预设配置,在commen文件的allure文件配置

@pytest.mark.parametrize("get_case_data", ["payOrder_list.json"], indirect=True)
def test_payorder_list(get_case_data, api_request, assert_code, base_url, allure_reporter, request_processor):
    # 遍历所有测试用例（支持单文件多 case，按 logic 字段区分执行逻辑）
    for case_name, case in get_case_data["test_cases"].items():
        case_desc = case.get("description", "payOrder_list接口测试")
        logic = case.get("logic", "query")  # 默认 query
        # allure.dynamic.title(f"payOrder_list接口测试 - {case_desc}")

        full_url = ""
        method = ""
        request_body = {}
        request_params = {}
        headers = {}

        try:
            # 准备请求参数
            request_data = case["data"]
            full_url = f"{base_url}{request_data.get('url', '')}"
            method = request_data.get("method", "GET")
            request_type = case.get("request_type", "default")
            request_params = request_data.get("params", {})

            # 处理请求参数
            request_body, headers = request_processor.process_request_params(request_type, request_data)

            # 隐藏敏感信息的请求头（用于打印）
            safe_headers = {k: v if k.lower() not in ['authorization', 'token', 'itoken'] else '***' for k, v in headers.items()}

            # 打印请求参数
            print(f"\n【请求】{method} {full_url}")
            if request_params:
                print(f"参数: {json.dumps(request_params, ensure_ascii=False)}")
            if request_body:
                print(f"请求体: {json.dumps(request_body, ensure_ascii=False)}")
            if headers:
                print(f"请求头: {json.dumps(safe_headers, ensure_ascii=False)}")

            # 报告记录请求
            allure.attach(f"{method} {full_url}", "请求信息", allure.attachment_type.TEXT)
            if request_body:
                allure.attach(json.dumps(request_body, indent=2, ensure_ascii=False), "请求体", allure.attachment_type.JSON)
            if headers:
                allure.attach(json.dumps(safe_headers, indent=2, ensure_ascii=False), "请求头", allure.attachment_type.JSON)

            # 发送请求
            response = api_request.send_request(
                url=full_url,
                method=method,
                params=request_params,
                headers=headers,
                **request_body
            )

            # 打印响应
            print(f"【响应】状态码: {response.status_code}")
            try:
                print(f"响应体: {json.dumps(response.json(), ensure_ascii=False)[:500]}")
            except:
                print(f"响应体: {response.text[:500]}")

            # 报告记录响应
            allure.attach(str(response.status_code), "响应状态码", allure.attachment_type.TEXT)
            try:
                allure.attach(json.dumps(response.json(), indent=2, ensure_ascii=False), "响应体", allure.attachment_type.JSON)
            except:
                allure.attach(response.text, "响应体", allure.attachment_type.TEXT)

            # 断言（logic="expect_error" 时不固定状态码，此处 assert 200）
            assert_code.status_code(response, 200)
            print(f"✅ {case_name} - {case_desc} [logic={logic}] 执行成功")
            allure_reporter.add_custom_attachment("测试结果", f"✅ 执行成功: {case_desc}")

        except Exception as e:
            error_msg = f"❌ {case_name} - {case_desc} 执行失败: {str(e)}"
            print(error_msg)
            print(f"请求URL: {full_url}")
            allure_reporter.add_custom_attachment("测试结果", error_msg)

            # 失败时也记录请求信息
            if request_body:
                allure.attach(json.dumps(request_body, indent=2, ensure_ascii=False), "失败-请求体", allure.attachment_type.JSON)
            if headers:
                safe_headers = {k: v if k.lower() not in ['authorization', 'token', 'itoken'] else '***' for k, v in headers.items()}
                allure.attach(json.dumps(safe_headers, indent=2, ensure_ascii=False), "失败-请求头", allure.attachment_type.JSON)
            raise
