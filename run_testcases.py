#! /usr/bin/env python
'''
Auther      : Alvin.zeng
Email       : zengjiangtaoasd@qq.com
createTime  : 2024/11/18 23:28
fileName    : run_testcases.py
Description : 测试入口脚本 — 运行 pytest + 后置报告任务

环境变量配置（JAVA_HOME / Allure）已迁移至根目录 conftest.py（pytest_configure 钩子自动执行）。
报告生成/压缩/清理/邮件通知逻辑已迁移至 api_project/common/report_manager.py。

按模块/接口筛选运行：
  - 终端: set RUN_MODULE=查询模块
  - 代码: 修改 api_project/testcases/conftest.py 中 RUN_MODULE_CONFIG 变量
  - 查看: set RUN_MODULE=list

执行耗时观测：
  - 测试完成后输出 pytest 阶段、报告/通知阶段及全流程耗时
  - 不改变既有的串行执行、请求超时、报告和通知行为
'''
import os
import sys
import time
import pytest

from api_project import CASE_SCRIPT_DIR_PATH, DATA_DIR_PATH, REPORT_DIR_PATH
from api_project.common import init
from api_project.common.LOG import Logger
from api_project.common.report_manager import run_post_test_tasks

logger = Logger()

# 未显式配置时才使用默认执行人，避免覆盖 CI 或 .env 中的值。
os.environ.setdefault("TEST_EXECUTOR", "曾超群")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


if __name__ == '__main__':
    init()

    # 构建 custom.css 的绝对路径
    custom_css_path = os.path.join(os.path.dirname(__file__), 'api_project', 'config', 'custom.css')
    print(f"CSS 文件路径: {custom_css_path}")
    print(f"文件是否存在: {os.path.exists(custom_css_path)}")

    # 运行测试（模块/接口筛选由 testcases/conftest.py 中的 RUN_MODULE 处理）。
    # 保持原有串行执行；当前参数化用例共享进程内变量，且报告插件未兼容 xdist。
    pytest_args = [
        CASE_SCRIPT_DIR_PATH,
        '-v',
        '-s',
        '--litereport',
        f'--alluredir={DATA_DIR_PATH}',
        '--clean-alluredir',
        '--cache-clear',
        # pytest-html-plus uses an output directory rather than pytest-html's
        # --html/--self-contained-html/--css options.
        f'--html-output={REPORT_DIR_PATH}',
    ]
    # 透传 pytest 参数，例如：python run_testcases.py --api-host https://test.example.com
    pytest_args.extend(sys.argv[1:])

    test_started_at = time.perf_counter()
    pytest_exit_code = pytest.main(pytest_args)
    test_duration = time.perf_counter() - test_started_at
    print(f'耗时统计：pytest 测试阶段 {test_duration:.2f}s（退出码：{pytest_exit_code}）')

    # 后置任务：Allure 服务 + 报告压缩 + 清理 + 邮件
    post_started_at = time.perf_counter()
    post_failed = False
    try:
        run_post_test_tasks()
    except Exception as exc:
        post_failed = True
        logger.error(f"报告与通知后置任务失败: {exc}")
    post_duration = time.perf_counter() - post_started_at
    print(f'耗时统计：报告与通知阶段 {post_duration:.2f}s；全流程 {test_duration + post_duration:.2f}s')
    # 将测试或后置任务失败可靠传递给 CI/Jenkins。
    raise SystemExit(pytest_exit_code if pytest_exit_code else (1 if post_failed else 0))




























#------------------------------------------备份-----------------------------------------------

"""
import os
import sys
import pytest

from api_project import CASE_SCRIPT_DIR_PATH, DATA_DIR_PATH, REPORT_DIR_PATH
from api_project.common import init
from api_project.common.LOG import Logger
from api_project.common.report_manager import run_post_test_tasks

logger = Logger()

# 飞书执行人配置
os.environ["TEST_EXECUTOR"] = "曾超群"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


if __name__ == '__main__':
    init()

    # 构建 custom.css 的绝对路径
    custom_css_path = os.path.join(os.path.dirname(__file__), 'api_project', 'config', 'custom.css')
    print(f"CSS 文件路径: {custom_css_path}")
    print(f"文件是否存在: {os.path.exists(custom_css_path)}")

    # 运行测试（模块/接口筛选由 testcases/conftest.py 中的 RUN_MODULE 处理）
    pytest.main([
        CASE_SCRIPT_DIR_PATH,
        '-v',
        '-s',
        '--litereport',
        f'--alluredir={DATA_DIR_PATH}',
        '--clean-alluredir',
        '--cache-clear',
        f'--html-output={REPORT_DIR_PATH}',
    ])

    # 后置任务：Allure 服务 + 报告压缩 + 清理 + 邮件
    run_post_test_tasks()



# 按模块筛选

#RUN_MODULE_CONFIG = ""
#SET RUN_MODULE=订单模块
#python run_testcases.py

# 多个一起
#SET RUN_MODULE=订单模块,用户模块
#python run_testcases.py
"""
