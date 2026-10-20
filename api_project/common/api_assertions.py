"""
API 断言封装类
- 覆盖常见断言场景：状态码、JSON键值、响应时间等
- 统一错误提示格式（便于定位问题）
- 支持链式调用（简化断言代码）
"""

import json
import logging
from typing import Any, Dict
from requests import Response

logger = logging.getLogger(__name__)


class ApiAssert:
    """API断言封装类"""

    @staticmethod
    def status_code(response: Response, expected_code: int) -> "ApiAssert":
        """断言响应状态码"""
        actual_code = response.status_code
        assert actual_code == expected_code, (
            f"❌ 状态码断言失败\n"
            f"预期: {expected_code} | 实际: {actual_code}\n"
            f"请求URL: {response.request.url}"
        )
        logger.info(f"✅ 状态码断言通过: 预期{expected_code}，实际{actual_code}")
        return ApiAssert  # 支持链式调用

    @staticmethod
    def json_key_exists(response_json: Dict[str, Any], key: str) -> "ApiAssert":
        """断言JSON响应中存在指定键"""
        assert key in response_json, (
            f"❌ JSON键存在性断言失败\n"
            f"缺失键: {key}\n"
            f"当前JSON: {json.dumps(response_json, ensure_ascii=False, indent=2)}"
        )
        logger.info(f"✅ JSON键存在性断言通过: 键[{key}]存在")
        return ApiAssert  # 支持链式调用

    @staticmethod
    def json_value(
        response_json: Dict[str, Any],
        key: str,
        expected_value: Any
    ) -> "ApiAssert":
        """断言JSON响应中指定键的取值等于预期值"""
        ApiAssert.json_key_exists(response_json, key)  # 先确保键存在
        actual_value = response_json[key]
        assert actual_value == expected_value, (
            f"❌ JSON值断言失败\n"
            f"键: {key}\n"
            f"预期: {expected_value} | 实际: {actual_value}\n"
            f"当前JSON: {json.dumps(response_json, ensure_ascii=False, indent=2)}"
        )
        logger.info(f"✅ JSON值断言通过: 键[{key}]，预期{expected_value}，实际{actual_value}")
        return ApiAssert  # 支持链式调用

    @staticmethod
    def json_value_contains(
        response_json: Dict[str, Any],
        key: str,
        expected_substring: str
    ) -> "ApiAssert":
        """断言JSON响应中指定键的取值包含预期子串"""
        ApiAssert.json_key_exists(response_json, key)  # 先确保键存在
        actual_value = str(response_json[key])  # 统一转为字符串比较
        assert expected_substring in actual_value, (
            f"❌ JSON值包含性断言失败\n"
            f"键: {key}\n"
            f"预期包含: {expected_substring} | 实际: {actual_value}\n"
            f"当前JSON: {json.dumps(response_json, ensure_ascii=False, indent=2)}"
        )
        logger.info(
            f"✅ JSON值包含性断言通过: 键[{key}]，实际值包含{expected_substring}"
        )
        return ApiAssert  # 支持链式调用

    @staticmethod
    def response_time(response: Response, max_time: float) -> "ApiAssert":
        """断言响应时间不超过最大值（单位：秒）"""
        actual_time = response.elapsed.total_seconds()
        assert actual_time <= max_time, (
            f"❌ 响应时间断言失败\n"
            f"最大允许: {max_time}s | 实际: {actual_time:.3f}s\n"
            f"请求URL: {response.request.url}"
        )
        logger.info(
            f"✅ 响应时间断言通过: 实际{actual_time:.3f}s，最大允许{max_time}s"
        )
        return ApiAssert  # 支持链式调用

    @staticmethod
    def json_length_equals(
        response_json: Dict[str, Any],
        key: str,
        expected_length: int
    ) -> "ApiAssert":
        """断言JSON响应中指定键的取值长度等于预期值（适用于列表/字符串）"""
        ApiAssert.json_key_exists(response_json, key)  # 先确保键存在
        actual_value = response_json[key]

        # 检查是否支持长度计算
        if not hasattr(actual_value, "__len__"):
            raise TypeError(
                f"❌ JSON长度断言失败: 键[{key}]的取值类型{type(actual_value)}不支持长度计算"
            )

        actual_length = len(actual_value)
        assert actual_length == expected_length, (
            f"❌ JSON长度断言失败\n"
            f"键: {key}\n"
            f"预期长度: {expected_length} | 实际长度: {actual_length}\n"
            f"当前取值: {actual_value}"
        )
        logger.info(
            f"✅ JSON长度断言通过: 键[{key}]，预期长度{expected_length}，实际长度{actual_length}"
        )
        return ApiAssert  # 支持链式调用
