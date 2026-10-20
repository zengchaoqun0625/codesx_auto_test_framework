#! /usr/bin/env python
# -*- coding: utf-8 -*-
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@qq.com
createTime  : 2026/08/06  23:28
fileName    : host_config.py
Description : 主机配置加载器，多优先级获取API测试主机地址
'''
import importlib
import logging
from pathlib import Path
from typing import Optional

import pytest

logger = logging.getLogger(__name__)


class HostConfig:
    """
    主机配置加载器：多优先级获取API测试主机地址
    优先级顺序：缓存 → 命令行--api-host → host_config.py → pytest.ini → 报错
    """
    _cached_host: Optional[str] = None  # 缓存主机地址，减少重复加载
    _HOST_CONFIG_REQUIRED_ATTRS = ["CURRENT_HOST", "TEST_HOST", "PRO_HOST"]  # 必要配置属性

    @staticmethod
    def get_host(pytest_config: pytest.Config) -> str:
        """对外提供的统一获取主机地址入口"""
        # 1. 优先使用缓存
        if HostConfig._cached_host:
            return HostConfig._cached_host

        # 2. 读取命令行参数--api-host
        cli_host = HostConfig._get_cli_host(pytest_config)
        if cli_host:
            HostConfig._cached_host = cli_host
            return cli_host

        # 3. 读取host_config.py配置
        config_host = HostConfig._get_config_host()
        if config_host:
            HostConfig._cached_host = config_host
            return config_host

        # 4. 读取pytest.ini配置
        ini_host = HostConfig._get_ini_host(pytest_config)
        if ini_host:
            HostConfig._cached_host = ini_host
            return ini_host

        # 5. 所有方式失败，抛出明确错误
        error_msg = (
            "未配置有效的API主机地址！请通过以下方式之一设置：\n"
            "1. 命令行参数：pytest --api-host https://your-api-domain.com\n"
            "2. 配置文件：在api_project/config/host_config.py中定义HOST类\n"
            "3. 配置文件：在pytest.ini中添加base_url = https://your-api-domain.com"
        )
        logger.error(error_msg)
        return ""

    @staticmethod
    def _get_cli_host(pytest_config: pytest.Config) -> Optional[str]:
        """从命令行参数--api-host获取主机地址"""
        cli_host = pytest_config.getoption("--api-host")
        if not cli_host:
            return None

        validated_host = HostConfig._validate_url(cli_host.strip())
        if validated_host:
            logger.info(f"✅ 使用命令行指定的主机地址: {validated_host}")
            return validated_host
        logger.warning(f"❌ 命令行参数--api-host提供的URL无效: {cli_host}")
        return None

    @staticmethod
    def _get_config_host() -> Optional[str]:
        """从host_config.py获取主机地址（动态导入避免硬依赖）"""
        # 计算host_config.py的绝对路径（适配不同运行环境）
        current_file = Path(__file__).resolve()
        # 当前文件在 common/ 目录，config/ 在同级
        config_file_path = current_file.parent.parent / "config" / "host_config.py"
        if not config_file_path.exists():
            logger.warning(f"⚠️  未找到host_config.py文件，路径: {str(config_file_path)}")
            return None

        try:
            # 动态导入host_config.py
            spec = importlib.util.spec_from_file_location("host_config", str(config_file_path))
            if not spec or not spec.loader:
                logger.error(f"❌ 无法解析host_config.py文件，路径: {str(config_file_path)}")
                return None

            host_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(host_module)

            # 验证HOST类及必要属性
            if not hasattr(host_module, "HOST"):
                logger.error("❌ host_config.py中未定义HOST类")
                return None

            host_class = host_module.HOST
            for attr in HostConfig._HOST_CONFIG_REQUIRED_ATTRS:
                if hasattr(host_class, attr):
                    host_value = getattr(host_class, attr)
                    if isinstance(host_value, str) and host_value.strip():
                        validated_host = HostConfig._validate_url(host_value.strip())
                        if validated_host:
                            logger.info(f"✅ 从host_config.py加载主机地址（{attr}）: {validated_host}")
                            return validated_host

            logger.error(
                f"❌ host_config.py的HOST类缺少有效属性！\n"
                f"需定义以下属性之一：{HostConfig._HOST_CONFIG_REQUIRED_ATTRS}"
            )
            return None

        except Exception as e:
            logger.error(f"❌ 加载host_config.py失败: {str(e)}", exc_info=True)
            return None

    @staticmethod
    def _get_ini_host(pytest_config: pytest.Config) -> Optional[str]:
        """从pytest.ini配置文件获取base_url"""
        try:
            ini_base_url = pytest_config.getini("base_url")
            if isinstance(ini_base_url, str) and ini_base_url.strip():
                validated_host = HostConfig._validate_url(ini_base_url.strip())
                if validated_host:
                    logger.info(f"✅ 从pytest.ini加载主机地址: {validated_host}")
                    return validated_host
            logger.warning("⚠️ pytest.ini中未配置有效的base_url")
            return None
        except Exception as e:
            logger.error(f"❌ 读取pytest.ini的base_url失败: {str(e)}", exc_info=True)
            return None

    @staticmethod
    def _validate_url(url: str) -> Optional[str]:
        """
        验证并修复URL格式
        - 自动补充http/https协议头
        - 检查域名有效性（包含.）
        """
        if not url:
            return None

        # 补充协议头（优先https）
        if not url.startswith(("http://", "https://")):
            logger.warning(f"⚠️ URL缺少协议头，自动补充为https://{url}")
            url = f"https://{url}"

        # 简单验证域名格式（包含.，排除无效地址）
        url_domain = url.split("//")[-1].split("/")[0]  # 提取域名部分（排除路径）
        if "." not in url_domain:
            logger.error(f"❌ URL格式无效（域名缺少.）: {url}")
            return None

        return url
