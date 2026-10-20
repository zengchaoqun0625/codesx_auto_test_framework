#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gamil.com
createTime  : 2026/05/21 11:11
fileName    : Email.py
'''
import smtplib
from typing import Union
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from ..config.email_config import EMail
from ..common.LOG import Logger
from ..common.Data import get_case_result_html


class EmailService(object):

    @classmethod
    def send(cls, content: str = None, content_type: str = 'html', files: Union[str, list] = ''):
        """
        发送邮件，失败时抛出异常
        :param content: 邮件正文，为 None 时自动从最新 allure 结果动态生成（避免模块导入时 data/ 为空）
        :param content_type: 内容类型（html/plain）
        :param files: 附件路径，支持字符串（单个或逗号分隔）或列表
        :raises: 任何发送过程中的异常（如认证失败、网络问题等）
        """
        # 校验配置
        if not EMail.SMTP_UserName or not EMail.SMTP_Passwd:
            raise ValueError('SMTP_UserName或SMTP_Passwd未配置，无法发送邮件，请检查配置文件：API_Project/api_project/config/email_config.py')

        # 未显式传正文时，实时生成最新用例结果（修复：类属性在模块导入时生成导致拿不到本次结果）
        if content is None:
            content = get_case_result_html()

        logger = Logger()
        message = MIMEMultipart()
        message['From'] = EMail.SMTP_UserName
        message['To'] = ",".join(EMail.Receiver)
        message['Subject'] = Header(EMail.Subject_Title, 'utf-8')
        message.attach(MIMEText(content, content_type, 'utf-8'))

        # ---------- 附件处理 ----------
        attr_list = []
        if isinstance(files, str) and files != '' and ',' not in files:
            attr_list.append(files)
        elif isinstance(files, str) and ',' in files:
            attr_list = [f.strip() for f in files.split(',') if f.strip()]
        elif isinstance(files, list):
            attr_list = files

        for fpath in attr_list:
            try:
                with open(fpath, 'rb') as f:
                    _attr_ = MIMEText(f.read(), 'base64', 'utf-8')
                _attr_["Content-Type"] = 'application/octet-stream'
                # 只取文件名，避免包含路径
                filename = os.path.basename(fpath) if 'os' in dir() else fpath
                _attr_["Content-Disposition"] = f'attachment; filename="{filename}"'
                message.attach(_attr_)
                logger.info(f'已添加附件：{fpath}')
            except FileNotFoundError:
                logger.warning(f'附件文件不存在，已跳过：{fpath}')
            except Exception as e:
                logger.warning(f'添加附件 {fpath} 时发生错误：{e}，已跳过')
        # -----------------------------

        smtpObj = None
        try:
            # 建立 SSL 连接
            smtpObj = smtplib.SMTP_SSL(EMail.SMTP_HOST, EMail.SMTP_PORT, timeout=30)
            smtpObj.login(EMail.SMTP_UserName, EMail.SMTP_Passwd)
            smtpObj.sendmail(EMail.SMTP_UserName, EMail.Receiver, message.as_string())
            # 邮件数据已成功投递到服务器（收到 250 响应），记录成功
            logger.info("邮件已成功投递到服务器")
            # 不调用 quit()，直接关闭连接，避免因服务器主动断开而抛出异常
            smtpObj.close()
            logger.info("连接已正常关闭")
        except Exception as e:
            # 记录详细错误
            logger.error(f'邮件发送失败！{e}')
            # 重新抛出，让上层调用方处理（如重试或记录最终结果）
            raise
        finally:
            # 确保连接被关闭（如果上面 close 失败或未执行）
            if smtpObj:
                try:
                    smtpObj.close()
                except:
                    pass