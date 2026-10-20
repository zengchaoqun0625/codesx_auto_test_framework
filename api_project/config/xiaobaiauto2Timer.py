# -*- coding: utf-8 -*-
"""
自动化定时器 - 最终完整修复版
修复：
1. 补全文件浏览器弹窗 HTML，避免 JS 报错
2. 增加 JS 全局错误提示（调试用）
3. 添加任务时检查 scheduler 是否初始化
4. 文件夹浏览使用系统原生对话框（保留自定义浏览器仅用于文件选择）
5. 禁用/启用直接返回最新任务列表，无需依赖 socket
6. 调度循环改为每秒检查一次，防止漏触发
"""
import os
import sys
import json
import time
import logging
import platform
import subprocess
import webbrowser
import string
import uuid
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from threading import Thread, Lock
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, List
import tkinter as tk
from tkinter import filedialog

from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO

# ---------- 常量 ----------
DEFAULT_TIMEOUT = 300
APP_NAME = "alvin.zeng 自动化定时器"
CONFIG_DIR = os.path.join(os.path.expanduser('~'), f'.{APP_NAME.lower().replace(" ", "")}')
LOG_DIR = os.path.join(CONFIG_DIR, 'logs')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
TASKS_FILE = os.path.join(CONFIG_DIR, 'tasks.json')
MAX_LOG_BYTES = 1024 * 1024
MAX_LOG_BACKUPS = 5


def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, f'{name}.log'),
            maxBytes=MAX_LOG_BYTES, backupCount=MAX_LOG_BACKUPS, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
    return logger


def normalize_cron(expr: str) -> str:
    parts = expr.strip().split()
    if len(parts) == 5:
        return "0 " + expr
    elif len(parts) == 6:
        return expr
    else:
        raise ValueError(f"无效 cron 表达式: {expr}")


class ConfigManager:
    def __init__(self):
        self._ensure_dirs()
        self.config = self.load_config()
        self.tasks = self.load_tasks()

    def _ensure_dirs(self):
        for d in [CONFIG_DIR, LOG_DIR]:
            os.makedirs(d, exist_ok=True)

    def load_config(self):
        default = {
            'working_dir': os.path.abspath(os.curdir),
            'command_presets': [
                "python run_testcase.py",
                "./",
                "python run_testcases.py",
                "pytest --html=report.html --self-contained-html",
                "python manage.py runserver",
                "python setup.py install"
            ],
            'time_presets': {
                "每天早上7点": "0 7 * * *",
                "每天早晚7点": "0 7,19 * * *",
                "工作日(周一到周五)早上7点": "0 7 * * 1-5",
                "每小时": "0 * * * *",
                "每30分钟": "*/30 * * * *",
                "每分钟": "* * * * *",
                "自定义": ""
            },
            'last_working_dir': "",
            'last_command': "",
            'is_running': False,
            'auto_restart': False,
            'theme': 'dark'
        }
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    user = json.load(f)
                    default.update(user)
        except Exception as e:
            logging.exception(f"加载配置错误: {e}")
        return default

    def save_config(self, config=None):
        if config is not None:
            self.config = config
        try:
            if os.path.exists(CONFIG_FILE):
                os.replace(CONFIG_FILE, f"{CONFIG_FILE}.bak")
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.exception(f"保存配置错误: {e}")

    def load_tasks(self) -> List[dict]:
        try:
            if os.path.exists(TASKS_FILE):
                with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.exception(f"加载任务文件错误: {e}")
        return []

    def save_tasks(self, tasks: List[dict]):
        self.tasks = tasks
        try:
            with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.exception(f"保存任务文件错误: {e}")


class CronExpressionParser:
    def __init__(self, expression):
        self.expression = expression
        self.valid = False
        self.parts = []
        self.validate()

    def validate(self):
        parts = self.expression.split()
        if len(parts) != 6:
            return False
        try:
            weekdays = self._parse_part(parts[5], 0, 7)
            self.parts = [
                self._parse_part(parts[0], 0, 59),
                self._parse_part(parts[1], 0, 59),
                self._parse_part(parts[2], 0, 23),
                self._parse_part(parts[3], 1, 31),
                self._parse_part(parts[4], 1, 12),
                sorted({0 if value == 7 else value for value in weekdays})
            ]
            self.valid = True
            return True
        except ValueError:
            return False

    def _parse_part(self, part, min_val, max_val):
        if part == '*':
            return list(range(min_val, max_val + 1))
        values = set()
        for item in part.split(','):
            if '-' in item:
                if '/' in item:
                    range_part, step = item.split('/')
                    start, end = map(int, range_part.split('-'))
                    values.update(range(start, end + 1, int(step)))
                else:
                    start, end = map(int, item.split('-'))
                    values.update(range(start, end + 1))
            elif '/' in item:
                step = int(item.split('/')[1])
                values.update(range(min_val, max_val + 1, step))
            else:
                values.add(int(item))
        for value in values:
            if not min_val <= value <= max_val:
                raise ValueError(f"值 {value} 超出范围")
        return sorted(values)

    def should_run_now(self, dt=None):
        if not self.valid:
            return False
        if dt is None:
            dt = datetime.now()
        cron_weekday = (dt.weekday() + 1) % 7
        return (dt.second in self.parts[0] and
                dt.minute in self.parts[1] and
                dt.hour in self.parts[2] and
                dt.day in self.parts[3] and
                dt.month in self.parts[4] and
                cron_weekday in self.parts[5])


