"""Pytest session result collection, report decoration, and notification flow."""
import html
import json
import logging
import time
from datetime import datetime
from urllib.parse import urlparse

import pytest

from api_project.common.api_request import sanitize_headers
from api_project.common.notifications.builders import (
    ALLURE_URL,
    ALLURE_URLS,
    EMERGENCY_CONTACT,
    EMERGENCY_PHONE,
    NOTIFICATION_MODE,
    PASSED_DISPLAY_LIMIT,
    TEST_EXECUTOR,
    _status_emoji,
    _submit_bug,
)
from api_project.common.notifications.senders import _send_phone_call, _send_robot_notification
from api_project.common.performance_manager import append_performance_records, evaluate_cases
from api_project.common.reporting import (
    collect_worker_results,
    is_report_upload_enabled,
    is_xdist_worker,
    publish_worker_results,
)
from api_project.common.upload_service import upload_test_report


class SessionReporter:
    """Owns process-local pytest results and performs controller-only side effects."""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.results = []
        self.started_at = None
        self.finished = False
        self._pending_notification = None

    def start(self):
        self.results = []
        self.started_at = time.time()
        self.finished = False
        self._pending_notification = None

    def merge_worker_results(self, node):
        self.results.extend(collect_worker_results(node))

    @staticmethod
    def _safe_json(value):
        try:
            return json.dumps(value, indent=2, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    def capture_report(self, item, report):
        """Collect one final result per test item and attach request/response details."""
        req_info = getattr(item, "_request_info", None)
        res_info = getattr(item, "_response_info", None)
        if not req_info or not res_info:
            api_req = item.funcargs.get("api_request") if hasattr(item, "funcargs") else None
            if api_req:
                req_info = req_info or getattr(api_req, "last_request_info", None)
                res_info = res_info or getattr(api_req, "last_response_info", None)

        result = {
            "name": item.name, "nodeid": item.nodeid, "outcome": report.outcome,
            "duration": report.duration,
            "longrepr": str(report.longrepr) if report.longrepr else None,
            "status_code": res_info.get("status_code") if res_info else None,
            "response_text": (res_info.get("text", "") or "")[:500] if res_info else None,
            "request_url": req_info.get("url", "") if req_info else None,
            "request_method": req_info.get("method", "") if req_info else None,
            "response_elapsed": res_info.get("elapsed") if res_info else None,
        }

        # A test can produce reports for setup/call/teardown.  Keep a single
        # final record so totals match collected test items, while allowing a
        # setup or teardown failure to override an earlier successful call.
        existing = next((entry for entry in self.results if entry["nodeid"] == item.nodeid), None)
        was_failed = bool(existing and existing["outcome"] == "failed")
        if existing is None:
            self.results.append(result)
        else:
            total_duration = existing["duration"] + result["duration"]
            priority = {"passed": 0, "skipped": 1, "failed": 2}
            if priority.get(report.outcome, 0) >= priority.get(existing["outcome"], 0):
                existing.update(result)
            existing["duration"] = total_duration
        self._add_html_details(item, report, req_info, res_info)
        if report.outcome == "failed" and not was_failed:
            try:
                _submit_bug(item, report)
            except Exception as exc:
                self.logger.error("提交 Bug 失败: %s", exc)

    def _add_html_details(self, item, report, req_info, res_info):
        try:
            plugin = item.config.pluginmanager.getplugin("html") or item.config.pluginmanager.getplugin("html-plus")
            if plugin is None or not (req_info or res_info):
                return
            extras = getattr(report, "extra", [])
            if req_info:
                body = req_info.get("body", "")
                body_display = self._safe_json(body) if isinstance(body, (dict, list)) else html.escape(str(body))
                extras.append(plugin.extras.html(
                    "<div><strong>📤 请求详情</strong><br/>"
                    f"<strong>方法:</strong> {html.escape(str(req_info.get('method', '')))}<br/>"
                    f"<strong>URL:</strong> {html.escape(str(req_info.get('url', '')))}<br/>"
                    f"<strong>请求头:</strong><pre>{self._safe_json(sanitize_headers(req_info.get('headers', {})))}</pre>"
                    f"<strong>请求参数:</strong><pre>{self._safe_json(req_info.get('params', {}))}</pre>"
                    f"<strong>请求体:</strong><pre>{body_display}</pre></div>"
                ))
            if res_info:
                extras.append(plugin.extras.html(
                    "<div><strong>📥 响应详情</strong><br/>"
                    f"<strong>状态码:</strong> {html.escape(str(res_info.get('status_code', '')))}<br/>"
                    f"<strong>响应头:</strong><pre>{self._safe_json(sanitize_headers(res_info.get('headers', {})))}</pre>"
                    f"<strong>响应体:</strong><pre>{html.escape(res_info.get('text', '') or '')}</pre></div>"
                ))
            report.extras = extras
        except Exception as exc:
            self.logger.error("附加请求/响应信息失败: %s", exc, exc_info=True)

    def finish(self, config):
        if is_xdist_worker(config):
            publish_worker_results(config, self.results)
            return
        if self.finished:
            return
        self.finished = True
        if not self.results:
            self.logger.warning("无测试结果数据，跳过通知")
            return

        duration = time.time() - self.started_at if self.started_at else 0
        total = len(self.results)
        passed = sum(result["outcome"] == "passed" for result in self.results)
        failed = sum(result["outcome"] == "failed" for result in self.results)
        skipped = sum(result["outcome"] == "skipped" for result in self.results)
        performance_records, slow_alerts = evaluate_cases(self.results)
        append_performance_records(performance_records)
        # The final Allure archive and HTML report are produced by the
        # application after pytest exits.  Defer upload/notification until
        # then so every published link belongs to this run.
        self._pending_notification = {
            "duration": duration,
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "slow_alerts": slow_alerts,
        }

    def notify_after_reports(self, html_report_path=None):
        """Publish a collected pytest result after final artifacts exist."""
        if not self._pending_notification:
            return
        pending = self._pending_notification
        self._pending_notification = None
        report_url = self._upload_report(html_report_path)
        summary, report_data = self._build_summary(report_url=report_url, **pending)
        self._notify(summary, report_data, pending["failed"], pending["slow_alerts"])

    def _upload_report(self, html_report_path=None):
        if not is_report_upload_enabled():
            self.logger.info("ℹ️ 报告上传已关闭；设置 UPLOAD_TEST_REPORT=true 后启用")
            return None
        try:
            return upload_test_report(html_report_path or "./reports/report.html")
        except Exception as exc:
            self.logger.warning("⚠️ 上传报告异常: %s", exc)
            return None

    def _build_summary(self, duration, total, passed, failed, skipped, slow_alerts, report_url):
        pass_rate = round(passed / total * 100, 2) if total else 0
        lines = [
            "## 📊 接口自动化测试报告", "",
            f"**执行人**: {TEST_EXECUTOR}",
            f"**执行时间**: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"**总耗时**: {duration:.2f}s", "",
            f"- 总计: **{total}** ｜ ✅ 通过: **{passed}** ｜ ❌ 失败: **{failed}** ｜ ⏭️ 跳过: **{skipped}**",
            f"- 通过率: **{pass_rate}%**",
        ]
        failed_cases = []
        passed_cases = []
        for result in self.results:
            path = urlparse(result.get("request_url") or "").path or "N/A"
            case_summary = {
                "name": result["name"], "duration": result["duration"],
                "status_code": result.get("status_code"), "response_text": result.get("response_text"),
                "method": result.get("request_method"), "url": result.get("request_url"),
            }
            if result["outcome"] == "failed":
                lines.append(f"- ❌ **{result['name']}**：`{result.get('request_method') or ''} {path}`")
                failed_cases.append({
                    **case_summary,
                    "error": result.get("longrepr") or "无错误详情",
                })
            elif result["outcome"] == "passed":
                passed_cases.append(case_summary)
        if slow_alerts:
            lines.append(f"- ⚠️ 性能告警: **{len(slow_alerts)}** 条")
        lines.extend([f"[📄 本地 Allure 报告]({ALLURE_URL})", f"[📄 公网 Allure 报告]({ALLURE_URLS})"])
        if report_url:
            lines.append(f"[📄 HTML 报告]({report_url})")
        report_data = {
            "executor": TEST_EXECUTOR, "duration": duration, "total": total,
            "passed": passed, "failed": failed, "skipped": skipped, "pass_rate": pass_rate,
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "slow_api_alerts": slow_alerts,
            "failed_cases": failed_cases, "passed_cases": passed_cases,
            "allure_url": ALLURE_URL, "allure_urls": ALLURE_URLS, "report_url": report_url,
            "emergency_contact": EMERGENCY_CONTACT, "emergency_phone": EMERGENCY_PHONE,
            "passed_display_limit": PASSED_DISPLAY_LIMIT,
        }
        return "\n".join(lines), report_data

    def _notify(self, summary, report_data, failed, slow_alerts):
        if NOTIFICATION_MODE == "never":
            return
        should_send = NOTIFICATION_MODE == "always" or (NOTIFICATION_MODE == "only_failed" and (failed or slow_alerts))
        if not should_send:
            self.logger.info("ℹ️ 全部用例通过，不发送通知")
            return
        try:
            _send_robot_notification(summary, report_data)
            _send_phone_call(report_data)
        except Exception as exc:
            self.logger.error("发送测试通知失败: %s", exc)
