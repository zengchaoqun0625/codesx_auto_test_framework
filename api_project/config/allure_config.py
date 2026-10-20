#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@qq.com
createTime  : 2024/11/25 10:51
fileName    : allure_config.py
'''

import os
import socket
from pathlib import Path


def _get_local_ip():
    """Resolve a local address without importing api_project.common (avoids cycles)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"

class Allure(object):
    PATH    : str = os.getenv("ALLURE_PATH", str(Path(__file__).resolve().parent.parent / "bin" / "allure" / "bin" / "allure.bat"))
    IP      : str = _get_local_ip()
    PORT    : int = 9797
