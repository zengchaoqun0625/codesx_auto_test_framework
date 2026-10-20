# -*- coding: utf-8 -*-
"""
通知消息构建器模块
包含：配置项、工具函数、各平台消息构建函数、Bug提交、通知内容生成
"""
import html as html_escape
import logging
import os
import subprocess
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from api_project.common.Network import get_local_ip

logger = logging.getLogger(__name__)


# ====================== 配置项 ======================
NOTIFICATION_MODE = os.getenv("PYTEST_NOTIFY_MODE", "only_failed")   #飞书等通知配置
ROBOT_WEBHOOK = os.getenv("ROBOT_WEBHOOK_URL", "")


# Allure 报告地址：环境变量指定时用指定值，未指定时自动获取本机 IP
ALLURE_PORT = os.getenv("ALLURE_PORT", "9797")
ALLURE_URL = os.getenv("ALLURE_URL", "") or f"http://{get_local_ip()}:{ALLURE_PORT}"
ALLURE_URLS = os.getenv("ALLURE_URLS", "https://zx6122129mx.vicp.fun")


def _get_executor() -> str:
    """获取测试执行人：环境变量优先，其次 git config user.name，最后兜底"""
    executor = os.getenv("TEST_EXECUTOR", "")
    if executor:
        return executor
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "未知执行人"


TEST_EXECUTOR = _get_executor()

# 紧急联系人配置（环境变量优先，真实值在 api_project/.env 中配置，勿写死在代码里）
EMERGENCY_CONTACT = os.getenv("EMERGENCY_CONTACT", "")
EMERGENCY_PHONE = os.getenv("EMERGENCY_PHONE", "")

# 成功用例展示数量上限（环境变量可配，默认10条）
PASSED_DISPLAY_LIMIT = int(os.getenv("PASSED_DISPLAY_LIMIT", "10"))

# 电话通知配置（饭碗警告等第三方电话 webhook，POST 触发自动拨打；真实值在 api_project/.env）
PHONE_CALL_WEBHOOK = os.getenv("PHONE_CALL_WEBHOOK", "")


def _status_emoji(status_code) -> str:
    """根据 HTTP 状态码返回对应的颜色 emoji"""
    if not status_code:
        return "⚪"
    try:
        sc = int(status_code)
        if 200 <= sc < 300:
            return "🟢"
        elif 300 <= sc < 400:
            return "🔵"
        elif 400 <= sc < 500:
            return "🟡"
        elif 500 <= sc < 600:
            return "🔴"
        return "⚪"
    except (ValueError, TypeError):
        return "⚪"


