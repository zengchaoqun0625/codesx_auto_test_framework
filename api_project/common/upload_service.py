# -*- coding: utf-8 -*-
"""
文件上传服务模块
提供测试报告上传功能（tmpfile.link）
"""
import os
import tempfile
from abc import ABC, abstractmethod
from typing import Optional


class UploadService(ABC):
    @abstractmethod
    def upload(self, file_name, file_content, file_size):
        pass


class TmpFileUploadService(UploadService):
    """使用 tmpfile.link 上传文件，获取公网临时链接"""

    def __init__(self, user_id=None, auth_token=None):
        try:
            from tflink import TFLinkClient
        except ImportError:
            raise ImportError("请先安装 tflink: pip install tflink")

        if user_id and auth_token:
            self.client = TFLinkClient(user_id=user_id, auth_token=auth_token)
            self.upload_type = "authenticated"
        else:
            self.client = TFLinkClient()
            self.upload_type = "anonymous"

    def upload(self, file_name, file_content, file_size):
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp_file:
            tmp_file.write(file_content)
            tmp_path = tmp_file.name

        try:
            result = self.client.upload(tmp_path)
            download_link = getattr(result, 'download_link', None) or getattr(result, 'downloadLink', None)

            return {
                "service": "tmpfile.link",
                "file_name": file_name,
                "file_size": file_size,
                "file_url": download_link,
            }
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


def upload_test_report(file_path: str) -> Optional[str]:
    """
    上传测试报告文件，返回公网链接

    :param file_path: 报告文件路径，如 ./reports/report.html
    :return: 公网链接，上传失败返回 None
    """
    if not os.path.exists(file_path):
        print(f"⚠️ 报告文件不存在: {file_path}")
        return None

    if os.path.getsize(file_path) == 0:
        print(f"⚠️ 报告文件为空: {file_path}")
        return None

    try:
        with open(file_path, 'rb') as f:
            file_content = f.read()
            file_size = len(file_content)
            file_name = os.path.basename(file_path)

        print(f"📄 读取报告成功: {file_name} ({file_size} bytes)")

        service = TmpFileUploadService()
        result = service.upload(file_name, file_content, file_size)

        file_url = result.get("file_url")
        if file_url:
            print(f"✅ 报告上传成功: {file_url}")
            return file_url
        else:
            print(f"⚠️ 上传成功但未获取到链接: {result}")
            return None

    except Exception as e:
        print(f"❌ 上传报告失败: {e}")
        return None
