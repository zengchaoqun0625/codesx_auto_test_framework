# -*- coding: utf-8 -*-
"""
消息发送器模块
包含：飞书/钉钉/企微/电话通知的发送逻辑（带多级降级策略）
"""
import logging
import os
from urllib.parse import urlparse

import requests

from .builders import (
    _build_feishu_card,
    _build_dingding_actioncard,
    _build_dingding_markdown,
    _build_weixin_markdown,
    _build_report_links_md,
    _truncate_to_bytes,
    PHONE_CALL_WEBHOOK,
)
from api_project.config.message_config import FeiShu_Config, DingDing_Config, WeiXin_Config
from api_project.common.Message import FeiShuService, DingDingService, WeiXinService
from api_project.common.settings import get_bool_env, get_positive_float_env

logger = logging.getLogger(__name__)
NOTIFICATION_TIMEOUT = get_positive_float_env("NOTIFICATION_TIMEOUT", 10.0)
NOTIFICATION_VERIFY_TLS = get_bool_env("NOTIFICATION_VERIFY_TLS", default=True)


def _send_feishu_rich(service, report_data: dict) -> bool:
    """发送飞书富文本卡片，成功返回 True，失败返回 False（触发降级）"""
    try:
        payload = _build_feishu_card(report_data)
        response = service.client(
            url=service.webhook,
            headers={"Content-Type": "application/json"},
            json=payload,
            verify=NOTIFICATION_VERIFY_TLS,
            timeout=NOTIFICATION_TIMEOUT,
        )
        if response.status_code == 200:
            resp_json = response.json()
            if resp_json.get("code", -1) == 0 or resp_json.get("StatusCode", -1) == 0:
                return True
            logger.warning(f"⚠️ 飞书富文本响应异常: {resp_json}")
            return False
        logger.warning(f"⚠️ 飞书富文本 HTTP 状态码异常: {response.status_code}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ 飞书富文本发送失败，将降级为文本: {e}")
        return False


def _send_dingding_rich(service, content: str, report_data: dict) -> bool:
    """
    发送钉钉消息，带多级降级策略避免发送失败
    策略：ActionCard 完整版 → ActionCard 精简版 → Markdown 最小摘要 → 失败返回 False
    """
    DD_MAX = 4500
    TRUNCATE_SUFFIX = "\n\n…(已截断)"

    def _try_send_actioncard(compact: bool) -> bool:
        payload = _build_dingding_actioncard(report_data, compact=compact)
        try:
            response = service.client(
                url=service.signed_webhook,
                headers={"Content-Type": "application/json"},
                json=payload,
                verify=NOTIFICATION_VERIFY_TLS,
                timeout=NOTIFICATION_TIMEOUT,
            )
            if response.status_code != 200:
                logger.warning(f"⚠️ 钉钉 HTTP 状态码异常: {response.status_code}")
                return False
            resp_json = response.json()
            errcode = resp_json.get('errcode', -1)
            if errcode == 0:
                logger.info(f"✅ {service.app_name}发送消息已成功")
                return True
            errmsg = resp_json.get('errmsg', '未知错误')
            logger.warning(f"⚠️ 钉钉响应: errcode={errcode}, errmsg={errmsg}")
            return False
        except Exception as e:
            logger.warning(f"⚠️ 钉钉发送异常: {e}")
            return False

    def _try_send_markdown(markdown_text: str, report_data_inner: dict = None) -> bool:
        links_md = ""
        if report_data_inner:
            links_md = _build_report_links_md(report_data_inner)

        links_bytes = len(links_md.encode("utf-8"))
        suffix_bytes = len(TRUNCATE_SUFFIX.encode("utf-8"))
        body_max = DD_MAX - links_bytes - suffix_bytes

        final_text = _truncate_to_bytes(markdown_text, body_max, TRUNCATE_SUFFIX) + links_md

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": "📊 自动化测试报告", "text": final_text}
        }
        try:
            response = service.client(
                url=service.signed_webhook,
                headers={"Content-Type": "application/json"},
                json=payload,
                verify=NOTIFICATION_VERIFY_TLS,
                timeout=NOTIFICATION_TIMEOUT,
            )
            if response.status_code != 200:
                logger.warning(f"⚠️ 钉钉 HTTP 状态码异常: {response.status_code}")
                return False
            resp_json = response.json()
            errcode = resp_json.get('errcode', -1)
            if errcode == 0:
                logger.info(f"✅ {service.app_name}发送消息已成功")
                return True
            errmsg = resp_json.get('errmsg', '未知错误')
            logger.warning(f"⚠️ 钉钉响应: errcode={errcode}, errmsg={errmsg}")
            return False
        except Exception as e:
            logger.warning(f"⚠️ 钉钉发送异常: {e}")
            return False

    # 第1级：ActionCard 完整版
    if _try_send_actioncard(compact=False):
        logger.info("✅ 已发送钉钉通知（ActionCard 完整版）")
        return True

    logger.warning("⚠️ 钉钉 ActionCard 完整版发送失败，尝试精简版...")

    # 第2级：ActionCard 精简版
    if _try_send_actioncard(compact=True):
        logger.info("✅ 已发送钉钉通知（ActionCard 精简版）")
        return True

    logger.warning("⚠️ 钉钉 ActionCard 精简版发送失败，尝试 Markdown 最小摘要...")

    # 第3级：Markdown 最小摘要
    minimal_parts = [
        "📊 测试报告",
        f"执行人: {report_data.get('executor', '未知')}",
        f"总计 {report_data['total']} ｜ 通过 {report_data['passed']} ｜ 失败 {report_data['failed']}",
    ]
    links_md = _build_report_links_md(report_data)
    if links_md:
        minimal_parts.append(links_md.lstrip("\n"))
    minimal = "\n".join(minimal_parts)
    if _try_send_markdown(minimal):
        logger.info("✅ 已发送钉钉通知（Markdown 最小摘要）")
        return True

    logger.error("❌ 钉钉所有降级策略均失败")
    return False


