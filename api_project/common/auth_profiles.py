"""Role-based authentication profile loader.

Profiles contain endpoint metadata only.  Credentials stay in ``api_project/.env``
and are referenced with ``${ENV_VAR}`` placeholders in the login request.
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict


AUTH_PROFILES_PATH = Path(__file__).resolve().parent.parent / "config" / "auth_profiles.json"


class AuthProfileError(ValueError):
    """Raised when an authentication profile is absent or malformed."""


def get_auth_profile(profile_name: str) -> Dict[str, Any]:
    """Load one named authentication profile from the project configuration."""
    name = str(profile_name or "").strip()
    if not name:
        raise AuthProfileError("auth_profile 不能为空")
    if not AUTH_PROFILES_PATH.exists():
        raise AuthProfileError(f"未找到认证配置文件: {AUTH_PROFILES_PATH}")

    try:
        with AUTH_PROFILES_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except json.JSONDecodeError as exc:
        raise AuthProfileError(f"认证配置文件不是有效 JSON: {exc}") from exc

    profiles = config.get("profiles", {}) if isinstance(config, dict) else {}
    profile = profiles.get(name) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        raise AuthProfileError(f"未找到认证角色 '{name}'，请检查 {AUTH_PROFILES_PATH.name}")

    login = profile.get("login")
    token_env = str(profile.get("token_env", "")).strip()
    if not token_env and not isinstance(login, dict):
        raise AuthProfileError(f"认证角色 '{name}' 必须配置 token_env 或 login")
    if isinstance(login, dict) and not str(profile.get("token_variable", "")).strip():
        raise AuthProfileError(f"认证角色 '{name}' 配置 login 时必须同时配置 token_variable")

    return copy.deepcopy(profile)
