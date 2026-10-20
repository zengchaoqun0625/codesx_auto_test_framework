#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gmail.com
createTime  : 2024/11/20 0:59
fileName    : ENV.py
'''

import os
from typing import Any
try:
    from dotenv import load_dotenv
except ImportError as exc:
    raise ImportError(
        "缺少 python-dotenv。请先使用当前项目环境执行：pip install -r requirements.txt"
    ) from exc
from .. import ENV_PATH
from .LOG import Logger

logger = Logger()

class ENV(object):
    ''' 持久性环境变量 '''
    def __init__(self):
        pass

    @classmethod
    def load(cls, path: str = ENV_PATH):
        ''' 加载环境变量 '''
        # 加载环境变量
        if os.path.exists(path):
            try:
                load_dotenv(dotenv_path=path)
                logger.info(f'[{path}]文件加载成功~')
            except Exception as e:
                logger.error(f'[{path}]文件加载失败:{e}')
        else:
            # 创建文件
            with open(path, 'w', encoding='utf-8') as f:
                f.write('')
                f.close()
            logger.info(f'[{path}]文件创建成功~')

    @classmethod
    def set_env(cls, key: str, value: Any):
        ''' 设置环境变量 '''
        os.environ[key] = value
        logger.info(f'{key}={value}环境变量设置成功~')


    @classmethod
    def get_env(cls, key: str):
        ''' 获取环境变量 '''
        logger.info(f'获取{key}环境变量：{os.environ.get(key)}')
        return os.environ.get(key)