def _send_weixin_rich(service, content: str, report_data: dict) -> bool:
    """
    发送企微 Markdown 消息，带多级降级策略避免发送失败
    策略：完整 Markdown → 精简版 → 最小摘要 → 失败返回 False
    """
    WX_MAX = 4000
    TRUNCATE_SUFFIX = "\n\n…(已截断)"

    def _try_send(markdown_text: str, report_data_inner: dict = None) -> bool:
        links_md = ""
        if report_data_inner:
            links_md = _build_report_links_md(report_data_inner)

        links_bytes = len(links_md.encode("utf-8"))
        suffix_bytes = len(TRUNCATE_SUFFIX.encode("utf-8"))
        body_max = WX_MAX - links_bytes - suffix_bytes

        final_text = _truncate_to_bytes(markdown_text, body_max, TRUNCATE_SUFFIX) + links_md

        payload = {
            "msgtype": "markdown",
            "markdown": {"content": final_text}
        }
        try:
            response = service.client(
                url=service.webhook,
                headers={"Content-Type": "application/json"},
                json=payload,
                verify=NOTIFICATION_VERIFY_TLS,
                timeout=NOTIFICATION_TIMEOUT,
            )
            if response.status_code != 200:
                logger.warning(f"⚠️ 企微 HTTP 状态码异常: {response.status_code}")
                return False
            resp_json = response.json()
            errcode = resp_json.get('errcode', -1)
            if errcode == 0:
                logger.info(f"✅ {service.app_name}发送消息已成功")
                return True
            errmsg = resp_json.get('errmsg', '未知错误')
            logger.warning(f"⚠️ 企微响应: errcode={errcode}, errmsg={errmsg}")
            return False
        except Exception as e:
            logger.warning(f"⚠️ 企微发送异常: {e}")
            return False

    # 第1级：完整企微 Markdown
    weixin_md = _build_weixin_markdown(report_data, compact=False)
    if _try_send(weixin_md, report_data):
        logger.info("✅ 已发送企业微信通知（完整版）")
        return True

    logger.warning("⚠️ 企微完整版发送失败，尝试精简版...")

    # 第2级：精简版
    weixin_md_compact = _build_weixin_markdown(report_data, compact=True)
    if _try_send(weixin_md_compact, report_data):
        logger.info("✅ 已发送企业微信通知（精简版）")
        return True

    logger.warning("⚠️ 企微精简版发送失败，尝试最小摘要...")

    # 第3级：最小文本摘要
    minimal_parts = [
        "📊 测试报告",
        f"执行人: {report_data.get('executor', '未知')}",
        f"总计 {report_data['total']} ｜ 通过 {report_data['passed']} ｜ 失败 {report_data['failed']}",
    ]
    links_md = _build_report_links_md(report_data)
    if links_md:
        minimal_parts.append(links_md.lstrip("\n"))
    minimal = "\n".join(minimal_parts)
    if _try_send(minimal):
        logger.info("✅ 已发送企业微信通知（最小摘要）")
        return True

    logger.error("❌ 企微所有降级策略均失败")
    return False


