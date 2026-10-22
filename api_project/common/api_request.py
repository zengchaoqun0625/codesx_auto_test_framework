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
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import requests
from requests import Response
from requests.exceptions import RequestException, Timeout
from api_project.common.settings import get_bool_env, get_positive_float_env

logger = logging.getLogger(__name__)

# 默认请求超时（秒）：环境变量 API_TIMEOUT 可覆盖
DEFAULT_TIMEOUT = get_positive_float_env("API_TIMEOUT", 10.0)
DEFAULT_VERIFY_TLS = get_bool_env("API_VERIFY_TLS", default=True)

# Credentials can appear under many vendor-specific header names.  Keep this
# policy close to the HTTP client so terminal logs and every report use it.
_SENSITIVE_FIELD_PARTS = (
    "authorization", "cookie", "token", "secret", "password", "passwd", "pwd",
    "api-key", "apikey", "api_key", "accesskey", "access_key", "privatekey",
    "private_key", "credential", "client_secret", "sign", "signature",
)
_PHONE_FIELD_PARTS = ("phone", "mobile", "telephone", "tel", "contact_number")
_ID_FIELD_PARTS = ("idcard", "id_card", "identity", "certificate_no", "cert_no")
_BANK_FIELD_PARTS = ("bankcard", "bank_card", "card_no", "cardnumber", "account_no")
_MASK = "*******"
_RETRY_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "request_retry.json"


def _load_retry_policy() -> Dict[str, Any]:
    """Load retry policy once per request so edits are effective on the next run."""
    default = {
        "enabled": True,
        "max_attempts": 3,
        "backoff_seconds": 0.5,
        "retry_status_codes": [429, 502, 503],
        "retry_timeout": True,
        "safe_methods": ["GET", "HEAD", "OPTIONS"],
        "retry_write_requests": False,
    }
    if not _RETRY_CONFIG_PATH.exists():
        return default
    try:
        with _RETRY_CONFIG_PATH.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        if isinstance(loaded, dict):
            default.update(loaded)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("⚠️ 请求重试配置读取失败，使用默认策略: %s", exc)

    default["max_attempts"] = max(1, int(default["max_attempts"]))
    default["backoff_seconds"] = max(0.0, float(default["backoff_seconds"]))
    default["retry_status_codes"] = {int(code) for code in default["retry_status_codes"]}
    default["safe_methods"] = {str(method).upper() for method in default["safe_methods"]}
    return default


def _mask_value(value: Any) -> str:
    """Mask a value for display without revealing its length."""
    text = str(value)
    if len(text) <= 6:
        return _MASK
    return f"{text[:3]}{_MASK}{text[-3:]}"


def _field_matches(key: object, candidates: tuple[str, ...]) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(candidate.replace("-", "_") in normalized for candidate in candidates)


def _sanitize_text(text: str) -> str:
    """Mask common PII in unstructured response and form text."""
    # Chinese mobile numbers and 18-digit identity numbers retain only three
    # characters on either side, matching the display convention used by the UI.
    text = re.sub(r"(?<!\d)(1[3-9]\d)\d{5}(\d{3})(?!\d)", rf"\1{_MASK}\2", text)
    text = re.sub(r"(?<!\d)(\d{3})\d{12}(\d{3})(?!\d)", rf"\1{_MASK}\2", text)
    text = re.sub(
        r"(?i)((?:authorization|cookie|token|secret|password|passwd|pwd|api[_-]?key|signature)\s*[:=]\s*[\"']?)([^\s\"'&,;}]+)",
        lambda match: f"{match.group(1)}{_mask_value(match.group(2))}",
        text,
    )
    return text