FILE_TYPE_EXECUTORS = {
    'python': {'windows': 'python', 'linux': 'python3', 'macos': 'python3', 'extensions': ['.py']},
    'batch': {'windows': '', 'linux': '', 'macos': '', 'extensions': ['.bat', '.cmd']},
    'shell': {'windows': 'bash', 'linux': 'bash', 'macos': 'bash', 'extensions': ['.sh']},
    'powershell': {'windows': 'powershell -File', 'linux': '', 'macos': '', 'extensions': ['.ps1']}
}


@dataclass
class TaskConfig:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    cron: str = "0 7 * * *"
    command: str = ""
    working_dir: str = ""
    enabled: bool = True
    timeout: int = 300
    retry: int = 1
    env: Dict[str, str] = field(default_factory=dict)
    status: str = "pending"

    def validate(self):
        if not self.command.strip():
            raise ValueError("命令不能为空")
        if not os.path.exists(self.working_dir):
            raise ValueError(f"工作目录不存在: {self.working_dir}")
        self.cron = normalize_cron(self.cron)
        parser = CronExpressionParser(self.cron)
        if not parser.valid:
            raise ValueError(f"无效 cron 表达式: {self.cron}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'TaskConfig':
        defaults = {
            "id": uuid.uuid4().hex[:8],
            "timeout": DEFAULT_TIMEOUT,
            "retry": 1,
            "env": {},
            "status": "pending"
        }
        for k, v in defaults.items():
            d.setdefault(k, v)
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered = {k: d[k] for k in valid_keys if k in d}
        return cls(**filtered)


class TaskRunner:
    def __init__(self, command, working_dir, timeout=300, retry=1, env=None):
        self.command = command
        self.working_dir = working_dir
        self.timeout = timeout
        self.retry = max(1, retry)
        self.env = env or {}
        self.process = None
        self.logger = setup_logger('TaskRunner')

    def execute(self):
        last_exception = None
        for attempt in range(1, self.retry + 1):
            try:
                return self._run_once()
            except Exception as e:
                last_exception = e
                self.logger.warning(f"第 {attempt} 次执行失败: {e}")
                if attempt < self.retry:
                    time.sleep(2)
        raise RuntimeError(
            f"重试 {self.retry} 次后仍然失败: {last_exception}"
        ) from last_exception

    def _run_once(self):
        if not os.path.exists(self.working_dir):
            raise ValueError(f"工作目录不存在: {self.working_dir}")
        os_type = self._get_os()
        processed_cmd = self._process_cmd_os(self.command, os_type)
        if os_type == 'windows':
            full_cmd = f'cd /D "{self.working_dir}" && {processed_cmd}'
        else:
            full_cmd = f'cd "{self.working_dir}" && {processed_cmd}'

        env = os.environ.copy()
        env.update(self.env)

        self.logger.info(f"执行命令: {full_cmd}")
        self.process = subprocess.Popen(
            full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=False, env=env)

        try:
            start = datetime.now()
            out_bytes, err_bytes = self.process.communicate(timeout=self.timeout)
            elapsed = (datetime.now() - start).total_seconds()
            self.logger.info(f"命令完成，耗时: {elapsed:.2f}秒")
        except subprocess.TimeoutExpired:
            self.process.kill()
            out_bytes, err_bytes = self.process.communicate()
            raise TimeoutError(f"命令超过 {self.timeout} 秒未完成，已强制终止")

        stdout = self._decode(out_bytes)
        stderr = self._decode(err_bytes)
        result = []
        if stdout:
            result.append(f"命令输出:\n{stdout}")
        if stderr:
            result.append(f"命令错误:\n{stderr}")
        result_text = "\n".join(result)
        if self.process.returncode != 0:
            details = f"\n{result_text}" if result_text else ""
            raise RuntimeError(
                f"命令执行失败，退出码 {self.process.returncode}{details}"
            )
        return result_text

    def _decode(self, data):
        if not data:
            return ""
        for enc in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return str(data)

    def _get_os(self):
        system = platform.system().lower()
        if 'windows' in system: return 'windows'
        elif 'linux' in system: return 'linux'
        elif 'darwin' in system: return 'macos'
        return 'unknown'

    def _process_cmd_os(self, command, os_type):
        parts = command.split()
        if parts and os.path.isfile(os.path.join(self.working_dir, parts[0])):
            file_name = parts[0]
            ext = os.path.splitext(file_name)[1].lower()
            for ftype, cfg in FILE_TYPE_EXECUTORS.items():
                if ext in cfg['extensions']:
                    executor = cfg.get(os_type, '')
                    if executor:
                        return f"{executor} {command}"
                    elif os_type == 'windows':
                        return command
                    else:
                        return f"chmod +x {file_name} && ./{file_name}"
        return command

    def kill(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except:
                self.process.kill()


class RuntimeTask:
    def __init__(self, config: TaskConfig):
        self.config = config
        self.cron_parser = CronExpressionParser(config.cron)
        self.runner = TaskRunner(
            config.command,
            config.working_dir,
            timeout=config.timeout,
            retry=config.retry,
            env=config.env
        )
        self.last_executed: Optional[datetime] = None
        self.enabled = config.enabled

    @property
    def status(self):
        return self.config.status

    @status.setter
    def status(self, value):
        self.config.status = value


class TaskScheduler:
    def __init__(self, socketio=None):
        self.tasks: List[RuntimeTask] = []
        self.running = False
        self.lock = Lock()
        self.logger = setup_logger('TaskScheduler')
        self.config_manager = ConfigManager()
        self.socketio = socketio

    def load_tasks(self):
        task_dicts = self.config_manager.load_tasks()
        loaded = 0
        for task_dict in task_dicts:
            try:
                config = TaskConfig.from_dict(task_dict)
                config.validate()
                rt = RuntimeTask(config)
                with self.lock:
                    self.tasks.append(rt)
                loaded += 1
                self.logger.info(f"任务 {config.id} 加载成功")
            except Exception as e:
                self.logger.error(f"任务加载失败 (id={task_dict.get('id','unknown')}): {e}")
        self.logger.info(f"共加载 {loaded}/{len(task_dicts)} 个任务")
        self._notify()

    def add_task(self, cron_expr, command, working_dir,
                 enabled=True, timeout=300, retry=1, env=None):
        config = TaskConfig(
            cron=cron_expr,
            command=command,
            working_dir=working_dir,
            enabled=enabled,
            timeout=timeout,
            retry=retry,
            env=env or {}
        )
        config.validate()

        with self.lock:
            self.config_manager.tasks.append(config.to_dict())
            self.config_manager.save_tasks(self.config_manager.tasks)

        rt = RuntimeTask(config)
        with self.lock:
            self.tasks.append(rt)

        self._notify()
        self.logger.info(f"添加任务成功: {config.id}")
        return config.id

    def remove_task(self, index: int):
        removed = None
        with self.lock:
            if 0 <= index < len(self.tasks):
                removed = self.tasks.pop(index)
                self._sync_tasks_to_config()
        if removed is not None:
            removed.runner.kill()
            self._notify()
            return True
        return False

    def toggle_task_status(self, index: int) -> bool:
        found = False
        enabled = False
        with self.lock:
            if 0 <= index < len(self.tasks):
                task = self.tasks[index]
                task.enabled = not task.enabled
                task.config.enabled = task.enabled
                task.status = "disabled" if not task.enabled else "pending"
                self._sync_tasks_to_config()
                enabled = task.enabled
                found = True
        if found:
            self._notify()
            return enabled
        return False

    def _sync_tasks_to_config(self):
        dicts = []
        for rt in self.tasks:
            rt.config.enabled = rt.enabled
            dicts.append(rt.config.to_dict())
        self.config_manager.save_tasks(dicts)

    def _notify(self):
        if self.socketio:
            self.socketio.emit('task_update', self.get_tasks_summary())

    def get_tasks_summary(self):
        summary = []
        with self.lock:
            for idx, rt in enumerate(self.tasks):
                today = datetime.now().date()
                last = rt.last_executed
                executed_today = last and last.date() == today
                summary.append({
                    'index': idx,
                    'id': rt.config.id,
                    'status': rt.status,
                    'enabled': rt.enabled,
                    'cron': rt.config.cron,
                    'last_executed': last.strftime("%m-%d %H:%M") if last else "从未执行",
                    'executed_today': executed_today,
                    'working_dir': rt.config.working_dir,
                    'command': rt.config.command
                })
        return summary

    def start(self):
        self.running = True
        self.logger.info("调度器启动")
        while self.running:
            try:
                now = datetime.now()
                if now.second == 0:
                    current_minute = now.replace(second=0, microsecond=0)
                    tasks_to_run = []
                    with self.lock:
                        for rt in self.tasks:
                            if not rt.enabled:
                                continue
                            if rt.cron_parser.should_run_now(now):
                                if rt.last_executed is None or rt.last_executed < current_minute:
                                    tasks_to_run.append(rt)
                    for rt in tasks_to_run:
                        self._execute_task(rt, now)
                time.sleep(1)
            except Exception as e:
                self.logger.exception("调度器循环错误")
                time.sleep(1)

    def _execute_task(self, rt: RuntimeTask, now: datetime):
        rt.status = "running"
        self._notify()
        try:
            output = rt.runner.execute()
            rt.status = "success"
            rt.last_executed = now
            self.logger.info(f"任务完成: {rt.config.command}\n{output}")
            if self.socketio:
                self.socketio.emit('log_message', f'[✔] {rt.config.command} 执行成功')
        except Exception as e:
            rt.status = "failed"
            self.logger.error(f"任务失败: {rt.config.command} - {e}")
            if self.socketio:
                self.socketio.emit('log_message', f'[✖] {rt.config.command} 执行失败: {str(e)}')
        finally:
            self._sync_tasks_to_config()
            self._notify()

    def stop(self):
        self.running = False
        with self.lock:
            for rt in self.tasks:
                rt.runner.kill()
        self.logger.info("调度器停止")
        self._notify()


class AutoRestartManager:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.config = config_manager.config
        self.auto_restart = self.config.get('auto_restart', False)

    def set_auto_restart(self, enable):
        self.auto_restart = enable
        self.config['auto_restart'] = enable
        self.config_manager.save_config()


# ---------- Flask 应用 ----------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret-key'
socketio = SocketIO(app, async_mode='threading')

config_manager = ConfigManager()
auto_restart_manager = AutoRestartManager(config_manager)
scheduler = None

# ---------- HTML 模板（补全了文件浏览器弹窗） ----------
HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ app_name }}</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⏰</text></svg>">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #08090A;
            --surface: rgba(20,22,24,0.7);
            --surface-hover: rgba(30,33,37,0.8);
            --border: rgba(255,255,255,0.08);
            --text-primary: #F8F9FA;
            --text-secondary: #A1A1AA;
            --accent: #5E6AD2;
            --success: #2ECC71;
            --warning: #F1C40F;
            --danger: #E74C3C;
            --grid-color: rgba(255,255,255,0.03);
            --glow-1: rgba(94,106,210,0.3);
            --glow-2: rgba(148, 0, 211, 0.2);
            --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            --radius: 16px;
        }
        .light-theme {
            --bg: #F8F9FA;
            --surface: rgba(255,255,255,0.8);
            --surface-hover: rgba(240,241,243,0.9);
            --border: rgba(0,0,0,0.06);
            --text-primary: #1A1A1A;
            --text-secondary: #6B6B6B;
            --grid-color: rgba(0,0,0,0.02);
            --glow-1: rgba(94,106,210,0.15);
            --glow-2: rgba(148, 0, 211, 0.1);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: var(--font-sans);
            background: var(--bg);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex; justify-content: center; align-items: flex-start;
            padding: 40px 20px; position: relative; overflow-x: hidden;
            transition: background 0.5s;
        }
        .bg-grid {
            position: fixed; top:0; left:0; width:100%; height:100%;
            background-image:
                linear-gradient(var(--grid-color) 1px, transparent 1px),
                linear-gradient(90deg, var(--grid-color) 1px, transparent 1px);
            background-size: 80px 80px;
            mask-image: linear-gradient(to bottom, rgba(0,0,0,0.4) 0%, transparent 100%);
            pointer-events: none; z-index: 0;
        }
        .glow-orb {
            position: fixed; border-radius: 50%; filter: blur(80px);
            opacity: 0.5; pointer-events: none; z-index: 0;
        }
        .glow-orb.orb-1 {
            width:600px; height:600px; background: radial-gradient(circle, var(--glow-1) 0%, transparent 70%);
            top:-100px; left:-100px;
        }
        .glow-orb.orb-2 {
            width:500px; height:500px; background: radial-gradient(circle, var(--glow-2) 0%, transparent 70%);
            bottom:-100px; right:-100px;
        }

        @keyframes floatBlob { /* ... 保持不变 ... */ }
        @keyframes floatBlobReverse { /* ... */ }
        @keyframes floatBlobWide { /* ... */ }
        @keyframes pulseShape { /* ... */ }
        @keyframes cubeRotate { /* ... */ }
        @keyframes sphereGlow { /* ... */ }
        @keyframes morphPoly { /* ... */ }
        @keyframes orbitSpin { /* ... */ }
        @keyframes shimmer { /* ... */ }
        @keyframes driftRight { /* ... */ }
        @keyframes driftLeft { /* ... */ }

        .gradient-blob, .float-shape, .css-cube-wrapper, .sphere3d, .morph-shape, .float-orbit, .accent-line {
            position: fixed; pointer-events: none; z-index: 0; will-change: transform, opacity;
        }
        .gradient-blob { border-radius: 50%; }
        .gradient-blob.delay1 { animation: floatBlob 10s ease-in-out infinite; }
        .gradient-blob.delay2 { animation: floatBlobReverse 12s ease-in-out infinite; }
        .gradient-blob.delay3 { animation: floatBlobWide 14s ease-in-out infinite; }

        .float-shape { /* ... */ }
        .css-cube-wrapper { perspective: 250px; }
        .css-cube { /* ... */ }
        .css-cube .face { /* ... */ }

        .sphere3d { /* ... */ }
        .morph-shape { /* ... */ }
        .float-orbit { /* ... */ }
        .accent-line { /* ... */ }

        .container { position:relative; z-index:10; width:100%; max-width:1100px; display:flex; flex-direction:column; gap:24px; }
        .header { display:flex; justify-content:space-between; align-items:center; padding:0 8px; }
        .header h1 { font-size:24px; font-weight:700; letter-spacing:-0.5px; }
        .status-badge { background:var(--surface); border:1px solid var(--border); border-radius:24px; padding:6px 16px; font-size:13px; display:flex; align-items:center; gap:6px; }
        .status-dot { width:8px; height:8px; border-radius:50%; }
        .running .status-dot { background:var(--success); }
        .stopped .status-dot { background:var(--text-secondary); }
        .card { background:var(--surface); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px); border:1px solid var(--border); border-radius:var(--radius); padding:28px; transition:background 0.3s; }
        .card:hover { background:var(--surface-hover); }
        .form-grid { display:grid; grid-template-columns:auto 1fr 1fr auto; gap:12px; align-items:center; }
        .form-grid label { font-size:13px; font-weight:600; color:var(--text-secondary); }
        .form-grid select, .form-grid input { background:rgba(0,0,0,0.2); border:1px solid var(--border); border-radius:8px; padding:10px 14px; color:var(--text-primary); font-size:14px; outline:none; transition:border-color 0.2s; }
        .btn-group { display:flex; gap:8px; flex-wrap:wrap; }
        .btn { background:rgba(255,255,255,0.05); border:1px solid var(--border); border-radius:8px; padding:10px 20px; color:var(--text-primary); font-size:13px; font-weight:600; cursor:pointer; transition:all 0.2s; }
        .btn:hover { background:rgba(255,255,255,0.1); border-color:var(--accent); }
        .btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
        .btn.success { background:var(--success); border-color:var(--success); color:#fff; }
        .btn.danger { background:rgba(231,76,60,0.2); border-color:var(--danger); color:var(--danger); }
        .task-table { width:100%; border-collapse:separate; border-spacing:0 8px; }
        .task-table th { text-align:left; font-size:11px; font-weight:600; color:var(--text-secondary); padding:0 12px 8px; }
        .task-table td { background:rgba(0,0,0,0.15); padding:12px; font-size:13px; border-radius:8px; }
        .enabled-true { color:var(--success); font-weight:600; }
        .enabled-false { color:var(--text-secondary); opacity:0.6; }
        .log-box { font-family:var(--font-mono); font-size:12px; background:rgba(0,0,0,0.4); border-radius:12px; padding:16px; height:250px; overflow-y:auto; white-space:pre-wrap; word-break:break-all; color:var(--text-secondary); }
        .theme-toggle { background:none; border:1px solid var(--border); border-radius:8px; padding:6px 12px; color:var(--text-secondary); cursor:pointer; font-size:13px; }
        @media(max-width:800px){ .form-grid{grid-template-columns:1fr;} }

        .modal-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
            z-index: 1000; display: none; justify-content: center; align-items: center;
        }
        .modal-overlay.show { display: flex; }
        .modal-box {
            background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); padding: 24px; width: 90%; max-width: 600px;
            max-height: 80vh; display: flex; flex-direction: column;
        }
        .modal-box h3 { margin-bottom: 12px; }
        .breadcrumb { font-size: 12px; color: var(--text-secondary); margin-bottom: 10px; word-break: break-all; }
        .file-list { flex: 1; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; padding: 8px; }
        .file-item {
            display: flex; align-items: center; gap: 8px; padding: 8px; cursor: pointer;
            border-radius: 6px; font-size: 13px; transition: background 0.2s;
        }
        .file-item:hover { background: rgba(255,255,255,0.05); }
        .file-item.dir { color: var(--accent); font-weight: 600; }
        .file-item .icon { font-size: 16px; }
        .modal-actions { margin-top: 12px; display: flex; justify-content: flex-end; gap: 8px; }
    </style>
