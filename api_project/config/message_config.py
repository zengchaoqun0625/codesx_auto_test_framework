#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gmail.com
createTime  : 2026/08/2 14:30
fileName    : message_config.py
'''
import os
from typing import Union, Any

class MSG_Config(object):
    app_name            : str = ''
    _token_             : str = ''
    webhook             : str = ''
    # msg                 : str = ''
    msg_format          : dict = {}
    assert_jsonpath     : str = ''
    assert_value        : Union[Any] = None

class FeiShu_Config(MSG_Config):
    app_name            :str = '飞书'
    # webhook token 从环境变量读取（防明文入库，.env 中配置 FEISHU_TOKEN）
    _token_             :str = os.getenv("FEISHU_TOKEN", '')
    webhook_help_document :str = 'https://open.feishu.cn/document/ukTMukTMukTM/ucTM5YjL3ETO24yNxkjN'
    webhook             :str = 'https://open.feishu.cn/open-apis/bot/v2/hook/' + _token_
    msg                 :str = 'Hello,FeiShu!'
    msg_format          :dict= {"msg_type": "text", "content": {"text": '@所有人'}}
    assert_jsonpath     :str = "code"
    assert_value        :int = 0

class DingDing_Config(MSG_Config):
    app_name            :str = '钉钉'
    # webhook token 从环境变量读取（.env 中配置 DINGDING_TOKEN）
    _token_             :str = os.getenv("DINGDING_TOKEN", '')
    webhook_help_document :str = 'https://open.dingtalk.com/document/group/custom-robot-access'
    webhook             :str = 'https://oapi.dingtalk.com/robot/send?access_token=' + _token_
    # 钉钉机器人「加签」密钥；默认为空（不加签），仅当环境变量 DINGDING_SECRET 配置了值时才走加签
    # 适用于"自定义关键词"或"IP 白名单"模式，飞书/企微完全不受影响
    secret              :str = os.getenv("DINGDING_SECRET", "")
    # msg                 :str = 'Hello,DingDing!'
    msg_format          :dict= {"msgtype": "text", "text": {"content": '@所有人'}}
    assert_jsonpath     :str = 'errcode'
    assert_value        :int = 0

class WeiXin_Config(MSG_Config):
    app_name            :str = "企业微信"
    # webhook token 从环境变量读取（.env 中配置 WEIXIN_TOKEN）
    _token_             :str = os.getenv("WEIXIN_TOKEN", '')
    webhook_help_document :str = 'https://developer.work.weixin.qq.com/document/path/91770'
    webhook             :str = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' + _token_
    # msg                 :str = 'Hello WeiXin!'
    msg_format          :dict= {"msgtype": "text", "text": {"content": '@所有人'}}
    assert_jsonpath     :str = 'errcode'
    assert_value        :int = 0