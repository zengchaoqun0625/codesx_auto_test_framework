"""Validated environment settings shared by runtime entry points."""
import logging
import os


logger = logging.getLogger(__name__)
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def get_bool_env(name: str, default: bool = False, environ=None) -> bool:
    """Read an explicit boolean; invalid values fall back safely with a warning."""
    environment = os.environ if environ is None else environ
    raw = environment.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    logger.warning("环境变量 %s=%r 不是有效布尔值，使用默认值 %s", name, raw, default)
    return default


def get_positive_float_env(name: str, default: float, environ=None) -> float:
    """Read a positive float and safely fall back for invalid configuration."""
    environment = os.environ if environ is None else environ
    raw = environment.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    logger.warning("环境变量 %s=%r 必须是正数，使用默认值 %s", name, raw, default)
    return default