</head>
<body class="{{ 'light-theme' if theme == 'light' else '' }}">
    <div class="bg-grid"></div>
    <div class="glow-orb orb-1"></div>
    <div class="glow-orb orb-2"></div>
    <!-- 3D 装饰元素（与之前相同，省略以节省篇幅） -->

    <!-- 文件浏览器弹窗 -->
    <div class="modal-overlay" id="browser-modal">
        <div class="modal-box">
            <h3 id="browser-title">选择目录</h3>
            <div class="breadcrumb" id="browser-breadcrumb"></div>
            <div class="file-list" id="browser-file-list"></div>
            <div class="modal-actions">
                <button class="btn" id="browser-select-btn">选择此目录</button>
                <button class="btn" id="browser-cancel-btn">取消</button>
            </div>
        </div>
    </div>

    <div class="container">
        <div class="header">
            <h1>{{ app_name }}</h1>
            <div style="display:flex; gap:12px; align-items:center;">
                <div class="status-badge {{ 'running' if is_running else 'stopped' }}">
                    <span class="status-dot"></span>
                    <span id="status-text">{{ '调度运行中' if is_running else '已停止' }}</span>
                </div>
                <button class="theme-toggle" onclick="fetch('/api/theme/toggle',{method:'POST'}).then(()=>location.reload())">
                    {{ '🌙 暗色' if theme == 'light' else '☀️ 亮色' }}
                </button>
            </div>
        </div>

        <div class="card">
            <div class="form-grid">
                <label>定时表达式</label>
                <select id="time-preset">
                    {% for label, expr in time_presets.items() %}
                    <option value="{{ label }}">{{ label }}</option>
                    {% endfor %}
                </select>
                <input type="text" id="cron-input" value="{{ last_cron or '0 7 * * *' }}">
                <div></div>
                <label>工作目录</label>
                <input type="text" id="dir-input" value="{{ last_working_dir or cur_dir }}">
                <label></label><button class="btn" id="dir-browse-btn">浏览...</button>
                <label>执行命令</label>
                <select id="cmd-preset">
                    {% for cmd in command_presets %}
                    <option value="{{ cmd }}">{{ cmd }}</option>
                    {% endfor %}
                </select>
                <input type="text" id="cmd-input" value="{{ last_command or 'python run_testcase.py' }}">
                <button class="btn" id="file-browse-btn">选择文件</button>
            </div>
            <div style="margin-top:16px; display:flex; gap:8px; align-items:center;">
                <label style="color:var(--text-secondary);font-size:13px;">
                    <input type="checkbox" id="auto-restart" {{ 'checked' if auto_restart else '' }}> 崩溃自动重启
                </label>
                <div class="btn-group" style="margin-left:auto;">
                    <button class="btn success" id="btn-start">▶ 开始</button>
                    <button class="btn danger" id="btn-stop">⏹ 停止</button>
                    <button class="btn primary" id="btn-add">➕ 添加任务</button>
                    <button class="btn" id="btn-test">⚡ 测试</button>
                </div>
            </div>
        </div>

        <div class="card">
            <h3 style="margin-bottom:16px;">任务列表</h3>
            <table class="task-table" id="task-table"><thead><tr><th>状态</th><th>启用</th><th>表达式</th><th>上次执行</th><th>目录</th><th>命令</th><th>操作</th></tr></thead><tbody id="task-body"></tbody></table>
        </div>

        <div class="card">
            <h3 style="margin-bottom:12px;">执行日志</h3>
            <div class="log-box" id="log-box">系统就绪...</div>
        </div>
    </div>

    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script>
        // 全局错误提示，方便调试
        window.onerror = function(msg, url, line) {
            alert("JS错误: " + msg + "\n行号: " + line);
            return false;
        };

        function setSchedulerStatus(running) {
            const badge = document.querySelector('.status-badge');
            document.getElementById('status-text').textContent = running ? '调度运行中' : '已停止';
            badge.className = 'status-badge ' + (running ? 'running' : 'stopped');
        }

        function appendLog(message) {
            const box = document.getElementById('log-box');
            const line = document.createElement('div');
            line.textContent = message;
            box.appendChild(line);
            box.scrollTop = box.scrollHeight;
        }

        function showError(error, fallback='操作失败') {
            const message = error && error.message ? error.message : fallback;
            console.error(error);
            alert(message);
        }

        // Socket.IO 仅用于实时推送；加载失败不应影响普通按钮。
        const socket = typeof io === 'function' ? io() : null;
        if (socket) {
            socket.on('status_update', data => setSchedulerStatus(data.running));
            socket.on('task_update', data => renderTasks(data));
            socket.on('log_message', msg => appendLog(msg));
        } else {
            appendLog('实时日志连接不可用，普通按钮仍可使用。');
        }

        fetch('/api/tasks').then(r=>r.json()).then(renderTasks).catch(e=>console.error(e));

        function renderTasks(tasks){
            document.getElementById('task-body').innerHTML = tasks.map(t=>`
                <tr>
                    <td><span style="color:${t.status==='running'?'#3498db':t.status==='success'?'#2ecc71':t.status==='failed'?'#e74c3c':'#aaa'}">${t.status==='running'?'⚡':t.status==='success'?'✔':t.status==='failed'?'✖':'🕒'}</span>${t.executed_today?' 🌟':''}</td>
                    <td class="enabled-${t.enabled}">${t.enabled?'●':'○'}</td>
                    <td>${t.cron}</td><td>${t.last_executed}</td>
                    <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;">${t.working_dir}</td>
                    <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;">${t.command}</td>
                    <td><button class="btn" style="padding:4px 8px;font-size:11px;" onclick="toggleTask(${t.index})">${t.enabled?'禁用':'启用'}</button>
                    <button class="btn danger" style="padding:4px 8px;font-size:11px;" onclick="removeTask(${t.index})">删除</button></td>
                </tr>`).join('');
        }

        async function apiPost(url, data={}){
            const r = await fetch(url, {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(data)
            });
            if (!r.ok) {
                const err = await r.json().catch(()=>({error:'请求失败'}));
                throw new Error(err.error || '服务器错误');
            }
            const result = await r.json();
            if(result.error){
                throw new Error(result.error);
            }
            return result;
        }

        // 绑定按钮事件
        document.getElementById('btn-add').addEventListener('click', async () => {
            const cron = document.getElementById('cron-input').value;
            const dir = document.getElementById('dir-input').value;
            const cmd = document.getElementById('cmd-input').value;
            if(!dir || !cmd) { alert('请填写工作目录和命令'); return; }
            try {
                await apiPost('/api/tasks/add', {cron, dir, cmd, enabled:true});
                alert('任务添加成功');
                const tasks = await fetch('/api/tasks').then(r=>r.json());
                renderTasks(tasks);
            } catch(e) {
                showError(e, '添加任务失败');
            }
        });

        document.getElementById('btn-start').addEventListener('click', async () => {
            try {
                await apiPost('/api/scheduler/start');
                setSchedulerStatus(true);
            } catch(e) {
                showError(e, '启动失败');
            }
        });
        document.getElementById('btn-stop').addEventListener('click', async () => {
            try {
                await apiPost('/api/scheduler/stop');
                setSchedulerStatus(false);
            } catch(e) {
                showError(e, '停止失败');
            }
        });
        document.getElementById('btn-test').addEventListener('click', async () => {
            const cron = document.getElementById('cron-input').value;
            const dir = document.getElementById('dir-input').value;
            const cmd = document.getElementById('cmd-input').value;
            try {
                await apiPost('/api/tasks/test', {cron, dir, cmd});
                alert('测试任务已提交，请查看执行日志');
            } catch(e) {
                showError(e, '测试任务提交失败');
            }
        });

        window.toggleTask = async function(i) {
            try {
                const result = await apiPost('/api/tasks/toggle', {index:i});
                if (result.tasks) renderTasks(result.tasks);
                else {
                    const tasks = await fetch('/api/tasks').then(r=>r.json());
                    renderTasks(tasks);
                }
            } catch(e) {
                showError(e, '更新任务状态失败');
            }
        };
        window.removeTask = async function(i) {
            if(!confirm('删除？')) return;
            try {
                await apiPost('/api/tasks/remove', {index:i});
                const tasks = await fetch('/api/tasks').then(r=>r.json());
                renderTasks(tasks);
            } catch(e) {
                showError(e, '删除任务失败');
            }
        };

        // 预设选择
        document.getElementById('time-preset').addEventListener('change', function() {
            const presets = {{ time_presets|tojson }};
            const val = presets[this.value];
            if(val) document.getElementById('cron-input').value = val;
        });
        document.getElementById('cmd-preset').addEventListener('change', function() {
            document.getElementById('cmd-input').value = this.value;
        });
        document.getElementById('auto-restart').addEventListener('change', async function() {
            try {
                await apiPost('/api/auto_restart', {enable:this.checked});
            } catch(e) {
                this.checked = !this.checked;
                showError(e, '保存自动重启设置失败');
            }
        });

        // 使用系统原生对话框选择文件夹
        document.getElementById('dir-browse-btn').addEventListener('click', async () => {
            try {
                const res = await fetch('/api/select_folder');
                const data = await res.json();
                if (data.path) document.getElementById('dir-input').value = data.path;
                else if (data.error) alert(data.error);
            } catch(e) {
                showError(e, '打开文件夹对话框失败');
            }
        });

        // 文件浏览器（选择文件用，保留自定义弹窗）
        let browserMode = 'dir';
        let currentPath = '';
        let targetInputId = '';

        function openBrowser(mode, inputId) {
            browserMode = mode;
            targetInputId = inputId;
            document.getElementById('browser-title').textContent = mode === 'dir' ? '选择工作目录' : '选择文件';
            document.getElementById('browser-select-btn').textContent = mode === 'dir' ? '选择此目录' : '选择此文件';
            navigatePath('');
            document.getElementById('browser-modal').classList.add('show');
        }
        function closeBrowser() {
            document.getElementById('browser-modal').classList.remove('show');
        }
        async function navigatePath(path) {
            const r = await fetch('/api/browse', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: path})
            });
            const data = await r.json();
            if (data.error) { alert(data.error); return; }
            currentPath = data.current;
            document.getElementById('browser-breadcrumb').textContent = currentPath || '计算机';
            const fileList = document.getElementById('browser-file-list');
            fileList.innerHTML = '';
            if (data.parent !== undefined && data.parent !== null) {
                const div = document.createElement('div');
                div.className = 'file-item dir';
                div.dataset.path = data.parent;
                div.dataset.type = 'dir';
                div.innerHTML = '<span class="icon">📁</span> ..';
                fileList.appendChild(div);
            }
            data.items.forEach(item => {
                const div = document.createElement('div');
                div.className = 'file-item ' + item.type;
                div.dataset.path = item.path;
                div.dataset.type = item.type;
                div.innerHTML = `<span class="icon">${item.type === 'dir' ? '📁' : '📄'}</span> ${item.name}`;
                fileList.appendChild(div);
            });
        }

        const browserFileList = document.getElementById('browser-file-list');
        if (browserFileList) {
            browserFileList.addEventListener('click', function(e) {
                const item = e.target.closest('.file-item');
                if (!item) return;
                const path = item.dataset.path;
                const type = item.dataset.type;
                if (type === 'dir') navigatePath(path);
                else if (browserMode === 'file') {
                    let finalPath = path;
                    let ext = path.split('.').pop().toLowerCase();
                    if(ext === 'py') finalPath = 'python "' + path + '"';
                    document.getElementById(targetInputId).value = finalPath;
                    closeBrowser();
                }
            });
        }

        document.getElementById('browser-select-btn').addEventListener('click', () => {
            if (browserMode === 'file') {
                alert('请在列表中点击要选择的文件');
                return;
            }
            if (currentPath) document.getElementById(targetInputId).value = currentPath;
            closeBrowser();
        });
        document.getElementById('browser-cancel-btn').addEventListener('click', closeBrowser);
        document.getElementById('file-browse-btn').addEventListener('click', () => openBrowser('file', 'cmd-input'));
    </script>
