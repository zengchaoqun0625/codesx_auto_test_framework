"""Layered runtime configuration for environment data and reusable assertions."""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List


CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
ENVIRONMENT_PROFILES_PATH = CONFIG_DIR / "environment_profiles.json"
TEST_DATA_PATH = CONFIG_DIR / "test_data.json"
ASSERTION_RULES_PATH = CONFIG_DIR / "assertion_rules.json"
_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")
_runtime_values: Dict[str, str] = {}


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else default
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是有效 JSON: {path.name}: {exc}") from exc


def get_environment_name() -> str:
    """Return the selected canonical environment name, defaulting to ``test``."""
    config = _read_json(ENVIRONMENT_PROFILES_PATH, {"environments": {}, "aliases": {}})
    raw_name = os.getenv("API_ENV", "test").strip().lower() or "test"
    aliases = config.get("aliases", {})
    if isinstance(aliases, dict):
        raw_name = str(aliases.get(raw_name, raw_name)).lower()
    return raw_name


def get_environment_profile() -> Dict[str, Any]:
    config = _read_json(ENVIRONMENT_PROFILES_PATH, {"environments": {}, "aliases": {}})
    environment = get_environment_name()
    profiles = config.get("environments", {})
    profile = profiles.get(environment) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        raise ValueError(f"未找到环境 '{environment}'，请检查 {ENVIRONMENT_PROFILES_PATH.name}")
    return dict(profile)


def get_variable(name: str, default: str = "") -> str:
    """Resolve variables with runtime extraction > process/.env > selected test data."""
    key = str(name)
    if key in _runtime_values:
        return _runtime_values[key]
    environment_value = os.getenv(key)
    if environment_value is not None:
        return environment_value

    config = _read_json(TEST_DATA_PATH, {"common": {}, "environments": {}})
    values: Dict[str, Any] = {}
    if isinstance(config.get("common"), dict):
        values.update(config["common"])
    environments = config.get("environments", {})
    if isinstance(environments, dict):
        environment_values = environments.get(get_environment_name(), {})
        if isinstance(environment_values, dict):
            values.update(environment_values)
    value = values.get(key, default)
    return str(value) if value is not None else default


def set_runtime_variable(name: str, value: Any) -> None:
    _runtime_values[str(name)] = str(value)


def resolve_variables(value: Any) -> Any:
    """Recursively replace ``${NAME}`` from the layered configuration."""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda match: get_variable(match.group(1)), value)
    if isinstance(value, list):
        return [resolve_variables(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_variables(item) for key, item in value.items()}
    return value


def get_assertion_rules(rule_names: List[str]) -> List[Dict[str, Any]]:
    config = _read_json(ASSERTION_RULES_PATH, {"rules": {}})
    rules = config.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError(f"{ASSERTION_RULES_PATH.name} 的 rules 必须是对象")

    resolved: List[Dict[str, Any]] = []
    for rule_name in rule_names:
        rule_items = rules.get(rule_name)
        if not isinstance(rule_items, list):
            raise ValueError(f"未找到断言规则 '{rule_name}'")
        if not all(isinstance(item, dict) for item in rule_items):
            raise ValueError(f"断言规则 '{rule_name}' 必须是对象数组")
        resolved.extend(rule_items)
    return resolved
