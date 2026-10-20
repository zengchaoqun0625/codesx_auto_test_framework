#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gmail.com
createTime  : 2024/11/25 10:58
fileName    : IP.py
'''

import socket
import ipaddress
import re
import subprocess
from urllib.request import urlopen
from ..common.LOG import Logger

logger = Logger()

def _is_usable_private_ipv4(value: str) -> bool:
    """Return whether ``value`` can be presented as a LAN address."""
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and address.is_private and not address.is_loopback and not address.is_link_local
    except ValueError:
        return False


def _local_ipv4_candidates() -> list[str]:
    """Read Windows interfaces so VPN/TUN routes do not hide the Wi-Fi IP."""
    candidates = []
    try:
        output = subprocess.run(
            ["ipconfig"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=3
        ).stdout
        for value in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", output):
            if _is_usable_private_ipv4(value) and value not in candidates:
                candidates.append(value)
    except (OSError, subprocess.SubprocessError):
        pass
    return candidates


def get_local_ip():
    '''获取适合局域网访问的本机 IPv4 地址。'''
    # A UDP route probe is fast, but VPN/TUN adapters can make it select an
    # inaccessible 172.x address. Prefer a normal RFC1918 LAN range whenever
    # Windows reports one, then use the route-probe result as fallback.
    route_ip = ''
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            route_ip = sock.getsockname()[0]
    except OSError:
        pass

    candidates = _local_ipv4_candidates()
    if _is_usable_private_ipv4(route_ip) and route_ip not in candidates:
        candidates.append(route_ip)

    preferred_prefixes = ("192.168.", "10.", "172.")
    for prefix in preferred_prefixes:
        for value in candidates:
            if value.startswith(prefix):
                logger.info(f'获取本机局域网IP：{value}')
                return value

    logger.warning("未找到可用局域网 IPv4 地址，默认返回 127.0.0.1")
    return '127.0.0.1'

def get_ip():
    '''
    获取本机公网IP
    :return: 公网IP
    '''
    try:
        ip = urlopen('https://ipinfo.io/ip').read().decode()
        logger.info(f'获取本机公网IP：{ip}')
        return ip
    except Exception as e:
        logger.error(f"获取本机公网IP出错: {e}，默认返回：0.0.0.0，建议使用局域网访问")
        return '0.0.0.0'

def check_port(port):
    '''
    检查端口是否被占用
    :param port: 端口号
    :return: True表示被占用，False表示未被占用
    '''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((get_local_ip(), port))
            logger.info(f'端口{port}未使用')
            return False
        except socket.error:
            logger.info(f'端口{port}已被使用')
            return True