</body>
</html>'''


# ---------- 路由 ----------
@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        app_name=APP_NAME,
        theme=config_manager.config.get('theme', 'dark'),
        is_running=scheduler.running if scheduler else False,
        time_presets=config_manager.config.get('time_presets', {}),
        command_presets=config_manager.config.get('command_presets', []),
        last_working_dir=config_manager.config.get('last_working_dir', ''),
        last_command=config_manager.config.get('last_command', ''),
        last_cron=config_manager.config.get('time_presets', {}).get('每天早上7点', ''),
        auto_restart=auto_restart_manager.auto_restart,
        cur_dir=os.path.abspath(os.curdir)
    )


@app.route('/api/select_folder')
def select_folder():
    """使用系统原生对话框选择文件夹"""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder_selected = filedialog.askdirectory()
        root.destroy()
        if folder_selected:
            return jsonify({'path': os.path.normpath(folder_selected)})
        else:
            return jsonify({'path': ''})
    except Exception as e:
        return jsonify({'error': f'无法打开文件夹选择器: {str(e)}'}), 500


@app.route('/api/browse', methods=['POST'])
def api_browse():
    data = request.get_json()
    path = data.get('path', '').strip()
    if not path:
        if platform.system() == 'Windows':
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            return jsonify(
                {'current': '', 'parent': '', 'items': [{'name': d, 'type': 'dir', 'path': d} for d in drives]})
        else:
            path = '/'
    else:
        path = os.path.abspath(path)
    if not os.path.exists(path):
        return jsonify({'error': f'路径不存在: {path}'})
    if not os.path.isdir(path):
        path = os.path.dirname(path)
    try:
        items = []
        for entry in os.listdir(path):
            full = os.path.join(path, entry)
            is_dir = os.path.isdir(full)
            items.append({'name': entry, 'type': 'dir' if is_dir else 'file', 'path': full})
        items.sort(key=lambda x: (0 if x['type'] == 'dir' else 1, x['name'].lower()))
        parent = os.path.dirname(path)
        if platform.system() == 'Windows' and len(path) == 3 and path[1] == ':':
            parent = ''
        return jsonify({'current': path, 'parent': parent, 'items': items})
    except PermissionError:
        return jsonify({'error': '没有权限访问该目录'})


@app.route('/api/tasks')
def api_tasks():
    if not scheduler:
        return jsonify([])
    return jsonify(scheduler.get_tasks_summary())


@app.route('/api/tasks/add', methods=['POST'])
def api_add_task():
    global scheduler
    try:
        if scheduler is None:
            return jsonify({'error': '调度器未初始化，请重启程序'}), 500
        data = request.get_json()
        cron = data.get('cron', '').strip()
        dir_path = data.get('dir', '').strip()
        cmd = data.get('cmd', '').strip()
        timeout = int(data.get('timeout', DEFAULT_TIMEOUT))
        retry = int(data.get('retry', 1))
        env = data.get('env', {})
        task_id = scheduler.add_task(cron, cmd, dir_path, True, timeout, retry, env)
        config_manager.config['last_command'] = cmd
        config_manager.config['last_working_dir'] = dir_path
        config_manager.save_config()
        socketio.emit('task_update', scheduler.get_tasks_summary())
        return jsonify({'success': True, 'id': task_id})
    except ValueError as e:
        return jsonify({'error': str(e)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'添加失败: {str(e)}'}), 500


@app.route('/api/tasks/remove', methods=['POST'])
def api_remove_task():
    try:
        idx = request.get_json().get('index')
        if scheduler:
            scheduler.remove_task(idx)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/toggle', methods=['POST'])
def api_toggle_task():
    try:
        idx = request.get_json().get('index')
        if scheduler is None:
            return jsonify({'error': '调度器未初始化'}), 500
        enabled = scheduler.toggle_task_status(idx)
        tasks = scheduler.get_tasks_summary()
        return jsonify({'success': True, 'enabled': enabled, 'tasks': tasks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/test', methods=['POST'])
def api_test_task():
    try:
        data = request.get_json()
        runner = TaskRunner(data['cmd'], data['dir'], timeout=30, retry=1)

        def run():
            try:
                out = runner.execute()
                socketio.emit('log_message', f'[测试] 命令: {data["cmd"]}')
                socketio.emit('log_message', f'[测试] 输出:\n{out}')
            except Exception as e:
                socketio.emit('log_message', f'[测试] 错误: {str(e)}')

        Thread(target=run, daemon=True).start()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scheduler/start', methods=['POST'])
def api_start():
    if not scheduler or not scheduler.tasks:
        return jsonify({'error': '请先添加任务'})
    if scheduler.running:
        return jsonify({'error': '已在运行'})
    Thread(target=scheduler.start, daemon=True).start()
    config_manager.config['is_running'] = True
    config_manager.save_config()
    socketio.emit('log_message', '调度器已启动')
    socketio.emit('status_update', {'running': True})
    return jsonify({'success': True})


@app.route('/api/scheduler/stop', methods=['POST'])
def api_stop():
    if scheduler and scheduler.running:
        scheduler.stop()
    config_manager.config['is_running'] = False
    config_manager.save_config()
    socketio.emit('log_message', '调度器已停止')
    socketio.emit('status_update', {'running': False})
    return jsonify({'success': True})


@app.route('/api/theme/toggle', methods=['POST'])
def api_theme():
    cur = config_manager.config.get('theme', 'dark')
    new = 'light' if cur == 'dark' else 'dark'
    config_manager.config['theme'] = new
    config_manager.save_config()
    return jsonify({'theme': new})


@app.route('/api/auto_restart', methods=['POST'])
def api_auto_restart():
    enable = request.get_json().get('enable', True)
    auto_restart_manager.set_auto_restart(enable)
    return jsonify({'auto_restart': enable})


# ---------- 启动 ----------
def init_scheduler():
    global scheduler
    scheduler = TaskScheduler(socketio=socketio)
    scheduler.load_tasks()
    if config_manager.config.get('is_running', False):
        Thread(target=scheduler.start, daemon=True).start()


if __name__ == '__main__':
    print("=" * 60)
    print("正在启动自动化定时器...")
    print("=" * 60)
    try:
        init_scheduler()

        def open_browser():
            time.sleep(3)
            webbrowser.open("http://127.0.0.1:5000")

        Thread(target=open_browser, daemon=True).start()
        print("启动 Flask 服务...")
        socketio.run(app, host="127.0.0.1", port=5000, debug=False, allow_unsafe_werkzeug=True)
    except Exception:
        traceback.print_exc()
        input("按回车退出...")
