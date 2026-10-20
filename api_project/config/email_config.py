#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gamil.com
createTime  : 2026/05/21 11:11
fileName    : email_config.py
'''

import os
from typing import List

class EMail(object):
    # QQ的SMTP服务域名
    _QQ_SMTP_HOST_      : str = 'smtp.qq.com'
    _163_SMTP_HOST_     : str = 'smtp.163.com'
    # SMTP服务域名或者IP
    SMTP_HOST           : str = os.getenv("SMTP_HOST", _QQ_SMTP_HOST_)
    # SMTP端口号
    SMTP_PORT           : int = int(os.getenv("SMTP_PORT", "465"))
    USE_SSL = True  # 使用SSL连接
    # 邮箱登录用户名（环境变量优先，防止明文入库）
    SMTP_UserName       : str = os.getenv("SMTP_USERNAME", '')
    # 邮箱密码或者授权码（环境变量优先，防止明文入库）
    SMTP_Passwd         : str = os.getenv("SMTP_PASSWORD", '')
    # 邮件标题
    Subject_Title       : str = os.getenv("SMTP_SUBJECT", '曾超群自动化测试')
    # 收件人（逗号分隔的环境变量，或列表）
    Receiver            : List[str] = [
        r.strip() for r in os.getenv("SMTP_RECEIVERS", '').split(',') if r.strip()
    ]
    # 邮件内容：不在模块导入时生成（此时 data/ 刚被清空，取不到本次用例结果），
    # 由 EmailService.send() 在发送时动态生成最新 HTML；此处仅作占位。
    Content_HTML            : str = ''