def _truncate_to_bytes(text: str, max_bytes: int, suffix: str = "\n\n…(已截断)") -> str:
    """
    按 UTF-8 字节安全截断文本（逐字符缩短，避免截断中文字符导致乱码）
    suffix 含 \\n\\n 分隔符，确保截断提示独占一行不粘连正文
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix_bytes = suffix.encode("utf-8")
    limit = max_bytes - len(suffix_bytes)
    if limit <= 0:
        return suffix
    result = text
    while len(result.encode("utf-8")) > limit and len(result) > 0:
        result = result[:-1]
    return result + suffix


def _build_dingding_markdown(report_data: dict, compact: bool = False) -> str:
    """
    构建钉钉 Markdown 消息内容（不含报告链接，链接由 ActionCard 按钮或截断后追加）
    :param report_data: 结构化报告数据
    :param compact: True 时生成精简版（省略响应体和成功用例详情，用于超长降级）
    """
    lines = [
        f"**执行人**: {report_data.get('executor', '未知')}",
        f"**执行时间**: {report_data.get('now', '未知')}",
        f"**总耗时**: {report_data['duration']:.2f}s",
        "",
        f"总计 **{report_data['total']}** ｜ ✅通过 **{report_data['passed']}** ｜ ❌失败 **{report_data['failed']}** ｜ ⏭️跳过 **{report_data['skipped']}**",
        f"通过率: **{report_data['pass_rate']}%**",
    ]

    contact = report_data.get('emergency_contact', '')
    phone = report_data.get('emergency_phone', '')
    if contact and phone:
        lines.append(f"📞 紧急联系人: {contact} {phone}")

    slow_api_alerts = report_data.get('slow_api_alerts', [])
    if slow_api_alerts:
        lines.append("---")
        lines.append(f"### ⚠️ 接口性能告警（{len(slow_api_alerts)} 个）")
        for alert in slow_api_alerts[:5]:
            lines.append(
                f"- **{alert.get('endpoint', '未知接口')}**：{alert.get('duration_sec', 0):.3f}s "
                f"（阈值 {alert.get('threshold_sec', 0):.3f}s）"
            )

    failed_cases = report_data.get('failed_cases', [])
    if failed_cases:
        lines.append("---")
        lines.append("### ❌ 失败用例")
        for fc in failed_cases:
            sc = fc.get('status_code')
            emoji = _status_emoji(sc) if sc else ""
            method = fc.get('method', '')
            url = fc.get('url', '')
            url_path = urlparse(url).path if url else (url or '')
            lines.append(f"- **{fc['name']}** ({fc['duration']:.2f}s)")
            if method or url_path:
                lines.append(f"  - 接口: `{method} {url_path}`")
            if sc:
                lines.append(f"  - 状态码: {emoji} `{sc}`")
            if not compact and fc.get('response_text'):
                resp = fc['response_text'][:200]
                if len(fc['response_text']) > 200:
                    resp += "..."
                lines.append(f"  - 响应: `{resp}`")

    passed_cases = report_data.get('passed_cases', [])
    if passed_cases and not compact:
        lines.append("---")
        display_limit = report_data.get('passed_display_limit', 10)
        shown = passed_cases[:display_limit]
        header = f"\n### ✅ 成功用例（共{report_data['passed']}个"
        if len(passed_cases) > display_limit:
            header += f"，展示前{display_limit}条"
        header += "）"
        lines.append(header)
        for pc in shown:
            sc = pc.get('status_code')
            emoji = _status_emoji(sc) if sc else ""
            method = pc.get('method', '')
            url = pc.get('url', '')
            url_path = urlparse(url).path if url else (url or '')
            lines.append(f"- **{pc['name']}** ({pc['duration']:.2f}s)")
            if method or url_path:
                lines.append(f"  - 接口: `{method} {url_path}`")
            if sc:
                lines.append(f"  - 状态码: {emoji} `{sc}`")

    return "\n".join(lines)


def _build_weixin_markdown(report_data: dict, compact: bool = False) -> str:
    """
    构建企微 Markdown 消息内容（独立于通用 summary，针对企微 4096 字节限制优化）
    注意：不含报告链接，链接由 _try_send 在截断后追加，确保不被截掉
    :param report_data: 结构化报告数据
    :param compact: True 时生成精简版（省略响应体和成功用例详情，用于超长降级）
    """
    lines = [
        "## 📊 自动化测试报告",
        f"**执行人**: {report_data.get('executor', '未知')}",
        f"**执行时间**: {report_data.get('now', '未知')}",
        f"**总耗时**: {report_data['duration']:.2f}s",
        "",
        f"总计 **{report_data['total']}** ｜ ✅通过 **{report_data['passed']}** ｜ ❌失败 **{report_data['failed']}** ｜ ⏭️跳过 **{report_data['skipped']}**",
        f"通过率: **{report_data['pass_rate']}%**",
    ]

    contact = report_data.get('emergency_contact', '')
    phone = report_data.get('emergency_phone', '')
    if contact and phone:
        lines.append(f"📞 紧急联系人: {contact} {phone}")

    slow_api_alerts = report_data.get('slow_api_alerts', [])
    if slow_api_alerts:
        lines.append("---")
        lines.append(f"### ⚠️ 接口性能告警（{len(slow_api_alerts)} 个）")
        for alert in slow_api_alerts[:5]:
            lines.append(
                f"- **{alert.get('endpoint', '未知接口')}**：{alert.get('duration_sec', 0):.3f}s "
                f"（阈值 {alert.get('threshold_sec', 0):.3f}s）"
            )

    failed_cases = report_data.get('failed_cases', [])
    if failed_cases:
        lines.append("---")
        lines.append("### ❌ 失败用例")
        for fc in failed_cases:
            sc = fc.get('status_code')
            emoji = _status_emoji(sc) if sc else ""
            method = fc.get('method', '')
            url = fc.get('url', '')
            url_path = urlparse(url).path if url else (url or '')
            lines.append(f"- **{fc['name']}** ({fc['duration']:.2f}s)")
            if method or url_path:
                lines.append(f"  - 接口: `{method} {url_path}`")
            if sc:
                lines.append(f"  - 状态码: {emoji} `{sc}`")
            if not compact and fc.get('response_text'):
                resp = fc['response_text'][:200]
                if len(fc['response_text']) > 200:
                    resp += "..."
                lines.append(f"  - 响应: `{resp}`")

    passed_cases = report_data.get('passed_cases', [])
    if passed_cases and not compact:
        lines.append("---")
        display_limit = report_data.get('passed_display_limit', 10)
        shown = passed_cases[:display_limit]
        header = f"\n### ✅ 成功用例（共{report_data['passed']}个"
        if len(passed_cases) > display_limit:
            header += f"，展示前{display_limit}条"
        header += "）"
        lines.append(header)
        for pc in shown:
            sc = pc.get('status_code')
            emoji = _status_emoji(sc) if sc else ""
            method = pc.get('method', '')
            url = pc.get('url', '')
            url_path = urlparse(url).path if url else (url or '')
            lines.append(f"- **{pc['name']}** ({pc['duration']:.2f}s)")
            if method or url_path:
                lines.append(f"  - 接口: `{method} {url_path}`")
            if sc:
                lines.append(f"  - 状态码: {emoji} `{sc}`")

    return "\n".join(lines)


def _build_report_links_md(report_data: dict) -> str:
    """构建报告链接段（钉钉/企微通用，单独提取以便截断后追加，确保链接不被截掉）
    三个链接放同一行，各配独立图标，用 ｜ 分隔
    """
    links = []
    if report_data.get('allure_url'):
        links.append(f"🏠 [Allure报告]({report_data['allure_url']})")
    if report_data.get('allure_urls'):
        links.append(f"🌐 [公网Allure]({report_data['allure_urls']})")
    if report_data.get('report_url'):
        links.append(f"📋 [HTML报告]({report_data['report_url']})")
    if not links:
        return ""
    return "\n---\n" + " ｜ ".join(links)


def _build_feishu_card(report_data: dict) -> dict:
    """构建飞书互动卡片消息（富文本优先方案，含紧急联系人和色彩优化）"""
    elements = []

    # ---- 基本信息 ----
    info_md = (
        f"**👤 执行人**：{report_data.get('executor', '未知')}\n"
        f"**🕐 执行时间**：{report_data.get('now', '未知')}\n"
        f"**⏱️ 总耗时**：{report_data['duration']:.2f}s"
    )
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": info_md}})

    # ---- 紧急联系人（点击直接拨打） ----
    contact = report_data.get('emergency_contact', '')
    phone = report_data.get('emergency_phone', '')
    if contact and phone:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**📞 紧急联系人**：[{contact} {phone}](tel:{phone})（点击直接拨打）"
            }
        })

    elements.append({"tag": "hr"})

    # ---- 统计信息 ----
    stats_md = (
        f"**📈 统计信息**\n"
        f"总计 **{report_data['total']}** ｜ ✅ 通过 **{report_data['passed']}** ｜ "
        f"❌ 失败 **{report_data['failed']}** ｜ ⏭️ 跳过 **{report_data['skipped']}**\n"
        f"📊 通过率：**{report_data['pass_rate']}%**"
    )
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": stats_md}})

    # ---- 接口性能告警 ----
    slow_api_alerts = report_data.get('slow_api_alerts', [])
    if slow_api_alerts:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**⚠️ 接口性能告警（{len(slow_api_alerts)} 个）**"}})
        for alert in slow_api_alerts[:5]:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content":
                    f"🔶 **{alert.get('endpoint', '未知接口')}**：{alert.get('duration_sec', 0):.3f}s"
                    f"（阈值 {alert.get('threshold_sec', 0):.3f}s）"}
            })

    # ---- 失败用例详情（列布局 + 灰色背景 + 状态色标） ----
    failed_cases = report_data.get('failed_cases', [])
    if failed_cases:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "**❌ 失败用例详情**"}})

        for fc in failed_cases:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"\n**{fc['name']}**（{fc['duration']:.2f}s）"}
            })

            method = fc.get('method', '')
            url = fc.get('url', '')
            sc = fc.get('status_code')
            if method or url or sc:
                cols = []
                if method or url:
                    url_path = urlparse(url).path if url else (url or 'N/A')
                    cols.append({
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "vertical_align": "top",
                        "elements": [{
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": f"📤 接口\n`{method or '?'} {url_path}`"}
                        }]
                    })
                if sc:
                    emoji_val = _status_emoji(sc)
                    cols.append({
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "vertical_align": "top",
                        "elements": [{
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": f"🔑 状态码\n{emoji_val} `{sc}`"}
                        }]
                    })
                if cols:
                    elements.append({
                        "tag": "column_set",
                        "flex_mode": "none",
                        "background_style": "grey",
                        "columns": cols
                    })

            if fc.get('response_text'):
                resp = fc['response_text'][:300]
                if len(fc['response_text']) > 300:
                    resp += "..."
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"📥 响应：`{resp}`"}
                })

    # ---- 成功用例 ----
    passed_cases = report_data.get('passed_cases', [])
    if passed_cases:
        elements.append({"tag": "hr"})
        display_limit = report_data.get('passed_display_limit', 10)
        shown = passed_cases[:display_limit]
        header_text = f"**✅ 成功用例（共{report_data['passed']}个"
        if len(passed_cases) > display_limit:
            header_text += f"，展示前{display_limit}条"
        header_text += "）**"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": header_text}})

        for pc in shown:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"\n**{pc['name']}**（{pc['duration']:.2f}s）"}
            })

            method = pc.get('method', '')
            url = pc.get('url', '')
            sc = pc.get('status_code')
            if method or url or sc:
                cols = []
                if method or url:
                    url_path = urlparse(url).path if url else (url or 'N/A')
                    cols.append({
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "vertical_align": "top",
                        "elements": [{
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": f"📤 接口\n`{method or '?'} {url_path}`"}
                        }]
                    })
                if sc:
                    emoji_val = _status_emoji(sc)
                    cols.append({
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "vertical_align": "top",
                        "elements": [{
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": f"🔑 状态码\n{emoji_val} `{sc}`"}
                        }]
                    })
                if cols:
                    elements.append({
                        "tag": "column_set",
                        "flex_mode": "none",
                        "background_style": "grey",
                        "columns": cols
                    })

    elements.append({"tag": "hr"})

    # ---- 报告链接按钮 ----
    actions = []
    if report_data.get('allure_url'):
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📄 局域网 Allure 报告"},
            "url": report_data['allure_url'],
            "type": "primary"
        })
    if report_data.get('allure_urls'):
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📄 公网 Allure 报告"},
            "url": report_data['allure_urls'],
            "type": "default"
        })
    if report_data.get('report_url'):
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📄 HTML 报告"},
            "url": report_data['report_url'],
            "type": "default"
        })
    if actions:
        elements.append({"tag": "action", "actions": actions})

    # ---- 底部备注 ----
    note_text = "🔔 本通知由自动化测试框架自动发送"
    if contact and phone:
        note_text += f" ｜ 📞 {contact} {phone}"
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": note_text}]
    })

    # ---- 卡片头部颜色 ----
    if report_data['failed'] > 0:
        header_template = "red"
    elif report_data['pass_rate'] == 100:
        header_template = "green"
    else:
        header_template = "blue"

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📊 自动化测试报告"},
                "template": header_template
            },
            "elements": elements
        }
    }


def _build_dingding_actioncard(report_data: dict, compact: bool = False) -> dict:
    """构建钉钉 ActionCard 消息（结构化 markdown + 按钮链接）
    :param report_data: 结构化报告数据
    :param compact: True 时生成精简版（省略响应体和成功用例详情，用于超长降级）
    """
    card_text = _build_dingding_markdown(report_data, compact=compact)
    card_text = _truncate_to_bytes(card_text, 4500)

    btns = []
    if report_data.get('allure_url'):
        btns.append({"title": "🏠 Allure报告", "actionURL": report_data['allure_url']})
    if report_data.get('allure_urls'):
        btns.append({"title": "🌐 公网Allure", "actionURL": report_data['allure_urls']})
    if report_data.get('report_url'):
        btns.append({"title": "📋 HTML报告", "actionURL": report_data['report_url']})

    return {
        "msgtype": "actionCard",
        "actionCard": {
            "title": "📊 自动化测试报告",
            "text": card_text,
            "btnOrientation": "0",
            "btns": btns
        }
    }


def _build_notification_content(item, report, is_failed: bool) -> str:
    """构建通知内容（失败或通过时统一格式）"""
    current_time = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    if is_failed:
        title = f"❌ {item.function.__name__} 测试失败"
        content = (
            f"测试用例: {item.function.__name__}\n"
            f"错误详情: {report.longreprtext or '无详细错误'}\n"
            f"预期结果: passed\n"
            f"实际结果: {report.outcome}\n"
            f"执行时间: {current_time}"
        )
    else:
        title = f"✅ {item.function.__name__} 测试通过"
        content = (
            f"测试用例: {item.function.__name__}\n"
            f"执行时间: {current_time}\n"
            f"耗时: {report.duration:.2f}s"
        )
    return f"{title}\n{content}"


def _submit_bug(item, report) -> None:
    """提交Bug到缺陷管理系统"""
    from api_project.config.bug_config import BUG_Config
    from api_project.common.BUG import ZenTaoService, JiraService

    current_time = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    bug_title = f"{item.function.__name__}-{current_time}-测试失败".replace("test_", "")
    bug_doc = (
        f"测试用例: {item.function.__name__}\n"
        f"错误详情: {report.longreprtext}\n"
        f"预期结果: passed\n"
        f"实际结果: {report.outcome}\n"
        f"执行时间: {current_time}"
    )

    try:
        bug_fixer = next(
            fixer for fixer, cases in BUG_Config.Bug_fix_table.items()
            if str(item.function.__name__)[5:] in cases
        )
    except (StopIteration, AttributeError, KeyError):
        bug_fixer = ""

    logger.info(f"ℹ️ 测试失败，准备提交Bug: {bug_title}，负责人: {bug_fixer or '未指定'}")

    bug_service = getattr(BUG_Config, "Bug_Service_Name", "").lower()
    try:
        if bug_service in ("zentao", "禅道"):
            ZenTaoService().submit_bug(
                title=bug_title,
                steps=bug_doc,
                assignedTo=bug_fixer or ZenTaoService.assignedTo or ZenTaoService.account
            )
            logger.info(f"✅ 已提交Bug到禅道: {bug_title}")
        elif bug_service == "jira":
            JiraService().submit_bug(
                project_key="TEST",
                summary=bug_title,
                description=bug_doc,
                project_id=10000,
                assignee_name=bug_fixer or JiraService.assignee or JiraService.username
            )
            logger.info(f"✅ 已提交Bug到Jira: {bug_title}")
        else:
            logger.warning(f"⚠️ 未配置有效的缺陷管理系统（当前: {bug_service}），跳过Bug提交")
    except Exception as e:
        logger.error(f"❌ 提交Bug失败: {str(e)}", exc_info=True)
