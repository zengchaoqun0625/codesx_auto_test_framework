#! /usr/bin/env python
# -*- coding: utf-8 -*-
'''
Auther      : Alvin.zeng
createTime  : 2026/08/12
fileName    : run_scheduler.py
Description : 定时调度器入口 —— 基于 APScheduler 定时执行 run_testcases.py
              纯新增模块，不改动现有测试逻辑（run_testcases.py / conftest.py 等一律不动）。

用法（项目根目录执行）：
  python run_scheduler.py            启动调度器（需 .env 中 SCHEDULER_ENABLED=true）
  python run_scheduler.py --dry-run  仅打印任务配置，不启动（验证用）
  python run_scheduler.py --force    忽略 SCHEDULER_ENABLED 开关，强制启动
  python run_scheduler.py --jobs xxx.json  指定任务配置文件

开关控制：
  - 总开关：api_project/.env 中 SCHEDULER_ENABLED=true/false（默认 false）
  - 任务开关：api_project/config/scheduler_jobs.json 中每个任务 enabled
  - 任务级环境变量（RUN_MODULE / TEST_EXECUTOR 等）在 jobs 的 env 字段中配置

Windows 开机自启（任务计划程序，管理员 PowerShell）：
  schtasks /Create /TN "ApiAutoScheduler" /TR "pythonw run_scheduler.py" /SC ONLOGON /RL HIGHEST /F
  注意：/TR 中 pythonw 需为绝对路径，且需指定工作目录或 cd 到项目根目录
'''
import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from api_project.common.ENV import ENV  # noqa: E402
from api_project.common.settings import get_bool_env  # noqa: E402

ENV.load()  # 加载 api_project/.env（SCHEDULER_ENABLED / 通知渠道等配置）

from api_project.scheduler import run_scheduler  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="API 自动化测试定时调度器")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印任务配置，不启动调度器")
    parser.add_argument("--force", action="store_true",
                        help="忽略 SCHEDULER_ENABLED 开关，强制启动")
    parser.add_argument("--jobs", default=None,
                        help="任务配置文件路径（默认 api_project/config/scheduler_jobs.json）")
    args = parser.parse_args()

    if not args.dry_run and not args.force:
        raw = os.getenv("SCHEDULER_ENABLED", "false")
        enabled = get_bool_env("SCHEDULER_ENABLED", default=False)
        if not enabled:
            print("=" * 60)
            print("调度器未启用：.env 中 SCHEDULER_ENABLED 当前值 = %r" % raw)
            print("  临时启动一次：   python run_scheduler.py --force")
            print("  长期开启：       编辑 api_project/.env 设置 SCHEDULER_ENABLED=true")
            print("=" * 60)
            return 0

    return run_scheduler(jobs_file=args.jobs, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
