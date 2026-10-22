"""Local web console for the API test framework.

Run with ``python web_app.py`` and open http://127.0.0.1:5000.
The console deliberately binds to localhost only: it may start real API tests
and exposes local reports, so it must not be published without authentication.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from apscheduler.triggers.cron import CronTrigger


ROOT = Path(__file__).resolve().parent
CASE_DIR = ROOT / "api_project" / "case_data_files"
CONFIG_DIR = ROOT / "api_project" / "config"
REPORT_DIR = ROOT / "api_project" / "report"
HISTORY_DIR = ROOT / "api_project" / "history"
RUNNER = ROOT / "run_testcases.py"
SCHEDULER_RUNNER = ROOT / "run_scheduler.py"
MAX_LOG_CHARS = 120_000
ALLURE_PRESETS_FILE = CONFIG_DIR / "allure_presets.json"
SCHEDULER_JOBS_FILE = CONFIG_DIR / "scheduler_jobs.json"
ENVIRONMENT_PROFILES_FILE = CONFIG_DIR / "environment_profiles.json"
AUTH_PROFILES_FILE = CONFIG_DIR / "auth_profiles.json"
ASSERTION_RULES_FILE = CONFIG_DIR / "assertion_rules.json"
PERFORMANCE_THRESHOLDS_FILE = CONFIG_DIR / "performance_thresholds.json"
RETRY_CONFIG_FILE = CONFIG_DIR / "request_retry.json"
CASE_CONTROLS_FILE = CONFIG_DIR / "case_controls.json"
MANUAL_FILE = ROOT / "api_project" / "接口自动化测试使用手册.pdf"

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()
_curl_drafts: dict[str, dict] = {}
_curl_drafts_lock = threading.Lock()
_scheduler_process: subprocess.Popen | None = None
_scheduler_process_lock = threading.RLock()


@app.after_request
def disable_console_asset_cache(response):
    """Always serve the local console's HTML/JS/CSS fresh after a restart."""
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


def _read_json(path: Path, fallback):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _case_controls() -> dict:
    data = _read_json(CASE_CONTROLS_FILE, {"disabled": []})
    disabled = data.get("disabled", []) if isinstance(data, dict) else []
    return {"disabled": sorted({Path(str(name)).name for name in disabled if str(name).endswith(".json")})}


def _validate_case_name(filename: str) -> str:
    name = Path(str(filename)).name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.json", name):
        raise ValueError("用例文件名只能包含字母、数字、下划线、短横线和点，且必须以 .json 结尾")
    return name


def _validate_case_document(data: object) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("test_cases"), dict):
        raise ValueError("用例文件必须是包含 test_cases 对象的 JSON")
    if not data["test_cases"]:
        raise ValueError("test_cases 不能为空")
    valid_logic = {"query", "precondition", "expect_error"}
    for name, case in data["test_cases"].items():
        if not isinstance(name, str) or not isinstance(case, dict):
            raise ValueError("每个 test_cases 项必须为命名对象")
        if str(case.get("logic", "query")) not in valid_logic:
            raise ValueError(f"{name} 的 logic 必须是 {', '.join(sorted(valid_logic))} 之一")
        request_data = case.get("data")
        if not isinstance(request_data, dict) or not str(request_data.get("url", "")).strip():
            raise ValueError(f"{name} 缺少 data.url")
        method = str(request_data.get("method", "GET")).upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError(f"{name} 的 data.method 不支持: {method}")
        if "assertions" in case and (not isinstance(case["assertions"], list) or not all(isinstance(item, dict) for item in case["assertions"])):
            raise ValueError(f"{name} 的 assertions 必须是对象数组")
        if "extract" in case and (not isinstance(case["extract"], list) or not all(isinstance(item, dict) for item in case["extract"])):
            raise ValueError(f"{name} 的 extract 必须是对象数组")
        if "pre_steps" in case and (not isinstance(case["pre_steps"], list) or not all(isinstance(item, dict) for item in case["pre_steps"])):
            raise ValueError(f"{name} 的 pre_steps 必须是对象数组")
    return data


