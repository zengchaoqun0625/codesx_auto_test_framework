#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtao@qq.com
createTime  : 2024/11/20 23:09
fileName    : client.py
'''

import os
import allure
import functools
import requests
from requests.auth import HTTPBasicAuth
from jsonpath import jsonpath
from lxml import etree
from re import findall
from ..common.ENV import ENV
from ..common.LOG import Logger

ENV.load()
logger = Logger()

''' json提取器装饰器 '''
def at_json_extractor(env_name: str = None, expression: str = '', index: int = 0, default = None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            if env_name:
                try:
                    allure.step(f'[{func.__name__}]的 {env_name} json提取器')
                    ENV.set_env(env_name, jsonpath(response.json(), expression)[index])
                except Exception as e:
                    ENV.set_env(env_name, default)
            else:
                raise ("env_name参数不能为空！")
        return wrapper
    return _call_


def json_extractor(response = None, env_name: str = None, expression: str = '', index: int = 0, default = None):
    '''
    json提取器
    :param response     : 返回值对象
    :param env_name     : 存储的变量名
    :param expression   : 表达式
    :param index        : 索引值
    :param default      : 默认值/缺省值
    :return:
    '''
    if response and env_name:
        try:
            ENV.set_env(env_name, jsonpath(response.json(), expression)[index])
        except Exception as e:
            ENV.set_env(env_name, default)
    else:
        raise ("response与env_name参数不能为空！")


''' xpath提取器装饰器 '''
def at_xpath_extractor(env_name: str = None, expression: str = '', index: int = 0, default = None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            tree = etree.HTML(response.text())
            if env_name:
                try:
                    allure.step(f'[{func.__name__}]的 {env_name} xpath提取器')
                    ENV.set_env(env_name, tree.xpath(expression)[index])
                except Exception as e:
                    ENV.set_env(env_name, default)
            else:
                raise ("env_name参数不能为空！")
        return wrapper
    return _call_

def xpath_extractor(response = None, env_name: str = None, expression: str = '', index: int = 0, default = None):
    '''
    xpath提取器
    :param response     : 返回值对象
    :param env_name     : 存储的变量名
    :param expression   : 表达式
    :param index        : 索引值
    :param default      : 默认值/缺省值
    :return:
    '''
    if response and env_name:
        try:
            tree = etree.HTML(response.text())
            ENV.set_env(env_name, tree.xpath(expression)[index])
        except Exception as e:
            ENV.set_env(env_name, default)
    else:
        raise ("response与env_name参数不能为空！")

''' 正则提取器装饰器 '''
def at_re_extractor(env_name: str = None, expression: str = '', index: int = 0, default = None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            if env_name:
                try:
                    allure.step(f'[{func.__name__}]的 {env_name} 正则提取器')
                    ENV.set_env(env_name, findall(expression, response.text())[index])
                except Exception as e:
                    ENV.set_env(env_name, default)
            else:
                raise ("env_name参数不能为空！")
        return wrapper
    return _call_

def re_extractor(response = None, env_name: str = None, expression: str = '', index: int = 0, default = None):
    '''
    正则提取器
    :param response     : 返回值对象
    :param env_name     : 存储的变量名
    :param expression   : 表达式
    :param index        : 索引值
    :param default      : 默认值/缺省值
    :return:
    '''
    if response and env_name:
        try:
            ENV.set_env(env_name, findall(expression, response.text())[index])
        except Exception as e:
            ENV.set_env(env_name, default)
    else:
        raise ("response与env_name参数不能为空！")

''' json断言装饰器 '''
def at_json_assert(expression: str = '', index: int = 0, value=None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            allure.step(f'[{func.__name__}]的json路径内容断言')
            assert jsonpath(response.json(), expression)[index] == value
        return wrapper
    return _call_

def json_assert(response, expression: str, index: int = 0, value=None):
    '''
    json断言
    :param response     : 返回值对象
    :param expression   : 表达式
    :param value        : 预期值
    :return:
    '''
    if response:
        assert jsonpath(response.json(), expression)[index] == value
    else:
        raise ('response参数不能为空！')

''' json包含断言装饰器 '''
def at_json_contains_assert(expression: str = '', index: int = 0, value=None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            allure.step(f'[{func.__name__}]的json路径的内容包含断言')
            assert value in jsonpath(response.json(), expression)[index]
        return wrapper
    return _call_

def json_contains_assert(response, expression: str = '', index: int = 0, value=None):
    '''
    json断言
    :param response     : 返回值对象
    :param expression   : 表达式
    :param value        : 预期值
    :return:
    '''
    if response:
        assert value in jsonpath(response.json(), expression)[index]
    else:
        raise ('response参数不能为空！')

''' 内容包含断言装饰器 '''
def at_content_contains_assert(position: str = 'body', value = None):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            allure.step(f'[{func.__name__}]的内容包含断言')
            if position == 'body':
                assert value in response.text()
            elif position == 'headers':
                assert value in response.headers.keys() or value in response.headers.values()
            else:
                raise ('position参数只能选择：headers与body，默认为body')
        return wrapper
    return _call_

def content_contains_assert(response, position: str = 'body', value = None):
    '''
    json断言
    :param response     : 返回值对象
    :param position     : 位置（可选项：headers、body）
    :param value        : 预期值
    :return:
    '''
    if response:
        if position == 'headers':
            assert value in response.headers.keys() or value in response.headers.values()
        elif position == 'body':
            assert value in response.text()
        else:
            raise ('position参数只能选择：headers与body，默认为body')
    else:
        raise ('response参数不能为空！')

''' HTTP状态码断言装饰器 '''
def at_http_status_code_assert(code=200):
    def _call_(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            allure.step(f'[{func.__name__}]的HTTP状态码断言')
            assert response.status_code == code
        return wrapper
    return _call_

class APIClient(object):
    ''' 客户端 '''
    @classmethod
    def request(cls,
                method: str = 'GET',
                url: str = '/api_path',
                headers: dict = None,
                data: str = '',
                json: dict = None,
                params: str = '',
                verify: bool = False,
                auth_username: str = '',
                auth_password: str = '',
                **kwargs):
        return requests.request(method=method,
                                url=os.environ.get('HOST') + url,
                                headers=headers,
                                data=data,
                                json=json,
                                params=params,
                                verify=verify,
                                auth=HTTPBasicAuth(auth_username, auth_password),
                                **kwargs
                                )

    @classmethod
    def session(cls,
                method: str = 'GET',
                url: str = '/api_path',
                headers: dict = None,
                data: str = '',
                json: dict = None,
                params: str = '',
                verify: bool = False,
                auth_username: str = '',
                auth_password: str = '',
                **kwargs):
        s = requests.session()
        return s.request(method=method,
                         url=os.environ.get('HOST') + url,
                         headers=headers,
                         data=data,
                         json=json,
                         params=params,
                         verify=verify,
                         auth=HTTPBasicAuth(auth_username, auth_password),
                         **kwargs
                         )