def sanitize_for_display(value: Any, key: object = "") -> Any:
    """Return a recursively masked copy suitable for logs and reports.

    This function is intentionally display-only: callers must keep using their
    original request data when making HTTP calls or extracting variables.
    """
    if _field_matches(key, _SENSITIVE_FIELD_PARTS):
        return _mask_value(value)
    if _field_matches(key, _PHONE_FIELD_PARTS) or _field_matches(key, _ID_FIELD_PARTS) or _field_matches(key, _BANK_FIELD_PARTS):
        return _mask_value(value)
    if isinstance(value, Mapping):
        return {item_key: sanitize_for_display(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize_for_display(item, key) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_display(item, key) for item in value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.dumps(sanitize_for_display(json.loads(value)), ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        return _sanitize_text(value)
    return value


def sanitize_url(url: str) -> str:
    """Mask sensitive query parameter values in a URL shown to users."""
    try:
        parsed = urlsplit(url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        safe_query = urlencode([(key, sanitize_for_display(value, key)) for key, value in query], doseq=True, safe="*")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, safe_query, parsed.fragment))
    except (TypeError, ValueError):
        return _sanitize_text(str(url))


def sanitize_headers(headers: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a display-safe copy of request or response headers.

    The original mapping is never changed because it may still be needed to
    make the HTTP request.
    """
    if not isinstance(headers, Mapping):
        return {}
    return sanitize_for_display(headers)


class ApiRequest:
    def __init__(self):
        self.session = requests.Session()
        # 默认直连：忽略环境变量中的 HTTP_PROXY/HTTPS_PROXY 代理设置
        # （本地代理未启动/握手失败时 requests 会报 Connection aborted / FileNotFoundError / SSL EOF）
        # 需要走代理时：设置 PROXY_ENABLED=true（或 1/yes），将恢复读取环境代理
        self.session.trust_env = os.getenv("PROXY_ENABLED", "").strip().lower() in ("1", "true", "yes")
        self._init_default_headers()
        self.login_token: Optional[str] = None
        self.login_tokens: Dict[str, str] = {}
        self.global_use_token: bool = True
        self.default_token_header_name = os.getenv("API_TOKEN_HEADER", "iToken").strip() or "iToken"
        self.token_prefix = os.getenv("API_TOKEN_PREFIX", "").strip()
        # 静态 token：从 config/user_variable.py 加载（未配置则为 None，保持原有行为）
        self.user_token: Optional[str] = self._load_user_token()
        # 401 自动重登回调（由外部注册：login_handler() -> 返回新 token 字符串）
        self.login_handler = None
        self.login_handlers = {}
        self._retrying_401 = False
        # 新增：记录最近一次请求和响应
        self.last_request_info = None
        self.last_response_info = None

    def set_login_handler(self, handler, auth_profile: str = "default") -> "ApiRequest":
        """
        注册 401 自动重登回调。
        :param handler: 无参可调用对象，返回新 token 字符串（失败返回 None/空则放弃重试）
        """
        if callable(handler):
            profile_name = str(auth_profile or "default")
            self.login_handlers[profile_name] = handler
            if profile_name == "default":
                self.login_handler = handler
            logger.info("✅ 已注册 %s 的 401 自动重登处理器", profile_name)
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
        env_token = os.getenv("API_TOKEN", "").strip() or os.getenv("API_ITOKEN", "").strip()
        if env_token:
            logger.info("✅ 已从环境变量 API_TOKEN/API_ITOKEN 加载默认鉴权 token")
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

    def set_login_token(self, token: str, auth_profile: str = "default") -> "ApiRequest":
        """设置动态登录Token（如登录接口返回的Token）"""
        if isinstance(token, str) and token.strip():
            profile_name = str(auth_profile or "default")
            self.login_tokens[profile_name] = token.strip()
            if profile_name == "default":
                self.login_token = token.strip()
            logger.info("✅ 已设置 %s 的动态登录 Token", profile_name)
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

    def _prepare_headers(
        self,
        use_token: Optional[bool] = None,
        token_header_name: Optional[str] = None,
        token_prefix: Optional[str] = None,
        auth_profile: str = "default",
    ) -> Dict[str, str]:
        """
        准备请求头
        :param use_token: 是否使用Token
        :param token_header_name: Token 的 header 名称；未传时使用 API_TOKEN_HEADER/iToken。
        """
        # 清除旧的 token headers
        final_header_name = (token_header_name or self.default_token_header_name).strip()
        for header_name in {"iToken", "Authorization", "AccessToken", "Token", final_header_name}:
            self.session.headers.pop(header_name, None)

        # 确定最终是否使用Token
        final_use_token = self.global_use_token if use_token is None else use_token
        if not final_use_token:
            logger.info("ℹ️ 当前请求不使用Token（临时禁用）")
            return self.session.headers

        # 选择使用的Token
        profile_name = str(auth_profile or "default")
        token = self.login_tokens.get(profile_name)
        if token is None and profile_name == "default":
            token = self.login_token or self.user_token

        if token:
            final_token_prefix = self.token_prefix if token_prefix is None else str(token_prefix).strip()
            token_value = f"{final_token_prefix} {token}".strip() if final_token_prefix else token
            self.session.headers[final_header_name] = token_value
            logger.info(f"ℹ️ 请求头已添加 {final_header_name}")
        else:
            logger.warning("⚠️ 无可用Token")

        return self.session.headers

    def _record_response(self, response: Response) -> None:
        """记录响应信息（含耗时），供报告/通知使用"""
        self.last_response_info = {
            "status_code": response.status_code,
            "headers": sanitize_headers(response.headers),
            "text": sanitize_for_display(response.text)[:2000],  # 限制长度避免报告过大
            "elapsed": round(response.elapsed.total_seconds(), 4),  # 响应耗时（秒）
        }

    def _send_with_retry(self, method: str, url: str, retry: Optional[bool], **kwargs: Any) -> Response:
        """Retry only configured transient failures; unsafe methods require explicit opt-in."""
        policy = _load_retry_policy()
        method_upper = method.upper()
        retry_allowed = bool(policy["enabled"]) and retry is not False and (
            retry is True
            or method_upper in policy["safe_methods"]
            or bool(policy["retry_write_requests"])
        )
        attempts = policy["max_attempts"] if retry_allowed else 1

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(method, url, **kwargs)
            except RequestException as exc:
                can_retry_timeout = (
                    isinstance(exc, Timeout)
                    and bool(policy["retry_timeout"])
                    and attempt < attempts
                )
                if not can_retry_timeout:
                    raise
                delay = policy["backoff_seconds"] * attempt
                logger.warning("⚠️ 请求超时，第 %s/%s 次重试将在 %.2fs 后执行: %s", attempt, attempts, delay, url)
                time.sleep(delay)
                continue

            if response.status_code in policy["retry_status_codes"] and attempt < attempts:
                delay = policy["backoff_seconds"] * attempt
                logger.warning(
                    "⚠️ 收到可重试状态码 %s，第 %s/%s 次重试将在 %.2fs 后执行: %s",
                    response.status_code, attempt, attempts, delay, url,
                )
                time.sleep(delay)
                continue
            return response

        raise RuntimeError("请求重试流程异常结束")

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
            token_header_name: Optional[str] = None,
            token_prefix: Optional[str] = None,
            auth_profile: str = "default",
            retry: Optional[bool] = None,
            **kwargs: Any
    ) -> Response:
        """发送API请求，并记录请求/响应信息（含默认超时、响应时间、401自动重登）"""
        # 默认超时：防止接口挂死导致无限等待（用例可通过 timeout 参数覆盖）
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        # 默认校验证书；仅在开发环境明确设置 API_VERIFY_TLS=false 时关闭。
        kwargs.setdefault("verify", DEFAULT_VERIFY_TLS)

        # 统一由 _prepare_headers 注入 token，避免 JSON 中的旧 token 覆盖当前 token。
        final_use_token = self.global_use_token if use_token is None else use_token
        profile_name = str(auth_profile or "default")
        active_login_token = self.login_tokens.get(profile_name)
        if final_use_token and (self.user_token or active_login_token or (profile_name == "default" and self.login_token)):
            req_headers = kwargs.get("headers") or {}
            final_header_name = (token_header_name or self.default_token_header_name).lower()
            managed_headers = {"itoken", "authorization", "accesstoken", "token", final_header_name}
            stripped_headers = {
                k: v for k, v in req_headers.items()
                if k.lower() not in managed_headers
            }
            if len(stripped_headers) != len(req_headers):
                kwargs["headers"] = stripped_headers
                logger.info("ℹ️ 已剥离用例数据中的 token 请求头，改用环境变量/用户配置中的默认 token")

        # 记录请求信息
        self.last_request_info = {
            "method": method.upper(),
            "url": sanitize_url(url),
            "headers": sanitize_headers(kwargs.get("headers", {})),
            "params": sanitize_for_display(kwargs.get("params", {})),
            "body": sanitize_for_display(kwargs.get("json") or kwargs.get("data") or "")
        }

        try:
            domain = self._check_url(url)
            method = method.strip().lower()
            self._prepare_headers(use_token, token_header_name, token_prefix, profile_name)

            logger.info(f"📤 发送请求: {method.upper()} {sanitize_url(url)}")
            if "params" in kwargs:
                logger.debug(f"📤 请求参数: {json.dumps(sanitize_for_display(kwargs['params']), ensure_ascii=False)}")
            if "data" in kwargs or "json" in kwargs:
                body_key = "data" if "data" in kwargs else "json"
                logger.debug(f"📤 请求体: {json.dumps(sanitize_for_display(kwargs[body_key]), ensure_ascii=False)}")
            logger.debug(f"📤 请求头: {json.dumps(sanitize_headers(self.session.headers), ensure_ascii=False)}")

            response = self._send_with_retry(method, url, retry, **kwargs)
            logger.info(f"📥 响应状态码: {response.status_code}，耗时: {response.elapsed.total_seconds():.3f}s")

            # 记录响应信息（含耗时）
            self._record_response(response)

            # ---- 401 自动重登重试（仅一次） ----
            login_handler = self.login_handlers.get(profile_name)
            if login_handler is None and profile_name == "default":
                login_handler = self.login_handler
            if response.status_code == 401 and not self._retrying_401 and login_handler:
                self._retrying_401 = True
                try:
                    logger.warning("⚠️ 响应 401 未授权，尝试重新登录获取新 token ...")
                    new_token = login_handler()
                    if new_token:
                        self.set_login_token(new_token, profile_name)
                        self._prepare_headers(use_token, token_header_name, token_prefix, profile_name)
                        logger.info(f"✅ 已获取新 token，重发请求: {method.upper()} {url}")
                        response = self._send_with_retry(method, url, retry, **kwargs)
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