def _send_robot_notification(content: str, report_data: dict = None) -> bool:
    """
    统一发送机器人通知
    优先发送富文本消息，失败时逐级降级
    :param content: 文本格式通知内容（Markdown，兜底使用）
    :param report_data: 结构化报告数据（用于构建富文本），为 None 时直接使用文本格式
    :return: 是否至少成功发送到一个平台
    """
    sent_count = 0

    # 飞书
    if FeiShu_Config._token_ and FeiShu_Config.webhook:
        try:
            feishu_service = FeiShuService()
            rich_sent = False
            if report_data:
                rich_sent = _send_feishu_rich(feishu_service, report_data)
            if rich_sent:
                logger.info("✅ 已发送飞书富文本通知")
                sent_count += 1
            else:
                feishu_service.sendRobot(content)
                logger.info("✅ 已发送飞书通知（文本降级）")
                sent_count += 1
        except Exception as e:
            logger.error(f"❌ 飞书通知发送失败: {e}")
    else:
        logger.debug("飞书未配置 token，跳过")

    # 钉钉
    if DingDing_Config._token_ and DingDing_Config.webhook:
        try:
            dingding_service = DingDingService()
            rich_sent = False
            if report_data:
                rich_sent = _send_dingding_rich(dingding_service, content, report_data)
            if rich_sent:
                sent_count += 1
            else:
                dingding_service.sendRobot(content)
                logger.info("✅ 已发送钉钉通知（文本降级）")
                sent_count += 1
        except Exception as e:
            logger.error(f"❌ 钉钉通知发送失败: {e}")
    else:
        logger.debug("钉钉未配置 token，跳过")

    # 企业微信
    if WeiXin_Config._token_ and WeiXin_Config.webhook:
        try:
            weixin_service = WeiXinService()
            rich_sent = False
            if report_data:
                rich_sent = _send_weixin_rich(weixin_service, content, report_data)
            if rich_sent:
                sent_count += 1
            else:
                weixin_service.sendRobot(content)
                logger.info("✅ 已发送企业微信通知（文本降级）")
                sent_count += 1
        except Exception as e:
            logger.error(f"❌ 企业微信通知发送失败: {e}")
    else:
        logger.debug("企业微信未配置 token，跳过")

    if sent_count == 0:
        logger.warning("⚠️ 未配置任何机器人（飞书/钉钉/企微），请检查 message_config.py")

    return sent_count > 0


def _send_phone_call(report_data: dict) -> bool:
    """
    发送电话通知（第三方电话 webhook，如饭碗警告 fwalert）
    - 跟随 NOTIFICATION_MODE 开关逻辑
    - webhook 未配置时跳过
    """
    if not PHONE_CALL_WEBHOOK:
        logger.debug("📞 电话通知 webhook 未配置，跳过")
        return False

    executor = report_data.get("executor", "未知")
    total = report_data.get("total", 0)
    passed = report_data.get("passed", 0)
    failed = report_data.get("failed", 0)
    pass_rate = report_data.get("pass_rate", 0)
    allure_url = report_data.get("allure_url", "")

    if failed > 0:
        failed_names = [fc["name"] for fc in report_data.get("failed_cases", [])][:3]
        fail_summary = "、".join(failed_names) if failed_names else "未知用例"
        brief = (
            f"自动化测试告警。执行人{executor}。"
            f"共{total}个用例，失败{failed}个。失败用例：{fail_summary}。请及时处理。"
        )
        details = (
            f"执行人：{executor}\n"
            f"总计 {total} ｜ 通过 {passed} ｜ 失败 {failed} ｜ 通过率 {pass_rate}%\n"
            f"失败用例：{fail_summary}\n"
            f"Allure报告：{allure_url}"
        )
    else:
        brief = (
            f"自动化测试通知。执行人{executor}。"
            f"共{total}个用例，全部通过。"
        )
        details = (
            f"执行人：{executor}\n"
            f"总计 {total} ｜ 全部通过 ｜ 通过率 100%\n"
            f"Allure报告：{allure_url}"
        )

    try:
        last_err = None
        logger.debug(f"📞 电话播报内容(brief): {brief}")
        for attempt in range(2):
            try:
                resp = requests.post(
                    PHONE_CALL_WEBHOOK,
                    params={"brief": brief, "details": details},
                    timeout=NOTIFICATION_TIMEOUT,
                    verify=NOTIFICATION_VERIFY_TLS,
                )
                if resp.status_code == 200:
                    logger.info(f"✅ 已发送电话通知（HTTP {resp.status_code}）")
                    return True
                else:
                    logger.warning(f"⚠️ 电话通知返回非200：HTTP {resp.status_code} - {resp.text[:200]}")
                    return False
            except Exception as e:
                last_err = e
                if attempt == 0:
                    logger.warning(f"⚠️ 电话通知第1次失败，正在重试：{e}")
                    continue
        if last_err:
            logger.error(f"❌ 电话通知发送失败：{last_err}")
        return False
    except Exception as e:
        logger.error(f"❌ 电话通知发送失败：{e}")
        return False
