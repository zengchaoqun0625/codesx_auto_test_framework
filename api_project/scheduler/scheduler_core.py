# -*- coding: utf-8 -*-
"""
调度器核心 —— APScheduler 轻量封装（纯新增，不改动现有测试逻辑）。

设计要点：
1. 执行方式：subprocess 调用 run_testcases.py（或自定义命令），
   run_testcases.py 的入口逻辑（init -> pytest.main -> run_post_test_tasks）一行不改。
2. 任务配置：api_project/config/scheduler_jobs.json（cron 表达式 + 可选环境变量覆盖）。
3. 开关控制：.env 的 SCHEDULER_ENABLED（总开关，见 run_scheduler.py）+ 每个任务 enabled。
4. 日志：api_project/log/scheduler.log（滚动 2MB x 5），同时输出到控制台。
5. 防重入：max_instances=1 + coalesce=True，同一任务上一个实例未结束时跳过本次触发。
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from api_project.common.settings import get_bool_env

# ---------- 路径常量 ----------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent   # 项目根目录（含 run_testcases.py）
API_PROJECT_DIR = PROJECT_ROOT / "api_project"
RUN_ENTRY = PROJECT_ROOT / "run_testcases.py"
DEFAULT_JOBS_FILE = API_PROJECT_DIR / "config" / "scheduler_jobs.json"
LOG_FILE = API_PROJECT_DIR / "log" / "scheduler.log"
DEFAULT_TZ = "Asia/Shanghai"


def _logger():
    """调度器专用 logger：控制台 + 滚动文件，避免污染框架日志"""
    logger = logging.getLogger("api_scheduler")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024,
                                     backupCount=5, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            pass  # 日志文件不可用时仅控制台输出
        logger.propagate = False
    return logger


def load_jobs(jobs_file=None):
    """读取任务配置文件，校验 cron 语法，返回 {"timezone": str, "jobs": [job, ...]}"""
    logger = _logger()
    path = Path(jobs_file) if jobs_file else DEFAULT_JOBS_FILE
    if not path.exists():
        logger.warning(f"任务配置文件不存在: {path}")
        return {"timezone": DEFAULT_TZ, "jobs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"任务配置文件解析失败: {e}")
        return {"timezone": DEFAULT_TZ, "jobs": []}

    tz = data.get("timezone") or DEFAULT_TZ
    jobs = []
    for j in data.get("jobs", []):
        name = j.get("name") or j.get("id") or "未命名任务"
        cron = j.get("cron")
        if not cron:
            logger.warning(f"[{name}] 缺少 cron 表达式，跳过")
            continue
        try:
            CronTrigger.from_crontab(cron, timezone=tz)  # 提前校验语法
        except Exception as e:
            logger.warning(f"[{name}] cron 表达式无效({cron}): {e}，跳过")
            continue
        jobs.append({
            "name": name,
            "cron": cron,
            "enabled": _as_bool(j.get("enabled", True)),
            "command": (j.get("command") or "").strip(),
            "env": {str(k): str(v) for k, v in (j.get("env") or {}).items()},
            "timeout_sec": int(j.get("timeout_sec") or 0) or None,
            "description": j.get("description", ""),
        })
    return {"timezone": tz, "jobs": jobs}


def _as_bool(value):
    """Parse JSON/environment-style booleans without treating 'false' as true."""
    if isinstance(value, bool):
        return value
    return get_bool_env("SCHEDULER_JOB_ENABLED", default=True, environ={"SCHEDULER_JOB_ENABLED": value})


def _resolve_script(cmd):
    """把相对/绝对脚本路径解析为项目内绝对路径；非 .py 命令原样返回"""
    if cmd.lower().endswith(".py"):
        p = Path(cmd)
        return str(p if p.is_absolute() else PROJECT_ROOT / p)
    return cmd


def _run_command(job):
    """执行任务命令：
    - .py 脚本 → 用当前解释器直连执行（不依赖 PATH，Windows 下不弹黑窗口）
    - 其他（.bat/.cmd/任意命令）→ shell 执行
    """
    logger = _logger()
    name = job["name"]
    cmd = job["command"] or "run_testcases.py"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(job["env"])

    kwargs = dict(cwd=str(PROJECT_ROOT), env=env, capture_output=True,
                  text=True, encoding="utf-8", errors="replace")
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    start = time.time()
    try:
        if cmd.lower().endswith(".py"):
            proc = subprocess.run([sys.executable, _resolve_script(cmd)],
                                  timeout=job["timeout_sec"], **kwargs)
        else:
            proc = subprocess.run(cmd, shell=True, timeout=job["timeout_sec"], **kwargs)
        elapsed = time.time() - start
        if proc.returncode == 0:
            logger.info(f"✔ 任务完成 [{name}] 耗时 {elapsed:.1f}s 退出码 0")
        else:
            tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-2500:]
            logger.error(f"✘ 任务失败 [{name}] 耗时 {elapsed:.1f}s 退出码 {proc.returncode}\n{tail}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        logger.error(f"⏱ 任务超时 [{name}] 超过 {job['timeout_sec']}s，已强制终止")
        return -1
    except Exception as e:
        logger.exception(f"!! 任务执行异常 [{name}]: {e}")
        return -1


def run_job(job):
    """APScheduler 触发回调：执行单个任务"""
    logger = _logger()
    name = job["name"]
    cmd = job["command"] or "run_testcases.py"
    logger.info(f"▶ 任务开始 [{name}] cron={job['cron']} cmd={cmd}"
                + (f" env={job['env']}" if job["env"] else ""))
    try:
        return _run_command(job)
    except Exception as e:
        logger.exception(f"!! 任务回调异常 [{name}]: {e}")
        return -1


def build_scheduler(config):
    """构建 BackgroundScheduler 并注册所有启用的任务"""
    logger = _logger()
    tz = config["timezone"]
    enabled = [j for j in config["jobs"] if j["enabled"]]
    disabled = [j for j in config["jobs"] if not j["enabled"]]

    sched = BackgroundScheduler(timezone=tz)
    for j in enabled:
        sched.add_job(
            run_job,
            CronTrigger.from_crontab(j["cron"], timezone=tz),
            args=[j],
            id=j["name"], name=j["name"],
            replace_existing=True,
            max_instances=1,       # 同一任务同时只跑一个实例
            coalesce=True,         # 错过的触发合并为一次
            misfire_grace_time=1800,
        )
        desc = f" · {j['description']}" if j["description"] else ""
        logger.info(f"已注册任务 [{j['name']}] cron={j['cron']}{desc}")
    for j in disabled:
        logger.info(f"任务已禁用(跳过) [{j['name']}] cron={j['cron']}")

    logger.info(f"调度器就绪：启用 {len(enabled)} / 共 {len(config['jobs'])} 个任务，时区 {tz}")
    return sched


def run_scheduler(jobs_file=None, dry_run=False):
    """启动调度器常驻运行；dry_run=True 仅预览任务配置不启动"""
    logger = _logger()
    config = load_jobs(jobs_file)
    if not config["jobs"]:
        logger.warning("没有可用的任务配置，调度器退出。请检查 scheduler_jobs.json")
        return 1
    if not any(job["enabled"] for job in config["jobs"]):
        logger.warning("没有启用的任务，调度器退出。请将至少一个任务的 enabled 设为 true")
        return 0

    logger.info("=" * 60)
    logger.info("任务清单预览")
    logger.info("=" * 60)
    for j in config["jobs"]:
        state = "启用" if j["enabled"] else "禁用"
        logger.info(f"  [{state}] {j['name']:<18} cron={j['cron']:<16} "
                    f"cmd={j['command'] or 'run_testcases.py'}")
    if dry_run:
        logger.info("--dry-run：仅预览任务，未启动调度器")
        return 0

    sched = build_scheduler(config)
    sched.start()
    logger.info("调度器已启动，按 Ctrl+C 停止")
    try:
        threading.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到停止信号，正在关闭调度器...")
    finally:
        sched.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(run_scheduler(dry_run=True))
