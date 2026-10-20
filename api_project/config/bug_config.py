#! /usr/bin/env python
'''
Auther      : alvin.zeng
Email       : zengjiangataoasd@qq.com
createTime  : 2025/08/05 9:28
fileName    : bug_config.py
'''
'''
支持禅道和JIRA
'''

class BUG_Config(object):
    Bug_Service_Name    : str = '' # 不写为不提交BUG单 or 'zentao' or '禅道' or 'jira' or 'JIRA'
    Bug_fix_table       : dict= dict() # 格式：{'username1': ['api_name1', 'api_name2'], 'username2': ['all']}

class ZenTao_Config(object):
    baseURL             : str = ''  # 禅道的基础路径/api之前的url部分
    account             : str = ''  # 禅道登录的账户名
    key                 : str = ''  # 后台>>二次开发>>应用>>创建>>密钥
    code                : str = ''  # 后台>>二次开发>>应用>>创建>>代号
    assignedTo          : str = ''  # 填写则是唯一指派人员；为空时参考指派关系（assigned_relation）
    # 指派者账户与接口关系
    assigned_relation   : dict= BUG_Config.Bug_fix_table
    mailto              : str = ''  # 抄送者账户,分割

class JIRA_Config(object):
    server_url          : str = ''  # Jira的基础Url
    username            : str = ''  # Jira登录的用户名
    password            : str = ''  # Jira登录账户的密码
    assignee            : str = ''  # 填写则是唯一指派人员；为空时参考指派关系（assignee_relation）
    # 指派者账户与接口关系
    assignee_relation   : dict = BUG_Config.Bug_fix_table

