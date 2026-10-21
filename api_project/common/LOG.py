#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gmail.com
createTime  : 2024/11/23 22:30
fileName    : LOG.py
'''
import os, sys
from datetime import datetime
from ..config.log_config import file_name
from .. import LOG_DIR_PATH

class Logger(object):
    def __init__(self):
        self.logfile = os.path.join(LOG_DIR_PATH, file_name)

    def logging(self, message, level, stream=sys.stdout, end='\n'):
        if level.lower() in ['debug', 'info', 'warning', 'error']:
            COLOR = {'debug': '\033[34m', 'info': '\033[37m', 'warning': '\033[33m', 'error': '\033[31m'}
            log = [
                COLOR[level.lower()],
                f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]',
                ' - ',
                f'[{level.upper()}]{(7-len(level)) * " "}',
                ' - ',
                f'{message}',
                end
            ]
            log_content =  ''.join(log)
            try:
                stream.write(log_content)
            except UnicodeEncodeError:
                # 独立脚本可能在 GBK 控制台中运行；日志不能因 emoji/中文
                # 编码失败而中断报告、调度等主流程。
                encoding = getattr(stream, 'encoding', None) or 'utf-8'
                safe_content = log_content.encode(encoding, errors='backslashreplace').decode(encoding)
                stream.write(safe_content)
            if not os.path.exists(os.path.dirname(self.logfile)):
                os.makedirs(os.path.dirname(self.logfile))
            with open(self.logfile, 'a', encoding='utf-8') as f:
                f.write(log_content[5:])  # 去掉颜色代码
        else:
            raise ValueError(f"无效的日志level: {level}, 有效level范围是：'debug', 'info', 'warning', 'error'")

    def info(self, message: str = '', **kwargs):
        self.logging(message, level='INFO')

    def INFO(self, message: str = '', **kwargs):
        self.logging(message, level='INFO')

    def error(self, message: str = '', **kwargs):
        self.logging(message, level='ERROR', stream=sys.stderr)

    def ERROR(self, message: str = '', **kwargs):
        self.logging(message, level='ERROR', stream=sys.stderr)

    def warning(self, message: str = '', **kwargs):
        self.logging(message, level='WARNING')

    def WARNING(self, message: str = '', **kwargs):
        self.logging(message, level='WARNING')

    def debug(self, message: str = '', **kwargs):
        self.logging(message, level='DEBUG')

    def DEBUG(self, message: str = '', **kwargs):
        self.logging(message, level='DEBUG')
