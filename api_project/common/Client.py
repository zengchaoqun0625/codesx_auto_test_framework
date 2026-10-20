#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author      : xiaobaiTser
Email       : zengjiangtaoasd@gmail.com
Create Time : 2024/11/20 23:09
File Name   : client.py
Description : Enhanced HTTP client with automatic encoding handling
"""

import os
import sys
import allure
import functools
import requests
from typing import Optional, Union, Dict, Any
from urllib.parse import quote
from requests.auth import HTTPBasicAuth
from jsonpath import jsonpath
from lxml import etree
from re import findall
from ..common.ENV import ENV
from ..common.LOG import Logger

ENV.load()
logger = Logger()

def ensure_utf8(headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Ensure headers contain UTF-8 charset"""
    if headers is None:
        headers = {}
    if 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/json; charset=utf-8'
    elif 'charset=' not in headers['Content-Type']:
        headers['Content-Type'] += '; charset=utf-8'
    return headers

def encode_non_ascii(data: Any) -> Any:
    """Encode non-ASCII data properly"""
    if isinstance(data, str):
        if any(ord(c) > 127 for c in data):
            return data.encode('utf-8')
    elif isinstance(data, dict):
        return {k: encode_non_ascii(v) for k, v in data.items()}
    return data

''' JSON Extractor Decorator '''
def at_json_extractor(env_name: str = None, expression: str = '', index: int = 0, default=None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            if env_name:
                try:
                    allure.step(f'[{func.__name__}]的 {env_name} json提取器')
                    result = jsonpath(response.json(), expression)
                    ENV.set_env(env_name, result[index] if result else default)
                except Exception as e:
                    logger.warning(f"JSON extract failed: {str(e)}")
                    ENV.set_env(env_name, default)
            else:
                raise ValueError("env_name参数不能为空！")
            return response
        return wrapper
    return _call_

def json_extractor(response=None, env_name: str = None, expression: str = '', index: int = 0, default=None):
    """Enhanced JSON extractor with better error handling"""
    if response and env_name:
        try:
            result = jsonpath(response.json(), expression)
            ENV.set_env(env_name, result[index] if result else default)
        except Exception as e:
            logger.warning(f"JSON extract failed: {str(e)}")
            ENV.set_env(env_name, default)
    else:
        raise ValueError("response与env_name参数不能为空！")

''' XPath Extractor Decorator '''
def at_xpath_extractor(env_name: str = None, expression: str = '', index: int = 0, default=None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            if env_name:
                try:
                    allure.step(f'[{func.__name__}]的 {env_name} xpath提取器')
                    tree = etree.HTML(response.text)
                    ENV.set_env(env_name, tree.xpath(expression)[index])
                except Exception as e:
                    logger.warning(f"XPath extract failed: {str(e)}")
                    ENV.set_env(env_name, default)
            else:
                raise ValueError("env_name参数不能为空！")
            return response
        return wrapper
    return _call_

def xpath_extractor(response=None, env_name: str = None, expression: str = '', index: int = 0, default=None):
    """Enhanced XPath extractor"""
    if response and env_name:
        try:
            tree = etree.HTML(response.text)
            result = tree.xpath(expression)
            ENV.set_env(env_name, result[index] if result else default)
        except Exception as e:
            logger.warning(f"XPath extract failed: {str(e)}")
            ENV.set_env(env_name, default)
    else:
        raise ValueError("response与env_name参数不能为空！")

''' Regex Extractor Decorator '''
def at_re_extractor(env_name: str = None, expression: str = '', index: int = 0, default=None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            if env_name:
                try:
                    allure.step(f'[{func.__name__}]的 {env_name} 正则提取器')
                    result = findall(expression, response.text)
                    ENV.set_env(env_name, result[index] if result else default)
                except Exception as e:
                    logger.warning(f"Regex extract failed: {str(e)}")
                    ENV.set_env(env_name, default)
            else:
                raise ValueError("env_name参数不能为空！")
            return response
        return wrapper
    return _call_

def re_extractor(response=None, env_name: str = None, expression: str = '', index: int = 0, default=None):
    """Enhanced regex extractor"""
    if response and env_name:
        try:
            result = findall(expression, response.text)
            ENV.set_env(env_name, result[index] if result else default)
        except Exception as e:
            logger.warning(f"Regex extract failed: {str(e)}")
            ENV.set_env(env_name, default)
    else:
        raise ValueError("response与env_name参数不能为空！")

''' Assertion Utilities '''
def at_json_assert(expression: str = '', index: int = 0, value=None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            allure.step(f'[{func.__name__}]的json路径内容断言')
            result = jsonpath(response.json(), expression)
            assert result and result[index] == value, \
                f"Assert failed: {result[index] if result else None} != {value}"
            return response
        return wrapper
    return _call_

def json_assert(response, expression: str, index: int = 0, value=None):
    """Enhanced JSON assertion"""
    if response:
        result = jsonpath(response.json(), expression)
        assert result and result[index] == value, \
            f"Assert failed: {result[index] if result else None} != {value}"
    else:
        raise ValueError('response参数不能为空！')

class APIClient:
    """Enhanced HTTP client with automatic encoding handling"""
    
    @classmethod
    def request(
        cls,
        method: str = 'GET',
        url: str = '/api_path',
        headers: Optional[Dict[str, str]] = None,
        data: Union[str, bytes, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Union[str, Dict[str, Any]]] = None,
        verify: bool = False,
        auth_username: str = '',
        auth_password: str = '',
        **kwargs
    ) -> requests.Response:
        """
        Send HTTP request with automatic encoding handling
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: API endpoint
            headers: Request headers
            data: Request body (string or bytes)
            json: JSON-serializable object
            params: Query parameters
            verify: SSL verification
            auth_username: Basic auth username
            auth_password: Basic auth password
            **kwargs: Additional requests arguments
            
        Returns:
            requests.Response: HTTP response
        """
        # Encode URL if contains non-ASCII characters
        full_url = os.environ.get('HOST', '') + url
        if any(ord(c) > 127 for c in full_url):
            full_url = quote(full_url, safe='/:?&=')
        
        # Process headers
        headers = ensure_utf8(headers)
        
        # Process params
        if params and isinstance(params, str):
            if any(ord(c) > 127 for c in params):
                params = quote(params, safe='=&')
        elif params and isinstance(params, dict):
            params = {k: quote(v) if isinstance(v, str) and any(ord(c) > 127 for c in v) else v 
                     for k, v in params.items()}
        
        # Process data
        if data and isinstance(data, str):
            data = encode_non_ascii(data)
        
        try:
            response = requests.request(
                method=method.upper(),
                url=full_url,
                headers=headers,
                data=data,
                json=json,
                params=params,
                verify=verify,
                auth=HTTPBasicAuth(auth_username, auth_password) if auth_username else None,
                **kwargs
            )
            response.encoding = 'utf-8'  # Force UTF-8 decoding
            return response
        except UnicodeEncodeError as e:
            logger.error(f"Encoding error: {str(e)}")
            raise ValueError(f"Invalid character encoding: {str(e)}") from e
        except requests.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            raise

    @classmethod
    def session(
        cls,
        method: str = 'GET',
        url: str = '/api_path',
        headers: Optional[Dict[str, str]] = None,
        data: Union[str, bytes, Dict[str, Any], None] = None,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Union[str, Dict[str, Any]]] = None,
        verify: bool = False,
        auth_username: str = '',
        auth_password: str = '',
        **kwargs
    ) -> requests.Response:
        """Send request with session (same parameters as request())"""
        with requests.Session() as s:
            return cls.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                json=json,
                params=params,
                verify=verify,
                auth_username=auth_username,
                auth_password=auth_password,
                **kwargs
            )

# Example usage
if __name__ == '__main__':
    # Test with Chinese characters
    os.environ['HOST'] = 'https://example.com'
    response = APIClient.request(
        method='POST',
        url='/api/test',
        json={'name': '张三', 'comment': '这是一个测试'},
        headers={'X-Test': '中文Header'}
    )
    print(response.text)