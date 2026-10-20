# -*- coding: utf-8 -*-
"""
定时调度器模块 —— APScheduler 轻量封装（纯新增，不改动现有测试逻辑）。

- 调度引擎：APScheduler 3.x BackgroundScheduler，cron 表达式精确到秒
- 执行方式：subprocess 调用 run_testcases.py（或自定义命令），与主流程完全解耦
- 总开关：api_project/.env 中 SCHEDULER_ENABLED=true/false（默认 false）
- 任务开关：api_project/config/scheduler_jobs.json 中每个任务 enabled
"""
from .scheduler_core import (
    DEFAULT_JOBS_FILE,
    build_scheduler,
    load_jobs,
    run_scheduler,
)

__all__ = ["load_jobs", "build_scheduler", "run_scheduler", "DEFAULT_JOBS_FILE"]
