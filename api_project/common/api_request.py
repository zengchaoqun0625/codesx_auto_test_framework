#! /usr/bin/env python
# -*- coding: utf-8 -*-
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@qq.com
createTime  : 2026/08/06  23:28
fileName    : api_request.py
Description : API请求封装，基于requests.Session的统一HTTP客户端（支持Token管理、请求日志、异常处理）
'''
import importlib
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from requests import Response
from requests.exceptions import RequestException
from api_project.common.settings import get_bool_env, get_positive_float_env

logger = logging.getLogger(__name__)

# 默认请求超时（秒）：环境变量 API_TIMEOUT 可覆盖
DEFAULT_TIMEOUT = get_positive_float_env("API_TIMEOUT", 10.0)
DEFAULT_VERIFY_TLS = get_bool_env("API_VERIFY_TLS", default=True)

# Credentials can appear under many vendor-specific header names.  Keep this
# policy close to the HTTP client so terminal logs and every report use it.
_SENSITIVE_HEADER_PARTS = ("authorization", "cookie", "token", "secret", "password", "api-key", "apikey")


def sanitize_headers(headers: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a copy of headers with credentials replaced by ``***``.

    The original mapping is never changed because it may still be needed to
    make the HTTP request.
    """
    if not isinstance(headers, Mapping):
        return {}
    return {
        key: "***" if any(part in str(key).lower() for part in _SENSITIVE_HEADER_PARTS) else value
        for key, value in headers.items()
    }


class ApiRequest:
    def __init__(self):
        self.session = requests.Session()
        # 默认直连：忽略环境变量中的 HTTP_PROXY/HTTPS_PROXY 代理设置
        # （本地代理未启动/握手失败时 requests 会报 Connection aborted / FileNotFoundError / SSL EOF）
        # 需要走代理时：设置 PROXY_ENABLED=true（或 1/yes），将恢复读取环境代理
        self.session.trust_env = os.getenv("PROXY_ENABLED", "").strip().lower() in ("1", "true", "yes")
        self._init_default_headers()
        self.login_token: Optional[str] = None
        self.global_use_token: bool = True
        # 静态 token：从 config/user_variable.py 加载（未配置则为 None，保持原有行为）
        self.user_token: Optional[str] = self._load_user_token()
        # 401 自动重登回调（由外部注册：login_handler() -> 返回新 token 字符串）
        self.login_handler = None
        self._retrying_401 = False
        # 新增：记录最近一次请求和响应
        self.last_request_info = None
        self.last_response_info = None

    def set_login_handler(self, handler) -> "ApiRequest":
        """
        注册 401 自动重登回调。
        :param handler: 无参可调用对象，返回新 token 字符串（失败返回 None/空则放弃重试）
        """
        if callable(handler):
            self.login_handler = handler
            logger.info("✅ 已注册 401 自动重登处理器")
        else:
            logger.warning("❌ login_handler 必须是可调用对象")
        return self  # 支持链式调用

    def _init_default_headers(self) -> None:
        """初始化默认请求头（避免重复设置）"""
        default_headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "API-Test-Framework/1.0 (Python)"
        }
        self.session.headers.update(default_headers)

    def _load_user_token(self) -> Optional[str]:
        """Load the default token from the environment, then legacy config."""
        env_token = os.getenv("API_ITOKEN", "").strip()
        if env_token:
            logger.info("✅ 已从环境变量 API_ITOKEN 加载默认鉴权 token")
            return env_token

        current_file = Path(__file__).resolve()
        # 当前文件在 common/ 目录，config/ 在同级
        user_token_path = current_file.parent.parent / "config" / "user_variable.py"
        if not user_token_path.exists():
            logger.warning(f"⚠️  未找到user_variable.py文件，路径: {str(user_token_path)}")
            return None

        try:
            spec = importlib.util.spec_from_file_location("user_variable", str(user_token_path))
            user_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(user_module)

            # 候选变量名（按优先级）：兼容 token / iToken / itoken 等常见命名
            # 注意：变量名只影响读取，发送时统一以 iToken 请求头发送
            for var_name in ("token", "iToken", "itoken", "TOKEN", "I_TOKEN", "ITOKEN"):
                if hasattr(user_module, var_name) and isinstance(getattr(user_module, var_name), str):
                    token = getattr(user_module, var_name).strip()
                    if token:
                        logger.info(f"✅ 从user_variable.py加载静态Token成功（变量名: {var_name}）")
                        return token
            logger.warning("⚠️ user_variable.py中未定义有效的token/iToken变量")
            return None
        except Exception as e:
            logger.error(f"❌ 加载user_variable.py的token失败: {str(e)}", exc_info=True)
            return None

    def set_login_token(self, token: str) -> "ApiRequest":
        """设置动态登录Token（如登录接口返回的Token）"""
        if isinstance(token, str) and token.strip():
            self.login_token = token.strip()
            logger.info("✅ 已设置动态登录Token")
        else:
            logger.warning("❌ 无效的Token值（必须是非空字符串）")
        return self  # 支持链式调用

    def enable_token(self, enable: bool = True) -> "ApiRequest":
        """设置全局是否使用Token（临时关闭Token场景）"""
        self.global_use_token = enable
        logger.info(f"✅ 全局Token开关已设置为: {'启用' if enable else '禁用'}")
        return self  # 支持链式调用

    def set_headers(self, headers: Dict[str, str]) -> "ApiRequest":
        """追加自定义请求头（覆盖默认头）"""
        if isinstance(headers, dict) and headers:
            self.session.headers.update(headers)
            logger.info(f"✅ 已追加自定义请求头: {list(headers.keys())}")
        else:
            logger.warning("❌ 无效的请求头（必须是非空字典）")
        return self  # 支持链式调用

    def _prepare_headers(self, use_token: Optional[bool] = None, token_header_name: str = "iToken") -> Dict[str, str]:
        """
        准备请求头
        :param use_token: 是否使用Token
        :param token_header_name: Token的header名称，默认为 "iToken"
        """
        # 清除旧的 token headers
        self.session.headers.pop("iToken", None)
        self.session.headers.pop("Authorization", None)

        # 确定最终是否使用Token
        final_use_token = self.global_use_token if use_token is None else use_token
        if not final_use_token:
            logger.info("ℹ️ 当前请求不使用Token（临时禁用）")
            return self.session.headers

        # 选择使用的Token
        token = self.login_token if self.login_token else self.user_token

        if token:
            # 使用配置的 header 名称
            self.session.headers[token_header_name] = token
            logger.info(f"ℹ️ 请求头已添加 {token_header_name}")
        else:
            logger.warning("⚠️ 无可用Token")

        return self.session.headers

    def _record_response(self, response: Response) -> None:
        """记录响应信息（含耗时），供报告/通知使用"""
        self.last_response_info = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "text": response.text[:2000],  # 限制长度避免报告过大
            "elapsed": round(response.elapsed.total_seconds(), 4),  # 响应耗时（秒）
        }

    def _check_url(self, url: str) -> str:
        """
        验证URL格式有效性
        - 抛出明确的错误提示（便于定位问题）
        - 返回域名用于后续错误分析
        """
        if not url:
            raise ValueError("❌ URL不能为空！请检查base_url配置或用例中的URL设置")

        if not url.startswith(("http://", "https://")):
            raise ValueError(
                f"❌ URL格式无效: {url}\n"
                "必须以http://或https://开头，建议修正为：\n"
                f"https://{url} 或 http://{url}"
            )

        try:
            parsed_url = urlparse(url)
            if not parsed_url.netloc:  # 检查域名是否存在
                raise ValueError(f"❌ URL缺少有效域名: {url}")
            return parsed_url.netloc
        except Exception as e:
            raise ValueError(f"❌ 无法解析URL: {url}，错误原因: {str(e)}") from e

    def send_request(
            self,
            method: str,
            url: str,
            use_token: Optional[bool] = None,
            token_header_name: str = "iToken",
            **kwargs: Any
    ) -> Response:
        """发送API请求，并记录请求/响应信息（含默认超时、响应时间、401自动重登）"""
        # 默认超时：防止接口挂死导致无限等待（用例可通过 timeout 参数覆盖）
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        # 默认校验证书；仅在开发环境明确设置 API_VERIFY_TLS=false 时关闭。
        kwargs.setdefault("verify", DEFAULT_VERIFY_TLS)

        # 静态 token 优先：user_variable.py 已配置 token 时，
        # 剥离用例数据中写死的 token 请求头，统一由 _prepare_headers 注入新 token
        if self.user_token:
            req_headers = kwargs.get("headers") or {}
            stripped_headers = {
                k: v for k, v in req_headers.items()
                if k.lower() not in ("itoken", "authorization", "accesstoken", "token")
            }
            if len(stripped_headers) != len(req_headers):
                kwargs["headers"] = stripped_headers
                logger.info("ℹ️ 已剥离用例数据中的 token 请求头，改用环境变量/用户配置中的默认 token")

        # 记录请求信息
        self.last_request_info = {
            "method": method.upper(),
            "url": url,
            "headers": sanitize_headers(kwargs.get("headers", {})),
            "params": kwargs.get("params", {}),
            "body": kwargs.get("json") or kwargs.get("data") or ""
        }

        try:
            domain = self._check_url(url)
            method = method.strip().lower()
            self._prepare_headers(use_token, token_header_name)

            logger.info(f"📤 发送请求: {method.upper()} {url}")
            if "params" in kwargs:
                logger.debug(f"📤 请求参数: {json.dumps(kwargs['params'], ensure_ascii=False)}")
            if "data" in kwargs or "json" in kwargs:
                body_key = "data" if "data" in kwargs else "json"
                logger.debug(f"📤 请求体: {json.dumps(kwargs[body_key], ensure_ascii=False)}")
            logger.debug(f"📤 请求头: {json.dumps(dict(self.session.headers), ensure_ascii=False)}")

            response = self.session.request(method, url, **kwargs)
            logger.info(f"📥 响应状态码: {response.status_code}，耗时: {response.elapsed.total_seconds():.3f}s")

            # 记录响应信息（含耗时）
            self._record_response(response)

            # ---- 401 自动重登重试（仅一次） ----
            if response.status_code == 401 and not self._retrying_401 and self.login_handler:
                self._retrying_401 = True
                try:
                    logger.warning("⚠️ 响应 401 未授权，尝试重新登录获取新 token ...")
                    new_token = self.login_handler()
                    if new_token:
                        self.set_login_token(new_token)
                        self._prepare_headers(use_token, token_header_name)
                        logger.info(f"✅ 已获取新 token，重发请求: {method.upper()} {url}")
                        response = self.session.request(method, url, **kwargs)
                        self._record_response(response)
                        logger.info(
                            f"📥 重发后响应状态码: {response.status_code}，"
                            f"耗时: {response.elapsed.total_seconds():.3f}s"
                        )
                    else:
                        logger.warning("⚠️ 登录回调未返回有效 token，放弃重试")
                except Exception as e:
                    logger.error(f"❌ 401 自动重登失败: {str(e)}", exc_info=True)
                finally:
                    self._retrying_401 = False

            return response

        except RequestException as e:
            # 原有的异常处理保持不变...
            error_msg = str(e)
            if any(keyword in error_msg for keyword in ["Failed to resolve", "getaddrinfo failed"]):
                raise ConnectionError(
                    f"❌ 无法连接到服务器: {domain}\n"
                    "可能的原因：\n"
                    f"1. 域名不存在或拼写错误: {domain}\n"
                    "2. 网络无法访问该域名（检查DNS/防火墙）\n"
                    f"3. 主机地址配置错误（当前URL: {url}）"
                ) from e
            elif "timeout" in error_msg:
                raise TimeoutError(
                    f"❌ 请求超时: {url}\n"
                    "建议操作：\n"
                    "1. 检查目标服务器是否正常运行\n"
                    "2. 增加超时时间（通过timeout参数）\n"
                    "3. 检查网络稳定性"
                ) from e
            else:
                raise RequestException(f"❌ 请求发送失败: {str(e)}") from e
