#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gamil.com
createTime  : 2024/11/18 23:29
fileName    : __init__.py
'''

import os

INDENT = 4
TAB_SPACE = INDENT * ' '
FEED = '\n' if os.name == 'nt' else '\r\n'
ALLURE_EXE = 'allure.bat' if os.name == 'nt' else 'allure'

PROJECT_ABS_PATH = os.path.dirname(os.path.realpath(__file__))
DATA_DIR_PATH = os.path.join(PROJECT_ABS_PATH, 'data')
REPORT_DIR_PATH = os.path.join(PROJECT_ABS_PATH, 'report')
LOG_DIR_PATH = os.path.join(PROJECT_ABS_PATH, 'log')
ALLURE_BIN_PATH = os.path.join(PROJECT_ABS_PATH, 'bin', 'allure', 'bin', ALLURE_EXE)
ALLURE_REPORT_DIR_PATH = os.path.join(PROJECT_ABS_PATH, 'allure-report')
ENV_PATH = os.path.join(PROJECT_ABS_PATH, '.env')
CASE_DATA_DIR_PATH = os.path.join(PROJECT_ABS_PATH, 'case_data_files')
CASE_SCRIPT_DIR_PATH = os.path.join(PROJECT_ABS_PATH, 'testcases')
CONFIG_DIR_PATH = os.path.join(PROJECT_ABS_PATH, 'config')
CASE_CONFIG_PATH = os.path.join(CONFIG_DIR_PATH, 'case_config.py')
FAVICON_PATH = os.path.join(PROJECT_ABS_PATH, "resources", "favicon.ico")

class PROJECT_CLEAN(object):
    data_status             : bool = True
    report_status           : bool = True
    allure_report_status    : bool = True