def _validate_json_config(kind: str, data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("配置根节点必须是 JSON 对象")
    if kind == "environments":
        profiles = data.get("environments")
        if not isinstance(profiles, dict) or not profiles:
            raise ValueError("environments 必须是非空对象")
        if not isinstance(data.get("aliases", {}), dict):
            raise ValueError("aliases 必须是对象")
        for name, profile in profiles.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(name)) or not isinstance(profile, dict):
                raise ValueError("环境名称或配置格式无效")
            if not str(profile.get("host_env", "")).strip():
                raise ValueError(f"环境 {name} 缺少 host_env")
    elif kind == "auth":
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            raise ValueError("profiles 必须是对象")
        for name, profile in profiles.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(name)) or not isinstance(profile, dict):
                raise ValueError("角色名称或配置格式无效")
            if profile.get("token_env") and not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(profile["token_env"])):
                raise ValueError(f"角色 {name} 的 token_env 必须是环境变量名")
    elif kind == "assertions":
        if not isinstance(data.get("rules"), dict):
            raise ValueError("rules 必须是对象")
        if not all(isinstance(name, str) and isinstance(items, list) and all(isinstance(item, dict) for item in items) for name, items in data["rules"].items()):
            raise ValueError("每个断言规则必须是对象数组")
    elif kind == "performance":
        if not isinstance(data.get("enabled", False), bool) or not isinstance(data.get("rules", []), list):
            raise ValueError("性能配置的 enabled/rules 格式无效")
        try:
            if float(data.get("default_threshold_sec", 0)) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("默认性能阈值必须大于 0") from None
        for rule in data["rules"]:
            if not isinstance(rule, dict) or float(rule.get("threshold_sec", 0)) <= 0:
                raise ValueError("每条性能规则必须有大于 0 的 threshold_sec")
    elif kind == "retry":
        try:
            if int(data.get("max_attempts", 0)) < 1 or float(data.get("backoff_seconds", -1)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("重试次数或退避时间无效") from None
        if not isinstance(data.get("retry_status_codes", []), list) or not isinstance(data.get("safe_methods", []), list):
            raise ValueError("重试状态码和安全方法必须是数组")
    return data


def _allure_store() -> dict:
    store = _read_json(ALLURE_PRESETS_FILE, {})
    return store if isinstance(store, dict) else {}


def _allure_assignments() -> dict[str, str]:
    assignments = _allure_store().get("assignments", {})
    return assignments if isinstance(assignments, dict) else {}


def _allure_preset_options() -> list[dict]:
    from api_project.common.allure_decorator import ALLURE_CONFIGS
    return [
        {
            "key": key,
            "title": str(config.get("title", key)),
            "sub_suite": str(config.get("sub_suite", "未分组")),
            "severity": getattr(config.get("severity"), "value", str(config.get("severity", "normal"))),
        }
        for key, config in sorted(ALLURE_CONFIGS.items())
    ]


def _case_preset(filename: str) -> str:
    assigned = _allure_assignments().get(filename)
    if assigned:
        return assigned
    return _allure_status(filename)["preset"]


def _scheduler_config() -> dict:
    config = _read_json(SCHEDULER_JOBS_FILE, {"timezone": "Asia/Shanghai", "jobs": []})
    if not isinstance(config, dict):
        config = {"timezone": "Asia/Shanghai", "jobs": []}
    config.setdefault("timezone", "Asia/Shanghai")
    config.setdefault("jobs", [])
    for index, job in enumerate(config["jobs"]):
        if isinstance(job, dict):
            job.setdefault("id", f"legacy-{index}")
    return config


def _scheduler_runtime_status() -> dict:
    with _scheduler_process_lock:
        process = _scheduler_process
        running = process is not None and process.poll() is None
        return {"running": running, "pid": process.pid if running else None}


def _stop_scheduler_process() -> bool:
    """Stop only the scheduler process created by this web console."""
    global _scheduler_process
    with _scheduler_process_lock:
        process = _scheduler_process
        if process is None or process.poll() is not None:
            _scheduler_process = None
            return False
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        _scheduler_process = None
        return True


def _validated_schedule_job(payload: dict, existing_id: str | None = None) -> dict:
    name = str(payload.get("name", "")).strip()
    cron = str(payload.get("cron", "")).strip()
    preset = str(payload.get("preset", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("任务名称不能为空，且最多 80 个字符")
    if not cron:
        raise ValueError("请填写 5 段 cron 表达式")
    CronTrigger.from_crontab(cron, timezone=_scheduler_config()["timezone"])
    if preset and preset not in {item["key"] for item in _allure_preset_options()}:
        raise ValueError("指定的 Allure 预设不存在")
    try:
        timeout_sec = int(payload.get("timeout_sec", 3600))
    except (TypeError, ValueError) as exc:
        raise ValueError("超时时间必须是整数") from exc
    if timeout_sec < 60 or timeout_sec > 86400:
        raise ValueError("超时时间须在 60 到 86400 秒之间")
    env = {"RUN_MODULE": preset} if preset else {}
    return {
        "id": existing_id or uuid.uuid4().hex[:12], "name": name,
        "enabled": bool(payload.get("enabled", True)), "cron": cron,
        "command": "run_testcases.py", "timeout_sec": timeout_sec,
        "env": env, "description": f"控制台创建；范围：{preset or '全部用例'}",
    }


def _case_summary() -> list[dict]:
    cases = []
    disabled = set(_case_controls()["disabled"])
    for path in sorted(CASE_DIR.glob("*.json")):
        data = _read_json(path, {})
        test_cases = data.get("test_cases", {}) if isinstance(data, dict) else {}
        cases.append({
            "file": path.name,
            "count": len(test_cases) if isinstance(test_cases, dict) else 0,
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "preset": _case_preset(path.name),
            "enabled": path.name not in disabled,
        })
    return cases


def _case_page(query: str = "", page: int = 1, page_size: int = 20) -> dict:
    """Return a bounded, searchable case-library page.

    Keeping the library paged avoids serialising every JSON file into the
    dashboard response when a project contains thousands of generated cases.
    """
    normalized = query.strip().lower()
    cases = _case_summary()
    if normalized:
        cases = [case for case in cases if normalized in case["file"].lower()]
    total = len(cases)
    page_size = min(max(page_size, 10), 100)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(page, 1), pages)
    start = (page - 1) * page_size
    return {"items": cases[start:start + page_size], "total": total, "page": page, "pages": pages, "page_size": page_size}


def _report_summary() -> dict:
    report = _read_json(REPORT_DIR / "final_report.json", {})
    filters = report.get("filters", {}) if isinstance(report, dict) else {}
    return {
        "total": filters.get("total", 0),
        "passed": filters.get("passed", 0),
        "failed": filters.get("failed", 0),
        "updated_at": datetime.fromtimestamp((REPORT_DIR / "final_report.json").stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        if (REPORT_DIR / "final_report.json").exists() else "暂无报告",
    }


def _safe_env_status() -> dict:
    """Expose only booleans/status—not credentials or endpoint values."""
    env_path = ROOT / "api_project" / ".env"
    values = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    def configured(name: str) -> bool:
        value = values.get(name, "").strip()
        return bool(value and not value.lower().startswith(("your_", "your-", "example_")))

    email_ready = configured("SMTP_USERNAME") and configured("SMTP_PASSWORD") and configured("SMTP_RECEIVERS")
    bots = [
        {"name": "飞书", "enabled": configured("FEISHU_TOKEN"), "detail": "机器人 Token"},
        {"name": "钉钉", "enabled": configured("DINGDING_TOKEN"), "detail": "机器人 Token"},
        {"name": "企业微信", "enabled": configured("WEIXIN_TOKEN"), "detail": "机器人 Token"},
        {"name": "电话告警", "enabled": configured("PHONE_CALL_WEBHOOK"), "detail": "告警 Webhook"},
    ]
    return {
        "token_configured": bool(values.get("API_TOKEN") or values.get("API_ITOKEN")),
        "scheduler_enabled": values.get("SCHEDULER_ENABLED", "false").lower() in {"true", "1", "yes", "on"},
        "api_verify_tls": values.get("API_VERIFY_TLS", "true").lower() in {"true", "1", "yes", "on"},
        "email_mode": values.get("SEND_EMAIL", "never"),
        "notification_mode": values.get("PYTEST_NOTIFY_MODE", "only_failed"),
        "email_configured": email_ready,
        "bots": bots,
    }


def _scheduler_status() -> dict:
    config = _scheduler_config()
    jobs = config["jobs"]
    enabled = [job for job in jobs if isinstance(job, dict) and bool(job.get("enabled"))]
    return {"total": len(jobs), "enabled": len(enabled), "jobs": [{"name": job.get("name", "未命名任务"), "cron": job.get("cron", ""), "enabled": bool(job.get("enabled"))} for job in jobs if isinstance(job, dict)]}


def _available_modules() -> list[str]:
    """Return only selectors understood by the existing RUN_MODULE hook.

    The legacy hook accepts an Allure preset (or a business sub-suite), not an
    arbitrary JSON stem.  Keeping that contract here prevents a user selecting
    one file and unexpectedly running the whole suite.
    """
    try:
        from api_project.common.allure_decorator import ALLURE_CONFIGS
    except Exception:
        return []

    # RUN_MODULE natively accepts either a preset or its configured sub_suite.
    # Presenting the latter is the useful "module" scope and includes every
    # mapped endpoint instead of exposing a misleading one-file-per-option UI.
    counts: dict[str, int] = {}
    for config in ALLURE_CONFIGS.values():
        name = str(config.get("sub_suite", "")).strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    return [{"value": name, "label": f"{name}（{count} 个接口）"} for name, count in sorted(counts.items())]


def _read_env_values() -> tuple[Path, dict[str, str], list[str]]:
    path = ROOT / "api_project" / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value
    return path, values, lines


def _update_env_values(updates: dict[str, str]) -> None:
    """Update only approved .env keys, retaining comments and other settings."""
    path, _, lines = _read_env_values()
    pending = dict(updates)
    result = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in pending:
                result.append(f"{key}={pending.pop(key)}")
                continue
        result.append(line)
    result.extend(f"{key}={value}" for key, value in pending.items())
    path.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")


def _settings_status() -> dict:
    _, values, _ = _read_env_values()
    def configured(name: str) -> bool:
        value = values.get(name, "").strip()
        return bool(value and not value.lower().startswith(("your_", "your-", "example_")))
    channels = {
        "feishu": {"configured": configured("FEISHU_TOKEN"), "enabled": values.get("FEISHU_ENABLED", "true").lower() in {"true", "1", "yes", "on"}},
        "dingding": {"configured": configured("DINGDING_TOKEN"), "enabled": values.get("DINGDING_ENABLED", "true").lower() in {"true", "1", "yes", "on"}},
        "weixin": {"configured": configured("WEIXIN_TOKEN"), "enabled": values.get("WEIXIN_ENABLED", "true").lower() in {"true", "1", "yes", "on"}},
        "phone_call": {"configured": configured("PHONE_CALL_WEBHOOK"), "enabled": values.get("PHONE_CALL_ENABLED", "true").lower() in {"true", "1", "yes", "on"}},
    }
    try:
        from api_project.config.host_config import HOST
        default_host = HOST.CURRENT_HOST
    except Exception:
        default_host = ""
    defaults = {
        "API_HOST": default_host, "API_TIMEOUT": "10", "TEST_EXECUTOR": "", "ALLURE_URL": "",
        "SMTP_HOST": "smtp.qq.com", "SMTP_PORT": "465", "SMTP_SUBJECT": "自动化测试报告",
        "SMTP_USERNAME": "", "SMTP_RECEIVERS": "", "API_ENV": "test", "TEST_API_HOST": "",
        "PRO_API_HOST": "", "ALLURE_REPORT_KEEP": "3", "NOTIFICATION_TIMEOUT": "10",
    }
    safe_keys = tuple(defaults)
    resolved_values = {key: values.get(key, defaults[key]) for key in safe_keys}
    return {
        "api_token": configured("API_TOKEN") or configured("API_ITOKEN"),
        "api_cookie": configured("API_COOKIE"),
        "api_host": configured("API_HOST"),
        "email_mode": values.get("SEND_EMAIL", "never"),
        "notification_mode": values.get("PYTEST_NOTIFY_MODE", "only_failed"),
        "scheduler_enabled": values.get("SCHEDULER_ENABLED", "false").lower() in {"true", "1", "yes", "on"},
        "channels": channels,
        "smtp_configured": configured("SMTP_HOST") and configured("SMTP_USERNAME") and configured("SMTP_PASSWORD"),
        "api_host_configured": configured("API_HOST"),
        "allure_url_configured": configured("ALLURE_URL"),
        "proxy_enabled": values.get("PROXY_ENABLED", "false").lower() in {"true", "1", "yes", "on"},
        "upload_test_report": values.get("UPLOAD_TEST_REPORT", "false").lower() in {"true", "1", "yes", "on"},
        "values": resolved_values,
        "value_sources": {key: "configured" if configured(key) else "default" for key in safe_keys},
        "secrets": {
        "api_token": configured("API_TOKEN"), "api_itoken": configured("API_ITOKEN"), "api_cookie": configured("API_COOKIE"),
            "smtp_password": configured("SMTP_PASSWORD"), "feishu_token": configured("FEISHU_TOKEN"),
            "dingding_token": configured("DINGDING_TOKEN"), "dingding_secret": configured("DINGDING_SECRET"),
            "weixin_token": configured("WEIXIN_TOKEN"), "phone_call_webhook": configured("PHONE_CALL_WEBHOOK"),
        },
    }


def _append_log(run_id: str, line: str) -> None:
    with _runs_lock:
        run = _runs.get(run_id)
        if run is None:
            return
        run["log"] = (run["log"] + line)[-MAX_LOG_CHARS:]


def _allure_status(filename: str) -> dict:
    stem = filename.removesuffix(".json").lower().replace("-", "_").replace(".", "_")
    try:
        from api_project.common.allure_decorator import ALLURE_CONFIGS
        for preset in ALLURE_CONFIGS:
            key = preset.lower()
            if key.startswith("jqb_") and key.endswith("_api") and stem.replace("_", "") == key[4:-4].replace("_", ""):
                return {"mode": "mapped", "preset": preset}
    except Exception:
        pass
    return {"mode": "fallback", "preset": f"generated_{stem}_api"}


def _draft_url_prefix(cases: list[dict]) -> str:
    """Extract the host inferred by the cURL parser for displaying in the UI."""
    try:
        item = cases[0]["case"]["test_cases"]
        request_data = next(iter(item.values()))["data"]
        parsed = urlparse(str(request_data.get("url", "")))
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    except (IndexError, KeyError, StopIteration, TypeError):
        return ""


def _build_curl_draft(curl_text: str, url_prefix: str = "") -> list[dict]:
    """Preview exactly the same conversion contract used by ``convert_json.py``."""
    if not isinstance(curl_text, str) or "curl" not in curl_text.lower():
        raise ValueError("请粘贴至少一条完整的 cURL 命令")
    from convert_json import Controller, RequestProcessor
    from saf.utils.Curl2Object import Curl
    found_url = re.search(r"https?://[^\s'\"]+", curl_text)
    inferred_prefix = ""
    if found_url:
        parsed_url = urlparse(found_url.group(0))
        inferred_prefix = f"{parsed_url.scheme}://{parsed_url.netloc}"
    effective_prefix = url_prefix.rstrip("/") or inferred_prefix
    if not effective_prefix:
        raise ValueError("cURL 未包含完整地址，请填写接口地址前缀")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as handle:
            handle.write(curl_text)
            temp_path = handle.name
        parser = Curl()
        previous_host = os.environ.get("HOST")
        previous_api_names = os.environ.get("ALL_API_NAME")
        os.environ["HOST"] = effective_prefix
        os.environ["ALL_API_NAME"] = "[]"
        try:
            parser.load(curl_file_path=temp_path)
        finally:
            if previous_host is None:
                os.environ.pop("HOST", None)
            else:
                os.environ["HOST"] = previous_host
            if previous_api_names is None:
                os.environ.pop("ALL_API_NAME", None)
            else:
                os.environ["ALL_API_NAME"] = previous_api_names
        converter = Controller()
        drafts = []
        for index, original in enumerate(parser.group, start=1):
            request_data = converter.normalize_request_data(dict(original))
            if not str(request_data.get("url", "")).startswith(("http://", "https://")):
                request_data["url"] = f"{effective_prefix}/{str(request_data.get('url', '')).lstrip('/')}"
            filename_stem = converter._generate_file_name(request_data)
            stem = filename_stem
            request_data.pop("api_name", None)
            request_type = RequestProcessor.get_request_type(request_data)
            case = {"test_cases": {"test_case_1": {"description": f"{stem}接口测试", "request_type": request_type, "logic": "query", "data": request_data}}}
            drafts.append({"id": str(index), "filename": f"{stem}.json", "case": case, "allure": _allure_status(f"{stem}.json")})
        if not drafts:
            raise ValueError("未能从 cURL 中解析出请求")
        return drafts
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def _validate_new_cases() -> tuple[bool, str]:
    collect = subprocess.run([sys.executable, "-m", "pytest", "api_project/testcases", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return collect.returncode == 0, (collect.stdout + collect.stderr)[-12_000:]


def _merge_curl_draft_cases(items: list[dict]) -> tuple[dict[Path, dict], list[str], list[str], int]:
    """Apply the legacy converter's one-file-per-endpoint merge contract.

    Requests with the same generated filename are stored as ``test_case_N`` in
    the same JSON file.  A request whose normalized ``data`` already exists is
    skipped, matching ``Controller._generate_test_data_json``.
    """
    pending: dict[Path, dict] = {}
    saved: list[str] = []
    skipped: list[str] = []
    added_cases = 0
    for item in items:
        target = CASE_DIR / item["filename"]
        if target not in pending:
            if target.exists():
                data = _read_json(target, {})
                if not isinstance(data, dict) or not isinstance(data.get("test_cases"), dict):
                    raise ValueError(f"用例文件格式无效：{target.name}")
            else:
                data = {"test_cases": {}}
            pending[target] = data

        test_cases = pending[target]["test_cases"]
        incoming = item["case"]["test_cases"]["test_case_1"]
        request_data = incoming["data"]
        if any(existing.get("data") == request_data for existing in test_cases.values() if isinstance(existing, dict)):
            if target.name not in skipped:
                skipped.append(target.name)
            continue

        case_number = len(test_cases) + 1
        case_name = f"test_case_{case_number}"
        test_cases[case_name] = {
            **incoming,
            "description": f"{target.stem}接口测试用例{case_number}",
        }
        if target.name not in saved:
            saved.append(target.name)
        added_cases += 1
    return pending, saved, skipped, added_cases


def _execute_run(run_id: str, module: str | None, files: list[str] | None = None) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if module:
        env["RUN_MODULE"] = module
    if files:
        env["RUN_CASE_FILES"] = ",".join(files)
    # Disable pytest's persistent cache for runs launched from the dashboard.
    # It contains no test result data and can be locked by an IDE or another
    # Python process on Windows; a locked cache must never prevent a run.
    process = subprocess.Popen(
        [sys.executable, str(RUNNER), "-p", "no:cacheprovider"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
    )
    with _runs_lock:
        _runs[run_id]["pid"] = process.pid
    assert process.stdout is not None
    for line in process.stdout:
        _append_log(run_id, line)
    exit_code = process.wait()
    with _runs_lock:
        run = _runs[run_id]
        run.update({
            "status": "passed" if exit_code == 0 else "failed",
            "exit_code": exit_code,
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/console-info")
def console_info():
    """Health/version marker used by the restart launcher to reject stale servers."""
    return jsonify({"version": "web-console-20261022.7", "config_api": True})


@app.get("/favicon.ico")
def favicon():
    response = send_from_directory(ROOT / "api_project" / "resources", "favicon.ico", mimetype="image/vnd.microsoft.icon")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.get("/manual")
def manual():
    """Serve the project operation manual from the local-only console."""
    if not MANUAL_FILE.is_file():
        abort(404)
    response = send_file(MANUAL_FILE, mimetype="application/pdf", as_attachment=False, conditional=True)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.get("/api/dashboard")
def dashboard():
    cases = _case_summary()
    return jsonify({
        "cases": cases,
        "case_count": sum(case["count"] for case in cases),
        "report": _report_summary(),
        "environment": _safe_env_status(),
        "scheduler": _scheduler_status(),
        "modules": _available_modules(),
    })


@app.get("/api/cases")
def cases():
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))
    except ValueError:
        return jsonify({"error": "page 和 page_size 必须是整数"}), 400
    return jsonify(_case_page(request.args.get("q", ""), page, page_size))


@app.get("/api/cases/<filename>")
def get_case(filename: str):
    try:
        name = _validate_case_name(filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    path = CASE_DIR / name
    if not path.is_file():
        abort(404)
    data = _read_json(path, None)
    if not isinstance(data, dict):
        return jsonify({"error": "用例文件不是有效 JSON"}), 422
    return jsonify({"file": name, "data": data, "enabled": name not in set(_case_controls()["disabled"])})


@app.put("/api/cases/<filename>")
def update_case(filename: str):
    try:
        name = _validate_case_name(filename)
        payload = request.get_json(silent=True) or {}
        document = _validate_case_document(payload.get("data"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    path = CASE_DIR / name
    if not path.is_file():
        abort(404)
    original = path.read_text(encoding="utf-8")
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    collected, output = _validate_new_cases()
    if not collected:
        path.write_text(original, encoding="utf-8")
        return jsonify({"error": "收集校验失败，已恢复原用例", "collect_log": output}), 422
    return jsonify({"file": name, "saved": True, "collect_ok": True})


@app.post("/api/cases/<filename>/copy")
def copy_case(filename: str):
    try:
        source_name = _validate_case_name(filename)
        new_name = _validate_case_name((request.get_json(silent=True) or {}).get("filename", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    source, target = CASE_DIR / source_name, CASE_DIR / new_name
    if not source.is_file():
        abort(404)
    if target.exists():
        return jsonify({"error": "目标文件已存在"}), 409
    data = _read_json(source, None)
    try:
        _validate_case_document(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    collected, output = _validate_new_cases()
    if not collected:
        target.unlink(missing_ok=True)
        return jsonify({"error": "收集校验失败，未创建副本", "collect_log": output}), 422
    return jsonify({"file": new_name, "copied_from": source_name}), 201


@app.post("/api/cases/<filename>/toggle")
def toggle_case(filename: str):
    try:
        name = _validate_case_name(filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not (CASE_DIR / name).is_file():
        abort(404)
    controls = _case_controls()
    disabled = set(controls["disabled"])
    enabled = name in disabled
    if enabled:
        disabled.remove(name)
    else:
        disabled.add(name)
    _write_json(CASE_CONTROLS_FILE, {"disabled": sorted(disabled)})
    return jsonify({"file": name, "enabled": enabled})


@app.delete("/api/cases/<filename>")
def delete_case(filename: str):
    try:
        name = _validate_case_name(filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    path = CASE_DIR / name
    if not path.is_file():
        abort(404)
    # A recoverable rename keeps accidental UI deletions out of the test scan.
    trash = CASE_DIR / ".trash"
    trash.mkdir(exist_ok=True)
    path.replace(trash / f"{datetime.now():%Y%m%d%H%M%S}_{name}")
    controls = _case_controls()
    _write_json(CASE_CONTROLS_FILE, {"disabled": [item for item in controls["disabled"] if item != name]})
    return jsonify({"deleted": name, "recoverable": True})


@app.post("/api/runs")
def start_run():
    payload = request.get_json(silent=True) or {}
    selected = str(payload.get("module", "")).strip()
    files = payload.get("files", [])
    if not isinstance(files, list) or not all(isinstance(name, str) for name in files):
        return jsonify({"error": "files 必须是文件名数组"}), 400
    files = sorted({Path(name).name for name in files if name.endswith(".json")})
    existing_files = {case["file"] for case in _case_summary()}
    if any(name not in existing_files for name in files):
        return jsonify({"error": "包含不存在的用例文件"}), 400
    allowed = {item["value"] for item in _available_modules()}
    if selected and selected not in allowed:
        return jsonify({"error": "未知的用例模块"}), 400

    run_id = uuid.uuid4().hex[:8]
    run = {
        "id": run_id, "module": selected or (f"{len(files)} 个选中用例" if files else "全部用例"), "status": "running",
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None, "exit_code": None, "pid": None, "log": "正在准备测试环境…\n",
    }
    with _runs_lock:
        _runs[run_id] = run
    threading.Thread(target=_execute_run, args=(run_id, selected or None, files or None), daemon=True).start()
    return jsonify({key: value for key, value in run.items() if key != "log"}), 202


@app.post("/api/curl/preview")
def preview_curl():
    payload = request.get_json(silent=True) or {}
    try:
        cases = _build_curl_draft(str(payload.get("curl", "")), str(payload.get("url_prefix", "")).strip())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    draft_id = uuid.uuid4().hex
    with _curl_drafts_lock:
        _curl_drafts[draft_id] = {"cases": cases, "created_at": time.time()}
    return jsonify({"draft_id": draft_id, "cases": cases, "url_prefix": _draft_url_prefix(cases)})


@app.post("/api/curl/upload-preview")
def preview_curl_upload():
    """Preview one or more exported cURL text files without persisting them."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "请选择至少一个 cURL 文本文件"}), 400
    contents = []
    for uploaded in files:
        suffix = Path(uploaded.filename or "").suffix.lower()
        if suffix not in {".txt", ".curl", ".sh"}:
            return jsonify({"error": f"不支持的文件：{uploaded.filename}；仅支持 .txt、.curl、.sh"}), 400
        raw = uploaded.read()
        if len(raw) > 5 * 1024 * 1024:
            return jsonify({"error": f"文件过大：{uploaded.filename}（最大 5MB）"}), 400
        contents.append(raw.decode("utf-8-sig", errors="replace"))
    try:
        cases = _build_curl_draft("\n".join(contents), request.form.get("url_prefix", "").strip())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    draft_id = uuid.uuid4().hex
    with _curl_drafts_lock:
        _curl_drafts[draft_id] = {"cases": cases, "created_at": time.time()}
    return jsonify({"draft_id": draft_id, "cases": cases, "source_files": len(files), "url_prefix": _draft_url_prefix(cases)})


@app.post("/api/curl/save")
def save_curl():
    payload = request.get_json(silent=True) or {}
    draft_id = str(payload.get("draft_id", ""))
    with _curl_drafts_lock:
        draft = _curl_drafts.pop(draft_id, None)
    if not draft:
        return jsonify({"error": "预览已失效，请重新解析 cURL"}), 404
    CASE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        merged_cases, saved, skipped, added_cases = _merge_curl_draft_cases(draft["cases"])
        for target, case_data in merged_cases.items():
            if target.name in saved:
                target.write_text(json.dumps(case_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return jsonify({"error": f"保存用例文件失败：{exc}"}), 500
    threshold = subprocess.run([sys.executable, "api_project/all_skills/curl-to-testcase/scripts/sync_performance_thresholds.py"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    collected, output = _validate_new_cases()
    # A converted file has already been saved even if the optional collection
    # validation detects another problem.  Do not turn a successful write into
    # a failed save response; return the validation warning to the UI instead.
    return jsonify({"saved": saved, "skipped": skipped, "added_cases": added_cases, "performance_synced": threshold.returncode == 0, "performance_log": (threshold.stdout + threshold.stderr)[-4000:], "collect_ok": collected, "collect_log": output}), 201 if added_cases else 200


@app.get("/api/allure-presets")
def allure_presets():
    return jsonify({"items": _allure_preset_options(), "assignments": _allure_assignments()})


_CONFIG_RESOURCES = {
    "environments": ENVIRONMENT_PROFILES_FILE,
    "auth": AUTH_PROFILES_FILE,
    "assertions": ASSERTION_RULES_FILE,
    "performance": PERFORMANCE_THRESHOLDS_FILE,
    "retry": RETRY_CONFIG_FILE,
}


@app.get("/api/config/<kind>")
def get_config_resource(kind: str):
    path = _CONFIG_RESOURCES.get(kind)
    if path is None:
        abort(404)
    fallback = {"environments": {"environments": {}, "aliases": {}}, "auth": {"profiles": {}}, "assertions": {"rules": {}}, "performance": {"enabled": False, "default_threshold_sec": 5, "rules": []}, "retry": {}}[kind]
    return jsonify({"kind": kind, "data": _read_json(path, fallback)})


@app.put("/api/config/<kind>")
def update_config_resource(kind: str):
    path = _CONFIG_RESOURCES.get(kind)
    if path is None:
        abort(404)
    try:
        payload = request.get_json(silent=True) or {}
        data = _validate_json_config(kind, payload.get("data"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    _write_json(path, data)
    return jsonify({"kind": kind, "saved": True, "data": data})


@app.get("/api/performance/alerts")
def performance_alerts():
    source = HISTORY_DIR / "performance_history.jsonl"
    alerts = []
    if source.is_file():
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("slow"):
                alerts.append(item)
    alerts.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return jsonify({"items": alerts[:50]})


@app.post("/api/allure-presets")
def save_allure_preset():
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", "")).strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", key):
        return jsonify({"error": "预设标识须为 3-64 位小写字母、数字或下划线"}), 400
    fields = {name: str(payload.get(name, "")).strip() for name in ("suite", "epic", "sub_suite", "title")}
    if not fields["title"] or not fields["sub_suite"]:
        return jsonify({"error": "标题和所属模块不能为空"}), 400
    severity = str(payload.get("severity", "normal")).lower()
    if severity not in {"blocker", "critical", "normal", "minor", "trivial"}:
        return jsonify({"error": "严重级别无效"}), 400
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        return jsonify({"error": "标签必须是非空文本数组"}), 400
    store = _allure_store()
    presets = store.setdefault("presets", {})
    presets[key] = {**fields, "severity": severity, "tags": [tag.strip() for tag in tags]}
    store.setdefault("deleted", [])
    if key in store["deleted"]:
        store["deleted"].remove(key)
    _write_json(ALLURE_PRESETS_FILE, store)
    from api_project.common.allure_decorator import ALLURE_CONFIGS
    import allure
    ALLURE_CONFIGS[key] = {**fields, "severity": getattr(allure.severity_level, severity.upper()), "tags": [tag.strip() for tag in tags]}
    return jsonify({"saved": key, "items": _allure_preset_options()}), 201


@app.delete("/api/allure-presets/<preset>")
def delete_allure_preset(preset: str):
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", preset):
        return jsonify({"error": "预设标识无效"}), 400
    store = _allure_store()
    store.setdefault("presets", {}).pop(preset, None)
    deleted = set(store.setdefault("deleted", []))
    deleted.add(preset)
    store["deleted"] = sorted(deleted)
    assignments = store.setdefault("assignments", {})
    store["assignments"] = {filename: key for filename, key in assignments.items() if key != preset}
    _write_json(ALLURE_PRESETS_FILE, store)
    from api_project.common.allure_decorator import ALLURE_CONFIGS
    ALLURE_CONFIGS.pop(preset, None)
    return jsonify({"deleted": preset})


@app.post("/api/cases/allure")
def assign_case_allure_preset():
    payload = request.get_json(silent=True) or {}
    files = payload.get("files", [])
    preset = str(payload.get("preset", "")).strip()
    if not isinstance(files, list) or not files:
        return jsonify({"error": "请至少选择一个用例"}), 400
    files = sorted({Path(str(name)).name for name in files})
    if any(not name.endswith(".json") or not (CASE_DIR / name).is_file() for name in files):
        return jsonify({"error": "包含不存在的用例文件"}), 400
    if preset and preset not in {item["key"] for item in _allure_preset_options()}:
        return jsonify({"error": "指定的 Allure 预设不存在"}), 400
    store = _allure_store()
    assignments = store.setdefault("assignments", {})
    for filename in files:
        if preset:
            assignments[filename] = preset
        else:
            assignments.pop(filename, None)
    _write_json(ALLURE_PRESETS_FILE, store)
    return jsonify({"files": files, "preset": preset or None})


@app.get("/api/schedules")
def schedules():
    config = _scheduler_config()
    return jsonify({"timezone": config["timezone"], "items": config["jobs"], "runtime": _scheduler_runtime_status()})


@app.post("/api/schedules")
def create_schedule():
    payload = request.get_json(silent=True) or {}
    try:
        job = _validated_schedule_job(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    config = _scheduler_config()
    config["jobs"].append(job)
    _write_json(SCHEDULER_JOBS_FILE, config)
    return jsonify(job), 201


@app.put("/api/schedules/<job_id>")
def update_schedule(job_id: str):
    payload = request.get_json(silent=True) or {}
    config = _scheduler_config()
    for index, job in enumerate(config["jobs"]):
        if str(job.get("id", "")) == job_id:
            try:
                config["jobs"][index] = _validated_schedule_job(payload, job_id)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            _write_json(SCHEDULER_JOBS_FILE, config)
            return jsonify(config["jobs"][index])
    abort(404)


@app.post("/api/schedules/<job_id>/toggle")
def toggle_schedule(job_id: str):
    config = _scheduler_config()
    for job in config["jobs"]:
        if str(job.get("id", "")) == job_id:
            job["enabled"] = not bool(job.get("enabled"))
            _write_json(SCHEDULER_JOBS_FILE, config)
            return jsonify({"id": job_id, "enabled": job["enabled"]})
    abort(404)


@app.delete("/api/schedules/<job_id>")
def delete_schedule(job_id: str):
    config = _scheduler_config()
    jobs = [job for job in config["jobs"] if str(job.get("id", "")) != job_id]
    if len(jobs) == len(config["jobs"]):
        abort(404)
    config["jobs"] = jobs
    _write_json(SCHEDULER_JOBS_FILE, config)
    return jsonify({"deleted": job_id})


@app.post("/api/scheduler/run")
def run_scheduler_process():
    """Start the project's normal scheduler entry point once in the background."""
    global _scheduler_process
    if not _safe_env_status()["scheduler_enabled"]:
        return jsonify({"error": "请先在配置中心启用定时调度总开关并保存", **_scheduler_runtime_status()}), 400
    if not _scheduler_status()["enabled"]:
        return jsonify({"error": "请先开启至少一个定时任务", **_scheduler_runtime_status()}), 400
    with _scheduler_process_lock:
        if _scheduler_process is not None and _scheduler_process.poll() is None:
            return jsonify({"error": "定时调度器正在运行", **_scheduler_runtime_status()}), 409
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        kwargs = {"cwd": ROOT, "env": env, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _scheduler_process = subprocess.Popen([sys.executable, str(SCHEDULER_RUNNER)], **kwargs)
        return jsonify({"started": True, **_scheduler_runtime_status()}), 202


@app.post("/api/scheduler/stop")
def stop_scheduler_process():
    """Stop the scheduler process started from this console, if it is running."""
    stopped = _stop_scheduler_process()
    if not stopped:
        return jsonify({"error": "调度器当前未运行", **_scheduler_runtime_status()}), 409
    return jsonify({"stopped": True, **_scheduler_runtime_status()})


@app.get("/api/settings")
def settings():
    # Never return credential values to the browser: only configuration state.
    return jsonify(_settings_status())


@app.post("/api/settings")
def save_settings():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "配置格式无效"}), 400
    aliases = {
        "api_token": "API_TOKEN", "api_itoken": "API_ITOKEN", "api_cookie": "API_COOKIE",
        "api_host": "API_HOST", "api_timeout": "API_TIMEOUT", "test_executor": "TEST_EXECUTOR",
        "allure_url": "ALLURE_URL", "smtp_host": "SMTP_HOST", "smtp_port": "SMTP_PORT",
        "smtp_username": "SMTP_USERNAME", "smtp_password": "SMTP_PASSWORD", "smtp_subject": "SMTP_SUBJECT", "smtp_receivers": "SMTP_RECEIVERS",
        "feishu_token": "FEISHU_TOKEN", "dingding_token": "DINGDING_TOKEN", "dingding_secret": "DINGDING_SECRET",
        "weixin_token": "WEIXIN_TOKEN", "phone_call_webhook": "PHONE_CALL_WEBHOOK",
        "api_env": "API_ENV", "test_api_host": "TEST_API_HOST", "pro_api_host": "PRO_API_HOST",
        "allure_report_keep": "ALLURE_REPORT_KEEP", "notification_timeout": "NOTIFICATION_TIMEOUT",
    }
    updates = {}
    for input_name, env_name in aliases.items():
        value = payload.get(input_name)
        if value is not None:
            if not isinstance(value, str) or "\n" in value or "\r" in value:
                return jsonify({"error": f"{input_name} 格式无效"}), 400
            updates[env_name] = value.strip()
    for input_name, env_name, allowed in (
        ("email_mode", "SEND_EMAIL", {"always", "only_failed", "never"}),
        ("notification_mode", "PYTEST_NOTIFY_MODE", {"always", "only_failed", "never"}),
    ):
        if input_name in payload:
            value = str(payload[input_name])
            if value not in allowed:
                return jsonify({"error": f"{input_name} 取值无效"}), 400
            updates[env_name] = value
    if "scheduler_enabled" in payload:
        updates["SCHEDULER_ENABLED"] = "true" if bool(payload["scheduler_enabled"]) else "false"
    if "api_verify_tls" in payload:
        updates["API_VERIFY_TLS"] = "true" if bool(payload["api_verify_tls"]) else "false"
    for key, env_name in (("proxy_enabled", "PROXY_ENABLED"), ("upload_test_report", "UPLOAD_TEST_REPORT")):
        if key in payload:
            updates[env_name] = "true" if bool(payload[key]) else "false"
    for key, env_name in (("feishu_enabled", "FEISHU_ENABLED"), ("dingding_enabled", "DINGDING_ENABLED"), ("weixin_enabled", "WEIXIN_ENABLED"), ("phone_call_enabled", "PHONE_CALL_ENABLED")):
        if key in payload:
            updates[env_name] = "true" if bool(payload[key]) else "false"
    if not updates:
        return jsonify({"error": "没有可保存的配置"}), 400
    _update_env_values(updates)
    return jsonify({"saved": sorted(updates), "settings": _settings_status()})


@app.get("/api/runs/<run_id>")
def run_status(run_id: str):
    with _runs_lock:
        run = _runs.get(run_id)
        if run is None:
            abort(404)
        return jsonify(run)


@app.get("/reports/<path:filename>")
def reports(filename: str):
    # send_from_directory prevents traversal; only deliberately exposed report roots are allowed.
    if filename.startswith("history/"):
        return send_from_directory(HISTORY_DIR, filename.removeprefix("history/"))
    return send_from_directory(REPORT_DIR, filename)


@app.get("/api/report-links")
def report_links():
    links = []
    for label, relative in (
        ("测试总报告", "report.html"),
        ("Allure 报告", "allure_html_report/index.html"),
        ("趋势报告", "history/trend_report.html"),
        ("汇总报告", "history/summary_report.html"),
        ("性能报告", "history/performance_report.html"),
    ):
        base = HISTORY_DIR if relative.startswith("history/") else REPORT_DIR
        target = base / relative.removeprefix("history/")
        if target.is_file():
            links.append({"label": label, "url": f"/reports/{relative}"})
    return jsonify(links)


if __name__ == "__main__":
    if os.getenv("WEB_APP_OPEN_BROWSER", "true").lower() in {"1", "true", "yes", "on"}:
        threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:5000/")).start()
    app.run(host="127.0.0.1", port=int(os.getenv("WEB_APP_PORT", "5000")), debug=False)
