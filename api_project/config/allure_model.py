# -*- coding: utf-8 -*-
"""
Allure标签自动化配置（根据pytest marker自动添加）
"""

import allure

# 定义 marker 与 allure 配置的映射表
ALLURE_MARKER_MAP = {
    "qq_info": {
        "epic": "QQ API接口测试",
        "feature": "QQ信息查询模块",
        "severity": allure.severity_level.CRITICAL,
        "tags": ["QQ接口", "信息查询"],
    },
    "qq_friend": {
        "epic": "QQ API接口测试",
        "feature": "QQ好友查询模块",
        "severity": allure.severity_level.NORMAL,
        "tags": ["QQ接口", "好友模块"],
    },
    "qq_group": {
        "epic": "QQ API接口测试",
        "feature": "QQ群管理模块",
        "severity": allure.severity_level.BLOCKER,
        "tags": ["QQ接口", "群管理"],
    },
}


def setup_allure_marker(item):
    """
    根据 marker 自动配置 Allure 标签
    """
    for mark_name, config in ALLURE_MARKER_MAP.items():
        if mark_name in item.keywords:
            allure.dynamic.epic(config["epic"])
            allure.dynamic.feature(config["feature"])
            allure.dynamic.severity(config["severity"])
            for t in config["tags"]:
                allure.dynamic.tag(t)
