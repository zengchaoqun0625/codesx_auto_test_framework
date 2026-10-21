"""
请求参数处理器：统一处理不同类型的请求参数（formdata/json/data）
- 自动识别请求类型（formdata/json/data）
- 补全默认Content-Type（避免手动设置）
- 兼容字符串/字典格式的请求体
"""

import json
import logging
from typing import Any, Dict
from api_project.common.runtime_config import resolve_variables

logger = logging.getLogger(__name__)
def _resolve_env_references(value: Any) -> Any:
    """Resolve ``${NAME}`` placeholders so secrets stay out of case JSON."""
    return resolve_variables(value)


class RequestProcessor:
    """请求参数处理器"""

    @staticmethod
    def get_request_type(request: Dict[str, Any]) -> str:
        """
        判断请求参数类型（优先级：formdata > json > data > default）
        :param request: 原始请求参数字典
        :return: 请求类型字符串（formdata/json/data/default）
        """
        if "formdata" in request and request["formdata"]:
            logger.debug("ℹ️ 识别请求类型为: formdata")
            return "formdata"
        elif "json" in request and request["json"]:
            logger.debug("ℹ️ 识别请求类型为: json")
            return "json"
        elif "data" in request and request["data"]:
            logger.debug("ℹ️ 识别请求类型为: data")
            return "data"
        logger.debug("ℹ️ 未识别到明确请求类型，使用default")
        return "default"

    @staticmethod
    def process_request_params(
        request_type: str,
        request_data: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Dict[str, str]]:
        """
        处理请求参数：生成requests库兼容的请求体和请求头
        :param request_type: 请求类型（formdata/json/data/default）
        :param request_data: 原始请求参数字典
        :return: (处理后的请求体, 处理后的请求头)
        """
        # 复制请求头（避免修改原始数据）
        headers = {
            key: _resolve_env_references(value)
            for key, value in request_data.get("headers", {}).items()
        }
        request_body = {}

        if request_type == "formdata":
            # 处理formdata（multipart/form-data）
            request_body["data"] = request_data.get("formdata", {})
            # 补全默认Content-Type（requests会自动处理boundary）
            if "Content-Type" not in headers:
                headers["Content-Type"] = "multipart/form-data"
            logger.debug(f"ℹ️ 处理formdata请求体: {list(request_body['data'].keys())}")

        elif request_type == "json":
            # 处理json请求体（application/json）
            request_body["json"] = request_data.get("json", {})
            # 补全默认Content-Type
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
            logger.debug(f"ℹ️ 处理json请求体: {json.dumps(request_body['json'], ensure_ascii=False)}")

        elif request_type == "data":
            # 处理data请求体（兼容JSON字符串/表单字符串）
            data_content = request_data.get("data", {})
            if isinstance(data_content, str):
                try:
                    # 尝试解析为JSON（如：'{"key":"value"}'）
                    request_body["json"] = json.loads(data_content)
                    headers["Content-Type"] = headers.get("Content-Type", "application/json")
                    logger.debug(f"ℹ️ data字符串解析为json: {request_body['json']}")
                except json.JSONDecodeError:
                    # 解析失败则视为表单数据（如：'key1=value1&key2=value2'）
                    request_body["data"] = data_content
                    headers["Content-Type"] = headers.get(
                        "Content-Type", "application/x-www-form-urlencoded"
                    )
                    logger.debug(f"ℹ️ data字符串视为表单数据: {data_content}")
            else:
                # 非字符串类型直接作为data（如字典）
                request_body["data"] = data_content
                headers["Content-Type"] = headers.get(
                    "Content-Type", "application/x-www-form-urlencoded"
                )
                logger.debug(f"ℹ️ 处理data请求体: {request_body['data']}")

        # 打印最终处理结果（便于调试）
        logger.debug(f"ℹ️ 最终请求头: {list(headers.keys())}")
        logger.debug(f"ℹ️ 最终请求体类型: {list(request_body.keys())}")

        return request_body, headers
