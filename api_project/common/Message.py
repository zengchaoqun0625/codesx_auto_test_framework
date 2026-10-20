#! /usr/bin/env python
# -*- coding: utf-8 -*-
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gmail.com
createTime  : 2026/08/2 14:25
fileName    : Message.py
'''
from requests import post
from jsonpath import jsonpath
import time
import hmac
import hashlib
import base64
import urllib.parse
from ..common.LOG import Logger
from ..config.message_config import *


def _redact_webhook(url: str) -> str:
    """Return a diagnostic-safe webhook URL without path/query credentials."""
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return "***"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/***", "", ""))


class MessageManager(MSG_Config):
    logger = Logger()

    def __init__(self):
        self.client = post

    def sendMsg(self, msg: str = ''):
        """通用文本消息发送（保留原有逻辑）"""
        if not msg:
            self.logger.error("msg信息不能为空，必填内容！")
            raise ValueError("msg信息不能为空，必填内容！")

        # 根据不同消息类型设置文本内容
        if self.msg_format.get("msg_type") == "text":
            self.msg_format["content"]["text"] = msg + '\n@所有人 '
        elif self.msg_format.get("msgtype") == "text":  # 钉钉/企业微信格式
            self.msg_format["text"]["content"] = msg + '\n@所有人 '

        self.logger.info(f"准备发送{self.app_name}消息")
        self.logger.debug(f"请求URL: {_redact_webhook(self.webhook)}")
        self.logger.debug(f"请求体: {self.msg_format}")

        try:
            response = self.client(
                url=self.webhook,
                headers={"Content-Type": "application/json"},
                json=self.msg_format,
                verify=False
            )
            self.logger.info(f"响应状态码: {response.status_code}")
            self.logger.debug(f"响应内容: {response.text}")

            if self.assert_jsonpath and self.assert_value is not None:
                result = jsonpath(response.json(), self.assert_jsonpath)
                self.logger.debug(f"JSONPath '{self.assert_jsonpath}' 提取结果: {result}")
                if result and result[0] == self.assert_value:
                    self.logger.info(f'{self.app_name}发送消息已成功')
                else:
                    self.logger.error(
                        f'{self.app_name}消息发送失败：断言不匹配，预期{self.assert_value}，实际{result[0] if result else None}')
            else:
                if response.status_code == 200:
                    self.logger.info(f'{self.app_name}发送消息已成功')
                else:
                    self.logger.error(f'{self.app_name}消息发送失败，HTTP状态码{response.status_code}')
        except Exception as e:
            self.logger.error(f'{self.app_name}的消息发送异常：{str(e)}', exc_info=True)


class DingDingService(DingDing_Config, MessageManager):
    @property
    def signed_webhook(self) -> str:
        """
        生成带「加签」参数的 webhook URL（钉钉开启加签安全设置时必须）
        未配置 secret 时直接返回原 webhook（适用于关键词 / IP 白名单模式）
        """
        if not self.secret:
            return self.webhook
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))
        return f"{self.webhook}&timestamp={timestamp}&sign={sign}"

    def sendRobot(self, msg: str):
        """钉钉发送 Markdown 格式消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": "自动化测试报告",   # 标题必填
                "text": msg
            }
        }
        self._send_payload(payload)

    def _send_payload(self, payload: dict):
        self.logger.info(f"准备发送{self.app_name}消息")
        self.logger.debug(f"请求URL: {_redact_webhook(self.signed_webhook)}")
        self.logger.debug(f"请求体: {payload}")
        try:
            response = self.client(
                url=self.signed_webhook,
                headers={"Content-Type": "application/json"},
                json=payload,
                verify=False
            )
            self.logger.info(f"响应状态码: {response.status_code}")
            self.logger.debug(f"响应内容: {response.text}")
            resp_json = response.json()
            errcode = resp_json.get('errcode')
            if response.status_code == 200 and errcode == 0:
                self.logger.info(f'{self.app_name}发送消息已成功')
            else:
                errmsg = resp_json.get('errmsg', '未知错误')
                self.logger.error(f'{self.app_name}发送消息失败：HTTP {response.status_code}, errcode={errcode}, errmsg={errmsg}')
                raise RuntimeError(f'{self.app_name}发送失败 errcode={errcode}: {errmsg}')
        except Exception as e:
            self.logger.error(f'{self.app_name}的消息发送异常：{str(e)}', exc_info=True)
            raise


class FeiShuService(FeiShu_Config, MessageManager):
    def sendRobot(self, msg: str):
        """飞书发送纯文本消息（Markdown 源码作为文本）"""
        # 临时构造纯文本 payload，不修改原配置
        payload = {
            "msg_type": "text",
            "content": {"text": msg}
        }
        self.logger.info(f"准备发送{self.app_name}消息")
        self.logger.debug(f"请求URL: {_redact_webhook(self.webhook)}")
        self.logger.debug(f"请求体: {payload}")
        try:
            response = self.client(
                url=self.webhook,
                headers={"Content-Type": "application/json"},
                json=payload,
                verify=False
            )
            self.logger.info(f"响应状态码: {response.status_code}")
            self.logger.debug(f"响应内容: {response.text}")
            if response.status_code == 200:
                self.logger.info(f'{self.app_name}发送消息已成功')
            else:
                self.logger.error(f'{self.app_name}发送消息失败，状态码{response.status_code}')
        except Exception as e:
            self.logger.error(f'{self.app_name}的消息发送异常：{str(e)}', exc_info=True)


class WeiXinService(WeiXin_Config, MessageManager):
    def sendRobot(self, msg: str):
        """企业微信发送 Markdown 格式消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": msg
            }
        }
        self._send_payload(payload)

    def _send_payload(self, payload: dict):
        self.logger.info(f"准备发送{self.app_name}消息")
        self.logger.debug(f"请求URL: {_redact_webhook(self.webhook)}")
        self.logger.debug(f"请求体: {payload}")
        try:
            response = self.client(
                url=self.webhook,
                headers={"Content-Type": "application/json"},
                json=payload,
                verify=False
            )
            self.logger.info(f"响应状态码: {response.status_code}")
            self.logger.debug(f"响应内容: {response.text}")
            resp_json = response.json()
        except Exception as e:
            self.logger.error(f'{self.app_name}的消息发送异常：{str(e)}', exc_info=True)
            raise

        # 关键修复：企微服务端返回 errcode != 0 时（如 key 失效/频率限制/格式错误），
        # 之前只 logger.error 不抛异常，导致上层误判为发送成功（静默失败）。
        # 这里主动抛异常，让 conftest 的 try/except 能打印真实错误原因。
        errcode = resp_json.get('errcode')
        if errcode == 0:
            self.logger.info(f'{self.app_name}发送消息已成功')
        else:
            errmsg = resp_json.get('errmsg', '未知错误')
            self.logger.error(f'{self.app_name}发送消息失败：errcode={errcode}, errmsg={errmsg}')
            raise RuntimeError(f"{self.app_name}发送失败 errcode={errcode}: {errmsg}")
