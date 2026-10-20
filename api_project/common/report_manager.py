#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
报告管理器 — 封装 Allure 报告生成、压缩、清理、邮件通知等后置逻辑。

从 run_testcases.py 中抽离，保持 run_testcases.py 精简为入口脚本。

用法：
    from api_project.common.report_manager import run_post_test_tasks

    # pytest 跑完后调用
    run_post_test_tasks()
"""

import os
import re
import sys
import json
import shutil
import subprocess
import time
from datetime import datetime
from api_project import DATA_DIR_PATH, REPORT_DIR_PATH, PROJECT_ABS_PATH
from api_project.common.Network import check_port, get_local_ip
from api_project.common.Email import EmailService
from api_project.common.LOG import Logger
from api_project.config.allure_config import Allure
from api_project.common.settings import get_bool_env

logger = Logger()

# 历史测试结果记录文件（不参与 init() 清理，长期积累用于趋势分析）
HISTORY_DIR = os.path.join(PROJECT_ABS_PATH, 'history')
HISTORY_FILE = os.path.join(HISTORY_DIR, 'run_history.jsonl')
TREND_REPORT_PATH = os.path.join(HISTORY_DIR, 'trend_report.html')

# ====================== 配置项 ======================

SEND_EMAIL_MODE = os.getenv("SEND_EMAIL", "only_failed")
# 可选值（严格三档）：
#   "only_failed" = 只有失败才发邮件
#   "always"      = 全部成功/失败都发邮件
#   "never"       = 永远不发邮件
# 兼容旧布尔写法：true/false/1/0 自动映射到合法枚举，避免语义冲突


def _normalize_send_email_mode(raw_value: str) -> str:
    """将 SEND_EMAIL 环境变量归一化为合法枚举（always/only_failed/never）"""
    value = str(raw_value or "").strip().lower()
    mapping = {
        "true": "always", "1": "always", "yes": "always", "on": "always",
        "false": "never", "0": "never", "no": "never", "off": "never",
    }
    if value in ("always", "only_failed", "never"):
        return value
    if value in mapping:
        normalized = mapping[value]
        logger.warning(
            f"⚠️ SEND_EMAIL={raw_value!r} 是旧布尔写法，已自动映射为 {normalized!r}。"
            "请改为 always/only_failed/never 三档之一"
        )
        return normalized
    logger.warning(
        f"⚠️ SEND_EMAIL={raw_value!r} 不是合法枚举（always/only_failed/never），"
        "已回退为 only_failed"
    )
    return "only_failed"


SEND_EMAIL_MODE = _normalize_send_email_mode(SEND_EMAIL_MODE)

# Allure 服务默认不启动，避免每轮测试结束后自动唤起浏览器。
# 如需保留本地 Allure 服务，可在 api_project/.env 中设置 AUTO_START_ALLURE=true。
AUTO_START_ALLURE = get_bool_env("AUTO_START_ALLURE", default=False)


# ====================== 测试结果检查 ======================

def check_test_result():
    """检查测试结果，返回是否有失败用例。"""
    # 方法1：通过 HTML 报告判断
    report_file = os.path.join(REPORT_DIR_PATH, 'report.html')
    if os.path.exists(report_file):
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()
            failed_match = re.search(r'(\d+)\s*failures?', content, re.IGNORECASE)
            if failed_match:
                return int(failed_match.group(1)) > 0

    # 方法2：通过 pytest 缓存判断
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.pytest_cache')
    if os.path.exists(cache_dir):
        cache_file = os.path.join(cache_dir, 'v', 'cache', 'lastfailed')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return len(json.load(f)) > 0
            except Exception:
                pass

    return False


def should_send_email():
    """判断是否应该发送邮件。"""
    if SEND_EMAIL_MODE == "never":
        return False
    if SEND_EMAIL_MODE == "always":
        return True
    # only_failed 或其他值 → 有失败才发
    return check_test_result()


def get_html_report_path():
    """获取 HTML 报告路径（多候选路径优先级查找）。"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidate_paths = [
        os.path.join(project_root, 'reports', 'report.html'),
        os.path.join(REPORT_DIR_PATH, 'reports', 'report.html'),
        os.path.join(REPORT_DIR_PATH, 'report.html'),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            logger.info(f"✅ 找到 HTML 报告: {path}")
            return path
    logger.warning("⚠️ 未找到 HTML 报告文件")
    return None


# ====================== Allure 报告服务 ======================

def allure_server():
    """
    启动 Allure 报告服务并打印访问地址。

    同步执行：获取 IP → 检查端口 → 打印地址 → 启动服务进程。
    subprocess.Popen 启动后立即返回，服务在后台运行。
    """
    try:
        local_ip = get_local_ip()
        port_in_use = check_port(Allure.PORT)

        # 无论端口是否被占用，都打印访问地址（端口被占用说明上次服务可能还在跑）
        if port_in_use:
            logger.warning(f"⚠️ 端口 {Allure.PORT} 已被占用（可能是上次的 Allure 服务仍在运行）")
        else:
            logger.info(f"端口 {Allure.PORT} 未使用，正在启动 Allure 服务...")

        # 先打印访问地址（确保用户一定能看到）
        logger.info(f"💻 电脑访问: http://127.0.0.1:{Allure.PORT}")
        logger.info(f"📱 手机访问: http://{local_ip}:{Allure.PORT}")
        logger.info(f"   → 确保手机电脑同一Wi-Fi")

        # 端口被占用就不重复启动
        if port_in_use:
            return None

        # 启动 allure serve（Popen 立即返回，服务在后台运行）
        process = subprocess.Popen(
            [Allure.PATH, 'serve', '-p', str(Allure.PORT), DATA_DIR_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        # 检查进程是否立刻退出（启动失败）
        if process.poll() is not None:
            logger.error(f"❌ Allure 服务启动失败，进程已退出")
            return None

        logger.info("✅ Allure 服务已启动")
        return process

    except Exception as e:
        logger.error(f"启动失败: {e}")
        return None


def generate_allure_html_report():
    """使用 Allure 命令生成 HTML 报告。"""
    try:
        allure_html_report_dir = os.path.join(REPORT_DIR_PATH, 'allure_html_report')
        subprocess.run(
            [Allure.PATH, 'generate', DATA_DIR_PATH, '-o', allure_html_report_dir, '--clean'],
            check=True,
        )
        logger.info(f"Allure HTML 报告已生成到 {allure_html_report_dir}")
        return allure_html_report_dir
    except (OSError, subprocess.CalledProcessError) as e:
        logger.error(f"生成 Allure HTML 报告失败：{e}")
        return None


# ====================== Allure 报告压缩 ======================

_BAT_CONTENT = '''@echo off
setlocal enabledelayedexpansion
set "chrome_path="
::从注册表查找谷歌浏览器路径
set reg_query_command=reg query "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chrome.exe" /ve
::遍历注册表查询结果
for /f "tokens=2*" %%A in ('%reg_query_command%') do (
    ::如果有 REG_SZ，则证明找到了谷歌浏览器
    if "%%A"=="REG_SZ" (
        ::如果路径存在，则设置谷歌浏览器绝对路径到变量 chrome_path
        set "tmp_chrome_path=%%B"
        if exist "!tmp_chrome_path!" (
            set "chrome_path=%%B"
        )
    )
)
::如果上面找到了谷歌浏览器的路径
if defined chrome_path (
    ::打印找到了谷歌浏览器的文件地址
    echo Chrome found at: "%chrome_path%"
    ::带参启动谷歌浏览器，使其不校验跨域问题 （./表示当前目录， 可以修改为你所需要的工作目录）
    "%chrome_path%" --disable-web-security --user-data-dir="%~dp0/tmp" "%~dp0/index.html"
) else (
    ::如果没找到，打印没找到
    echo Chrome not found.
    ::打印启动 web 信息
    echo start a webserver ...
    ::启动一个 web 服务监听 5001 端口，在后台运行。默认用当前文件夹的 index.html 作为首页
    start /b http_server.exe -port 5001
    ::使用默认浏览器打开 web 服务的地址并等待浏览器关闭
    start "" /WAIT http://127.0.0.1:5001
)
'''


def zip_allure_report():
    """压缩 Allure 报告数据为 ZIP 包，附带启动脚本和使用说明。"""
    allure_html_report_dir = generate_allure_html_report()
    if not allure_html_report_dir:
        return None

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = os.path.join(REPORT_DIR_PATH, f"allure_report_{timestamp}.zip")

        shutil.make_archive(zip_filename.replace('.zip', ''), 'zip', allure_html_report_dir)
        logger.info(f"Allure 报告已压缩为: {zip_filename}")

        allure_reports_dir = os.path.join(os.getcwd(), 'allure_reports', timestamp)
        os.makedirs(allure_reports_dir, exist_ok=True)
        shutil.copy2(zip_filename, allure_reports_dir)

        # 写入启动脚本
        bat_path = os.path.join(allure_reports_dir, 'allure_open.bat')
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(_BAT_CONTENT)

        # 写入使用说明
        instruction = "如果本地未安装 allure 或打开失败，把allure压缩文件解压到当前文件夹并双击allure_open.bat即可正常查看"
        with open(os.path.join(allure_reports_dir, '使用说明.txt'), 'w', encoding='utf-8') as f:
            f.write(instruction)

        return zip_filename
    except Exception as e:
        logger.error(f"压缩 Allure 报告失败: {e}")
        return None


# ====================== 旧报告清理 ======================

def cleanup_old_allure_reports(max_keep=3):
    """清理旧的 allure 报告，只保留最近 max_keep 个。"""
    allure_reports_base = os.path.join(os.getcwd(), 'allure_reports')
    if not os.path.exists(allure_reports_base):
        return

    # 1. 清理 allure_reports/<timestamp>/ 目录
    try:
        subdirs = sorted(
            [d for d in os.listdir(allure_reports_base)
             if os.path.isdir(os.path.join(allure_reports_base, d))],
            reverse=True,
        )
        for old_dir in subdirs[max_keep:]:
            old_path = os.path.join(allure_reports_base, old_dir)
            try:
                shutil.rmtree(old_path)
                logger.info(f"🗑️ 已清理旧 allure 报告目录: {old_dir}")
            except Exception as e:
                logger.warning(f"清理目录 {old_dir} 失败: {e}")

        kept = subdirs[:max_keep]
        if kept:
            logger.info(f"📦 保留最近 {len(kept)} 个 allure 报告: {kept}")
    except Exception as e:
        logger.warning(f"扫描 allure_reports 目录失败: {e}")

    # 2. 清理 REPORT_DIR_PATH 下旧的 zip 文件
    try:
        zip_files = sorted(
            [f for f in os.listdir(REPORT_DIR_PATH)
             if f.startswith('allure_report_') and f.endswith('.zip')],
            reverse=True,
        )
        for old_zip in zip_files[max_keep:]:
            old_zip_path = os.path.join(REPORT_DIR_PATH, old_zip)
            try:
                os.remove(old_zip_path)
                logger.info(f"🗑️ 已清理旧 allure zip 文件: {old_zip}")
            except Exception as e:
                logger.warning(f"清理 zip 文件 {old_zip} 失败: {e}")
    except Exception as e:
        logger.warning(f"扫描 REPORT_DIR_PATH zip 文件失败: {e}")


# ====================== 历史记录与趋势分析 ======================

def save_run_record():
    """
    保存本次测试结果到 run_history.jsonl（一行一条 JSON，供趋势分析）。

    统计来源：allure-results 目录（DATA_DIR_PATH）下的 result-*.json，
    无需解析 HTML，纯 JSON 统计，失败/成功/跳过一目了然。
    """
    try:
        if not os.path.isdir(DATA_DIR_PATH):
            return
        result_files = [
            f for f in os.listdir(DATA_DIR_PATH)
            if f.endswith('-result.json')  # Allure 标准命名：{uuid}-result.json
        ]
        if not result_files:
            logger.warning("⚠️ 未找到 allure 结果文件，跳过历史记录")
            return

        passed = failed = skipped = 0
        duration_ms = 0.0
        for fname in result_files:
            try:
                with open(os.path.join(DATA_DIR_PATH, fname), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                status = data.get('status', 'unknown')
                if status == 'passed':
                    passed += 1
                elif status in ('failed', 'broken'):
                    failed += 1
                elif status == 'skipped':
                    skipped += 1
                start = data.get('start', 0)
                stop = data.get('stop', 0)
                if stop and start:
                    duration_ms += (stop - start)
            except Exception:
                continue

        total = passed + failed + skipped
        pass_rate = round(passed / total * 100, 2) if total else 0.0
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": pass_rate,
            "duration_sec": round(duration_ms / 1000, 2),
            "executor": os.getenv("TEST_EXECUTOR", ""),
        }

        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(f"📊 历史记录已保存: {record['timestamp']} 通过率 {pass_rate}%")
    except Exception as e:
        logger.warning(f"⚠️ 保存历史记录失败: {str(e)}")


def generate_trend_report():
    """
    基于 run_history.jsonl 生成趋势分析 HTML（Chart.js 折线图 + 汇总表）。
    输出到 api_project/report/trend_report.html。
    """
    if not os.path.exists(HISTORY_FILE):
        logger.info("ℹ️ 暂无历史数据，跳过趋势报告生成")
        return None

    records = []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue
    except Exception as e:
        logger.warning(f"⚠️ 读取历史记录失败: {str(e)}")
        return None

    if len(records) < 2:
        logger.info("ℹ️ 历史记录不足 2 条，跳过趋势报告生成")
        return None

    # 只取最近 30 次，避免图表过密
    records = records[-30:]
    timestamps = [r['timestamp'] for r in records]
    pass_rates = [r['pass_rate'] for r in records]
    totals = [r['total'] for r in records]
    failed_list = [r['failed'] for r in records]
    # 前端展示增强（仅从 records 提取，不改变统计逻辑）
    passed_list = [r['passed'] for r in records]
    skipped_list = [r['skipped'] for r in records]
    durations_list = [r['duration_sec'] for r in records]
    latest_rate = records[-1]['pass_rate'] if records else 0
    prev_rate = records[-2]['pass_rate'] if len(records) >= 2 else None

    rows_html = "".join(
        f"<tr><td>{r['timestamp']}</td><td>{r.get('executor','-')}</td>"
        f"<td>{r['total']}</td><td>{r['passed']}</td>"
        f"<td><span class='{'badge-fail' if r['failed'] else 'badge-ok'}'>{r['failed']}</span></td>"
        f"<td>{r['skipped']}</td>"
        f"<td><span class='pass-badge'><span class='pass-bar'><i style='width:{r['pass_rate']}%'></i></span>"
        f"<span class='rate-txt'>{r['pass_rate']}%</span></span></td>"
        f"<td>{r['duration_sec']}s</td></tr>"
        for r in reversed(records)
    )

    # 汇总统计
    avg_rate = round(sum(r['pass_rate'] for r in records) / len(records), 2)
    total_runs = len(records)
    best_rate = max(r['pass_rate'] for r in records)

    # ---- 主题切换 JS（独立字符串，避免 f-string 花括号转义） ----
    _theme_js = r"""
function cssVar(name){ return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function curTheme(){ return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'; }
let savedTheme = localStorage.getItem('trend_theme');
if (!savedTheme && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) savedTheme = 'light';
if (savedTheme === 'light' || savedTheme === 'dark') document.documentElement.dataset.theme = savedTheme;
const themeBtn = document.getElementById('themeToggle');
function syncThemeBtn(){
  themeBtn.textContent = curTheme() === 'light' ? '\u2600\uFE0F' : '\uD83C\uDF19';
  themeBtn.title = curTheme() === 'light' ? '切换到深色模式' : '切换到浅色模式';
}
function applyChartTheme(){
  const ch = window.__trendChart;
  if (!ch) return;
  const tick = cssVar('--chart-tick'), grid = cssVar('--chart-grid');
  ch.options.plugins.tooltip.backgroundColor = cssVar('--chart-tooltip-bg');
  ch.options.plugins.tooltip.titleColor = cssVar('--chart-tooltip-title');
  ch.options.plugins.tooltip.bodyColor = cssVar('--chart-tooltip-body');
  ch.options.plugins.legend.labels.color = tick;
  ch.options.scales.y.ticks.color = tick;
  ch.options.scales.y.title.color = tick;
  ch.options.scales.y1.ticks.color = tick;
  ch.options.scales.y1.title.color = tick;
  ch.options.scales.x.ticks.color = tick;
  ch.options.scales.y.grid.color = grid;
  ch.update();
}
themeBtn.addEventListener('click', function(){
  const next = curTheme() === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('trend_theme', next);
  syncThemeBtn();
  applyChartTheme();
  if (window.__applyBgTheme) window.__applyBgTheme();
});
syncThemeBtn();
"""

    # ---- 全局粒子星云背景 JS（与汇总报告一致） ----
    _particles_js = r"""
(function(){
  const canvas = document.getElementById('bgParticles');
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(70, innerWidth/innerHeight, 0.1, 100);
  camera.position.z = 30;
  const renderer = new THREE.WebGLRenderer({canvas:canvas, alpha:true, antialias:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  function resize(){ renderer.setSize(innerWidth, innerHeight, false); }
  resize();
  const COUNT = 520, boxW = 48, boxH = 30, boxD = 20;
  const pos = new Float32Array(COUNT*3), seed = new Float32Array(COUNT);
  for (let i=0;i<COUNT;i++){
    pos[i*3]   = (Math.random()-0.5)*boxW;
    pos[i*3+1] = (Math.random()-0.5)*boxH;
    pos[i*3+2] = (Math.random()-0.5)*boxD;
    seed[i] = 0.002 + Math.random()*0.004;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos,3));
  const mat = new THREE.PointsMaterial({
    size:0.12, transparent:true, opacity:0.55, depthWrite:false,
    color:0x7da2ff, blending:THREE.AdditiveBlending
  });
  const points = new THREE.Points(geo, mat);
  scene.add(points);
  function applyBgTheme(){
    const light = curTheme() === 'light';
    if (light){ mat.color.set(0x6b7fc0); mat.opacity = 0.30; mat.blending = THREE.NormalBlending; }
    else { mat.color.set(0x7da2ff); mat.opacity = 0.55; mat.blending = THREE.AdditiveBlending; }
    mat.needsUpdate = true;
  }
  window.__applyBgTheme = applyBgTheme;
  let mx=0, my=0, cmx=0, cmy=0;
  window.addEventListener('mousemove', function(e){
    mx = (e.clientX/innerWidth - 0.5)*2;
    my = (e.clientY/innerHeight - 0.5)*2;
  });
  function animate(){
    requestAnimationFrame(animate);
    cmx += (mx-cmx)*0.04; cmy += (my-cmy)*0.04;
    camera.position.x = cmx*1.4;
    camera.position.y = -cmy*0.9;
    camera.lookAt(0,0,0);
    const p = geo.attributes.position.array;
    for (let i=0;i<COUNT;i++){
      p[i*3+1] += seed[i];
      if (p[i*3+1] > boxH/2) p[i*3+1] = -boxH/2;
    }
    geo.attributes.position.needsUpdate = true;
    points.rotation.y = performance.now()*0.00005;
    renderer.render(scene, camera);
  }
  applyBgTheme();
  animate();
  window.addEventListener('resize', resize);
})();
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>自动化测试趋势报告</title>
<script src="https://cdn.jsdelivr.net/npm/three@0.149.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1524;
    --grad-1: rgba(99,102,241,.18);
    --grad-2: rgba(56,189,248,.14);
    --card-bg: #1a2234;
    --card-border: rgba(255,255,255,.06);
    --text: #e6eaf3;
    --text-sub: #8b95ab;
    --panel-shadow: 0 8px 28px rgba(0,0,0,.4), 0 2px 8px rgba(0,0,0,.25);
    --th-bg: #222c44;
    --td-border: #26304a;
    --row-hover: #222c44;
    --ok: #34d399;
    --fail: #f87171;
    --radius: 16px;
    --chart-tick: #8b95ab;
    --chart-grid: rgba(128,140,170,.14);
    --chart-tooltip-bg: rgba(15,21,36,.94);
    --chart-tooltip-title: #e6eaf3;
    --chart-tooltip-body: #c3cbe0;
  }}
  [data-theme="light"] {{
    --bg: #f4f6fb;
    --grad-1: rgba(99,102,241,.10);
    --grad-2: rgba(56,189,248,.10);
    --card-bg: #ffffff;
    --card-border: rgba(255,255,255,.8);
    --text: #1f2430;
    --text-sub: #7c8497;
    --panel-shadow: 0 8px 28px rgba(30,41,82,.08), 0 2px 8px rgba(30,41,82,.04);
    --th-bg: #f6f8fd;
    --td-border: #eef1f8;
    --row-hover: #f6f8fd;
    --ok: #16a34a;
    --fail: #dc2626;
    --chart-tick: #6b7490;
    --chart-grid: rgba(107,116,144,.16);
    --chart-tooltip-bg: rgba(255,255,255,.97);
    --chart-tooltip-title: #1f2430;
    --chart-tooltip-body: #4a5270;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', 'Microsoft YaHei', -apple-system, sans-serif;
    background: var(--bg);
    background-image:
      radial-gradient(620px 300px at 6% -6%, var(--grad-1), transparent 70%),
      radial-gradient(720px 340px at 96% 2%, var(--grad-2), transparent 70%);
    background-attachment: fixed;
    color: var(--text);
    margin: 0; padding: 28px 20px 40px;
    -webkit-font-smoothing: antialiased;
    position: relative; overflow-x: hidden;
    transition: background-color .4s ease, color .4s ease;
  }}
  #bgParticles {{ position: fixed; inset: 0; width: 100%; height: 100%; z-index: 0; pointer-events: none; }}
  .container {{ max-width: 1080px; margin: 0 auto; position: relative; z-index: 1; }}
  header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 22px; }}
  h1 {{ margin: 0; font-size: 24px; letter-spacing: .5px; }}
  .subtitle {{ margin: 8px 0 0; color: var(--text-sub); font-size: 13px; }}
  .badge {{
    background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff;
    font-size: 12px; padding: 6px 14px; border-radius: 999px;
    box-shadow: 0 4px 14px rgba(99,102,241,.35);
  }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }}
  @media (max-width: 860px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
  /* 手机端：仅压缩展示密度，保留图表、数据字段和桌面端布局逻辑。 */
  @media (max-width: 640px) {{
    body {{ padding: 18px 12px 30px; }}
    header {{ align-items: flex-start; margin-bottom: 18px; }}
    h1 {{ font-size: 21px; line-height: 1.35; }}
    .subtitle {{ font-size: 12px; line-height: 1.65; }}
    .badge {{ padding: 5px 11px; }}
    .cards {{ grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }}
    .card {{ padding: 14px 15px; }}
    .card .num {{ font-size: 25px; margin-top: 7px; }}
    .card .label, .delta {{ font-size: 11px; }}
    .panel {{ padding: 16px 14px; margin-bottom: 14px; }}
    .panel-head {{ align-items: flex-start; margin-bottom: 12px; }}
    .panel-head h3 {{ font-size: 14px; line-height: 1.5; }}
    .legend-hint {{ line-height: 1.6; }}
    #trendChart {{ min-height: 190px; }}
    .table-wrap {{ margin: 0 -2px; -webkit-overflow-scrolling: touch; }}
    table {{ min-width: 720px; font-size: 12px; }}
    th, td {{ padding: 9px 10px; }}
    .theme-toggle {{ top: 12px; right: 12px; width: 38px; height: 38px; }}
  }}
  @media (max-width: 420px) {{ .cards {{ grid-template-columns: 1fr; }} .badge {{ font-size: 11px; }} }}
  .card {{
    background: var(--card-bg); border: 1px solid var(--card-border);
    border-radius: var(--radius); padding: 18px 20px;
    box-shadow: var(--panel-shadow);
    position: relative; overflow: hidden;
    transition: transform .18s ease, box-shadow .18s ease;
  }}
  .card:hover {{ transform: translateY(-3px); box-shadow: 0 14px 34px rgba(30,41,82,.12); }}
  .card::after {{ content: ''; position: absolute; right: -32px; top: -32px; width: 96px; height: 96px; border-radius: 50%; opacity: .6; }}
  .card.c1::after {{ background: radial-gradient(circle, rgba(79,156,247,.22), transparent 70%); }}
  .card.c2::after {{ background: radial-gradient(circle, rgba(22,163,74,.20), transparent 70%); }}
  .card.c3::after {{ background: radial-gradient(circle, rgba(245,158,11,.22), transparent 70%); }}
  .card.c4::after {{ background: radial-gradient(circle, rgba(239,68,68,.20), transparent 70%); }}
  .card .icon {{ font-size: 20px; }}
  .card .num {{ font-size: 30px; font-weight: 800; line-height: 1.15; margin-top: 10px; letter-spacing: .5px; font-variant-numeric: tabular-nums; }}
  .card.c1 .num {{ color: #3b82f6; }}
  .card.c2 .num {{ color: #16a34a; }}
  .card.c3 .num {{ color: #d97706; }}
  .card.c4 .num {{ color: #dc2626; }}
  .card .label {{ color: var(--text-sub); font-size: 13px; margin-top: 6px; }}
  .delta {{ display: inline-flex; align-items: center; gap: 3px; font-size: 12px; margin-top: 10px; padding: 2px 9px; border-radius: 999px; font-variant-numeric: tabular-nums; }}
  .delta.up {{ color: var(--ok); background: color-mix(in srgb, var(--ok) 12%, transparent); }}
  .delta.down {{ color: var(--fail); background: color-mix(in srgb, var(--fail) 12%, transparent); }}
  .delta.flat {{ color: var(--text-sub); background: color-mix(in srgb, var(--text-sub) 12%, transparent); }}
  .panel {{
    background: var(--card-bg); border: 1px solid var(--card-border);
    border-radius: var(--radius); padding: 22px 24px;
    box-shadow: var(--panel-shadow); margin-bottom: 20px;
  }}
  .panel-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  .panel-head h3 {{ margin: 0; font-size: 16px; }}
  .legend-hint {{ color: var(--text-sub); font-size: 12px; }}
  .legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 4px; vertical-align: middle; }}
  .table-wrap {{ overflow-x: auto; border-radius: 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead th {{
    background: var(--th-bg); color: var(--text-sub); font-weight: 600;
    padding: 11px 12px; white-space: nowrap;
  }}
  th, td {{ padding: 10px 12px; text-align: center; white-space: nowrap; }}
  tbody tr {{ border-bottom: 1px solid var(--td-border); transition: background .15s; }}
  tbody tr:hover {{ background: var(--row-hover); }}
  tbody tr:last-child {{ border-bottom: none; }}
  .pass-badge {{ display: inline-flex; align-items: center; gap: 7px; min-width: 92px; }}
  .pass-bar {{ flex: 1; height: 6px; border-radius: 999px; background: var(--td-border); overflow: hidden; }}
  .pass-bar > i {{ display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #22c55e, #4ade80); }}
  .rate-txt {{ font-variant-numeric: tabular-nums; }}
  .badge-fail, .badge-ok {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; min-width: 30px; }}
  .badge-fail {{ color: var(--fail); background: color-mix(in srgb, var(--fail) 12%, transparent); }}
  .badge-ok {{ color: var(--ok); background: color-mix(in srgb, var(--ok) 12%, transparent); }}
  footer {{ text-align: center; color: var(--text-sub); font-size: 12px; margin-top: 6px; }}
  .theme-toggle {{
    position: fixed; top: 18px; right: 18px; z-index: 60; width: 42px; height: 42px; border-radius: 50%;
    border: 1px solid var(--card-border); background: var(--card-bg); color: var(--text);
    font-size: 18px; line-height: 1; cursor: pointer; display: flex; align-items: center; justify-content: center;
    box-shadow: var(--panel-shadow); backdrop-filter: blur(8px); transition: transform .2s, box-shadow .2s;
  }}
  .theme-toggle:hover {{ transform: scale(1.1); }}
  [data-theme="light"] .card:hover {{ box-shadow: 0 12px 30px rgba(30,41,82,.12); }}
</style>
</head>
<body>
<canvas id="bgParticles"></canvas>
<button class="theme-toggle" id="themeToggle" title="切换浅色/深色">🌙</button>
<div class="container">
  <header>
    <div>
      <h1>📈 自动化测试趋势报告</h1>
      <p class="subtitle">基于历史执行记录自动生成 · 生成时间 <span id="genTime">—</span></p>
    </div>
    <span class="badge">最近 {total_runs} 次执行</span>
  </header>

  <div class="cards">
    <div class="card c1">
      <div class="icon">🗓️</div>
      <div class="num">{total_runs}</div>
      <div class="label">统计次数</div>
      <span class="delta flat" id="dRuns">持续积累中</span>
    </div>
    <div class="card c2">
      <div class="icon">📊</div>
      <div class="num">{avg_rate}%</div>
      <div class="label">平均通过率</div>
      <span class="delta flat" id="dAvg">—</span>
    </div>
    <div class="card c3">
      <div class="icon">🏆</div>
      <div class="num">{best_rate}%</div>
      <div class="label">历史最高通过率</div>
      <span class="delta flat" id="dBest">—</span>
    </div>
    <div class="card c4">
      <div class="icon">🧯</div>
      <div class="num">{sum(r['failed'] for r in records)}</div>
      <div class="label">累计失败用例</div>
      <span class="delta flat" id="dFail">—</span>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>📉 通过率 &amp; 失败数趋势</h3>
      <span class="legend-hint"><span class="legend-dot" style="background:#4f9cf7"></span>通过率(%)　<span class="legend-dot" style="background:rgba(239,68,68,.6)"></span>失败数</span>
    </div>
    <canvas id="trendChart" height="150"></canvas>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>📋 历史明细（最近 {total_runs} 次）</h3>
      <span class="legend-hint">最新在前 · 共 {total_runs} 条</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>时间</th><th>执行人</th><th>总数</th><th>通过</th><th>失败</th><th>跳过</th><th>通过率</th><th>耗时</th></tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
  </div>

  <footer>Generated by api_project/common/report_manager.py · Three.js + Chart.js v4</footer>
</div>
<script>
{_theme_js}
{_particles_js}
const labels = {json.dumps(timestamps, ensure_ascii=False)};
const passRates = {json.dumps(pass_rates)};
const failedList = {json.dumps(failed_list)};
const totals = {json.dumps(totals)};
const passedList = {json.dumps(passed_list)};
const skippedList = {json.dumps(skipped_list)};
const durations = {json.dumps(durations_list)};
const avgRate = {json.dumps(avg_rate)};
const bestRate = {json.dumps(best_rate)};
const latestRate = {json.dumps(latest_rate)};
const prevRate = {json.dumps(prev_rate)};
const latestFail = {json.dumps(failed_list[-1] if failed_list else 0)};
const prevFail = {json.dumps(failed_list[-2] if len(failed_list) >= 2 else None)};

document.getElementById('genTime').textContent = new Date().toLocaleString('zh-CN', {{ hour12: false }});

function fmtDelta(cur, prev, suffix, invert) {{
  if (prev === null || prev === undefined) return '<span class="delta flat">—</span>';
  const diff = cur - prev;
  const arrow = diff > 0 ? '▲' : (diff < 0 ? '▼' : '―');
  const cls = invert
    ? (diff > 0 ? 'down' : diff < 0 ? 'up' : 'flat')
    : (diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat');
  const txt = diff > 0 ? '+' + diff.toFixed(1) : diff.toFixed(1);
  return '<span class="delta ' + cls + '">' + arrow + ' ' + txt + (suffix || '') + ' 较上次</span>';
}}

document.getElementById('dAvg').outerHTML = fmtDelta(latestRate, avgRate, '%', false);
document.getElementById('dBest').outerHTML = (Math.abs(bestRate - latestRate) < 1e-9)
  ? '<span class="delta up">🏅 已达到历史最佳</span>'
  : fmtDelta(latestRate, bestRate, '%', false);
document.getElementById('dFail').outerHTML = fmtDelta(latestFail, prevFail, '', true);

const ctx = document.getElementById('trendChart').getContext('2d');
const grad = ctx.createLinearGradient(0, 0, 0, 340);
grad.addColorStop(0, 'rgba(79,156,247,.28)');
grad.addColorStop(1, 'rgba(79,156,247,.02)');

window.__trendChart = new Chart(ctx, {{
  data: {{
    labels,
    datasets: [
      {{
        type: 'line', label: '通过率(%)', data: passRates,
        borderColor: '#4f9cf7', backgroundColor: grad, fill: true,
        yAxisID: 'y', tension: .4, borderWidth: 3,
        pointRadius: 4, pointHoverRadius: 6,
        pointBackgroundColor: '#fff', pointBorderColor: '#4f9cf7', pointBorderWidth: 2
      }},
      {{
        type: 'bar', label: '失败数', data: failedList,
        backgroundColor: 'rgba(239,68,68,.45)', yAxisID: 'y1',
        borderRadius: 6, borderSkipped: false, maxBarThickness: 34
      }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      tooltip: {{
        backgroundColor: cssVar('--chart-tooltip-bg'), titleColor: cssVar('--chart-tooltip-title'), bodyColor: cssVar('--chart-tooltip-body'),
        padding: 12, cornerRadius: 10, displayColors: true,
        callbacks: {{
          afterBody: function(items) {{
            const i = items[0].dataIndex;
            return '总数: ' + totals[i] + '  通过: ' + passedList[i] + '  跳过: ' + skippedList[i] + '\\n耗时: ' + durations[i] + 's';
          }}
        }}
      }},
      legend: {{ labels: {{ usePointStyle: true, boxWidth: 8, padding: 18, color: cssVar('--chart-tick') }} }}
    }},
    scales: {{
      y: {{
        position: 'left', min: 0, max: 100,
        grid: {{ color: cssVar('--chart-grid'), drawTicks: false }},
        border: {{ display: false }},
        ticks: {{ callback: function(v) {{ return v + '%'; }}, color: cssVar('--chart-tick') }},
        title: {{ display: true, text: '通过率 %', color: cssVar('--chart-tick') }}
      }},
      y1: {{
        position: 'right', min: 0,
        grid: {{ display: false }},
        border: {{ display: false }},
        ticks: {{ stepSize: 1, color: cssVar('--chart-tick') }},
        title: {{ display: true, text: '失败数', color: cssVar('--chart-tick') }}
      }},
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 30, color: cssVar('--chart-tick') }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

    try:
        os.makedirs(REPORT_DIR_PATH, exist_ok=True)
        with open(TREND_REPORT_PATH, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"📈 趋势报告已生成: {TREND_REPORT_PATH}")
        return TREND_REPORT_PATH
    except Exception as e:
        logger.warning(f"⚠️ 生成趋势报告失败: {str(e)}")
        return None


# ====================== 多维度汇总报告（日报/周报/月报 + 3D 科技球体） ======================

# 汇总报告 HTML 模板（用 __PLACEHOLDER__ 占位，避免 f-string 转义 CSS/JS 花括号）
_SUMMARY_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>自动化测试汇总报告</title>
<script src="https://cdn.jsdelivr.net/npm/three@0.149.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0a0e1a;
    --card-bg: rgba(20,28,48,.72);
    --card-border: rgba(99,160,255,.18);
    --text: #e6ecff;
    --text-sub: #8b9bc4;
    --panel-shadow: 0 10px 40px rgba(0,0,0,.45), 0 0 0 1px rgba(99,160,255,.06);
    --th-bg: rgba(30,42,72,.6);
    --td-border: rgba(99,160,255,.1);
    --row-hover: rgba(99,160,255,.06);
    --ok: #34d399;
    --fail: #f87171;
    --radius: 18px;
    --badge-fail-bg: rgba(248,113,113,.14);
    --badge-ok-bg: rgba(52,211,153,.14);
    --chart-tick: #8b9bc4;
    --chart-grid: rgba(139,155,196,.12);
    --chart-tooltip-bg: rgba(10,14,26,.94);
    --chart-tooltip-title: #e6ecff;
    --chart-tooltip-body: #cdd6f0;
    --ring-track: rgba(139,155,196,.30);
  }
  [data-theme="light"] {
    --bg: #f4f6fb;
    --card-bg: #ffffff;
    --card-border: rgba(30,41,82,.10);
    --text: #1f2430;
    --text-sub: #6b7490;
    --panel-shadow: 0 8px 28px rgba(30,41,82,.08), 0 2px 8px rgba(30,41,82,.04);
    --th-bg: #f6f8fd;
    --td-border: #eef1f8;
    --row-hover: #f6f8fd;
    --ok: #16a34a;
    --fail: #dc2626;
    --badge-fail-bg: rgba(220,38,38,.10);
    --badge-ok-bg: rgba(22,163,74,.10);
    --chart-tick: #6b7490;
    --chart-grid: rgba(107,116,144,.16);
    --chart-tooltip-bg: rgba(255,255,255,.97);
    --chart-tooltip-title: #1f2430;
    --chart-tooltip-body: #4a5270;
    --ring-track: rgba(30,41,82,.18);
  }
  * { box-sizing: border-box; }
  body {
    font-family: 'Segoe UI','Microsoft YaHei',-apple-system,sans-serif;
    background: var(--bg);
    background-image:
      radial-gradient(900px 460px at 8% -10%, rgba(79,156,247,.14), transparent 70%),
      radial-gradient(900px 520px at 92% 6%, rgba(139,92,246,.12), transparent 70%),
      radial-gradient(700px 400px at 50% 110%, rgba(52,211,153,.08), transparent 70%);
    background-attachment: fixed;
    color: var(--text); margin:0; padding: 24px 18px 44px;
    -webkit-font-smoothing: antialiased; min-height:100vh;
    position:relative; overflow-x:hidden;
    transition:background-color .4s ease, color .4s ease;
  }
  [data-theme="light"] body {
    background-image:
      radial-gradient(900px 460px at 8% -10%, rgba(79,156,247,.10), transparent 70%),
      radial-gradient(900px 520px at 92% 6%, rgba(139,92,246,.08), transparent 70%),
      radial-gradient(700px 400px at 50% 110%, rgba(22,163,74,.06), transparent 70%);
  }
  #bgParticles { position:fixed; inset:0; width:100%; height:100%; z-index:0; pointer-events:none; }
  .container { max-width: 1160px; margin:0 auto; position:relative; z-index:1; }
  .hero { display:flex; gap:24px; align-items:center; justify-content:space-between; flex-wrap:wrap; margin-bottom:22px; }
  .hero-left { flex:1; min-width:280px; }
  h1 {
    margin:0; font-size:26px; letter-spacing:.6px;
    background: linear-gradient(120deg,#4f9cf7,#8b5cf6 60%,#34d399);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
  }
  .subtitle { margin:10px 0 0; color:var(--text-sub); font-size:13px; }
  .meta-row { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
  .meta-chip { font-size:12px; color:var(--text-sub); background:rgba(99,160,255,.08); border:1px solid var(--card-border); padding:6px 12px; border-radius:999px; }
  .meta-chip b { color:var(--text); font-weight:600; }
  .hero-right { position:relative; flex-shrink:0; display:flex; align-items:center; justify-content:center; }
  .ring-wrap { width:280px; height:280px; position:relative; }
  .ring-svg { width:100%; height:100%; display:block; }
  .ring-deco { position:absolute; inset:-12px; border-radius:50%; border:1px dashed var(--card-border); animation:spinSlow 26s linear infinite; }
  .ring-glow { position:absolute; inset:40px; border-radius:50%; background:radial-gradient(circle, rgba(79,156,247,.20), transparent 70%); animation:glowPulse 3.4s ease-in-out infinite; }
  @keyframes spinSlow { to { transform:rotate(360deg); } }
  @keyframes glowPulse { 0%,100%{ opacity:.55; transform:scale(1); } 50%{ opacity:1; transform:scale(1.06); } }
  .ring-track { fill:none; stroke:var(--ring-track); stroke-width:14; }
  .ring-bar { fill:none; stroke:url(#ringGrad); stroke-width:14; stroke-linecap:round; transform:rotate(-90deg); transform-origin:100px 100px; transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1); filter:drop-shadow(0 0 7px rgba(79,156,247,.4)); }
  .ring-center { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; pointer-events:none; }
  .ring-rate { font-size:46px; font-weight:800; letter-spacing:.5px; font-variant-numeric:tabular-nums; color:var(--text); }
  .ring-rate small { font-size:19px; font-weight:600; opacity:.75; margin-left:2px; }
  .ring-label { font-size:11px; color:var(--text-sub); margin-top:6px; letter-spacing:2px; }
  [data-theme="light"] .ring-deco { border-color:rgba(30,41,82,.22); }
  [data-theme="light"] .ring-rate { text-shadow:0 2px 10px rgba(30,41,82,.12); }
  .tabs { display:flex; gap:8px; margin-bottom:18px; padding:6px; background:var(--card-bg); border:1px solid var(--card-border); border-radius:14px; width:fit-content; }
  .tab { padding:9px 22px; border-radius:10px; font-size:14px; color:var(--text-sub); cursor:pointer; border:none; background:transparent; transition:all .2s; font-family:inherit; }
  .tab:hover { color:var(--text); background:rgba(99,160,255,.08); }
  .tab.active { color:#fff; background:linear-gradient(135deg,#4f9cf7,#8b5cf6); box-shadow:0 4px 16px rgba(79,156,247,.35); }
  .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px; }
  @media (max-width:860px) { .cards{grid-template-columns:repeat(2,1fr);} .ring-wrap{width:210px;height:210px;} .hero-right{margin:0 auto;} }
  /* 手机端：保留四维聚合、仪表盘和图表，仅调整密度与横向内容的可访问性。 */
  @media (max-width:640px) {
    body { padding:18px 12px 30px; }
    .container { max-width:100%; }
    .hero { display:block; margin-bottom:16px; }
    .hero-left { min-width:0; }
    h1 { font-size:22px; line-height:1.35; padding-right:42px; }
    .subtitle { font-size:12px; line-height:1.65; }
    .meta-row { gap:6px; margin-top:12px; }
    .meta-chip { font-size:11px; padding:6px 9px; }
    .hero-right { margin:16px auto 0; }
    .ring-wrap { width:190px; height:190px; }
    .ring-rate { font-size:40px; }
    .tabs { width:100%; overflow-x:auto; padding:5px; gap:5px; border-radius:12px; -webkit-overflow-scrolling:touch; }
    .tab { flex:0 0 auto; padding:8px 16px; font-size:13px; }
    .cards { grid-template-columns:1fr 1fr; gap:10px; margin-bottom:14px; }
    .card { padding:14px 15px; }
    .card .num { font-size:25px; margin-top:6px; }
    .card .label { font-size:11px; }
    .panel { padding:16px 14px; margin-bottom:14px; }
    .panel-head { align-items:flex-start; margin-bottom:12px; }
    .panel-head h3 { font-size:14px; line-height:1.5; }
    .legend-hint { font-size:11px; line-height:1.6; }
    #trendChart { min-height:190px; }
    .table-wrap { margin:0 -2px; -webkit-overflow-scrolling:touch; }
    table { min-width:720px; font-size:12px; }
    th, td { padding:9px 10px; }
    .theme-toggle { top:12px; right:12px; width:38px; height:38px; }
  }
  @media (max-width:420px) { .cards{grid-template-columns:1fr;} .ring-wrap{width:174px;height:174px;} .meta-chip{max-width:100%;} }
  .card { background:var(--card-bg); border:1px solid var(--card-border); border-radius:var(--radius); padding:18px 20px; box-shadow:var(--panel-shadow); position:relative; overflow:hidden; backdrop-filter:blur(8px); transition:transform .2s, box-shadow .2s; }
  .card:hover { transform:translateY(-3px); box-shadow:0 16px 44px rgba(0,0,0,.5); }
  .card::before { content:''; position:absolute; left:0; top:0; bottom:0; width:3px; }
  .card.c1::before { background:linear-gradient(#4f9cf7,#8b5cf6); }
  .card.c2::before { background:linear-gradient(#34d399,#4f9cf7); }
  .card.c3::before { background:linear-gradient(#f59e0b,#f87171); }
  .card.c4::before { background:linear-gradient(#8b5cf6,#4f9cf7); }
  .card .icon { font-size:18px; }
  .card .num { font-size:30px; font-weight:800; line-height:1.15; margin-top:8px; font-variant-numeric:tabular-nums; }
  .card.c1 .num { color:#4f9cf7; }
  .card.c2 .num { color:#34d399; }
  .card.c3 .num { color:#f59e0b; }
  .card.c4 .num { color:#a78bfa; }
  .card .label { color:var(--text-sub); font-size:12px; margin-top:6px; }
  .panel { background:var(--card-bg); border:1px solid var(--card-border); border-radius:var(--radius); padding:22px 24px; box-shadow:var(--panel-shadow); margin-bottom:20px; backdrop-filter:blur(8px); }
  .panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
  .panel-head h3 { margin:0; font-size:16px; }
  .legend-hint { color:var(--text-sub); font-size:12px; }
  .legend-dot { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:4px; vertical-align:middle; }
  .table-wrap { overflow-x:auto; border-radius:10px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  thead th { background:var(--th-bg); color:var(--text-sub); font-weight:600; padding:12px; white-space:nowrap; text-align:center; }
  th, td { padding:10px 12px; text-align:center; white-space:nowrap; }
  tbody tr { border-bottom:1px solid var(--td-border); transition:background .15s; }
  tbody tr:hover { background:var(--row-hover); }
  tbody tr:last-child { border-bottom:none; }
  .pass-badge { display:inline-flex; align-items:center; gap:7px; min-width:92px; }
  .pass-bar { flex:1; height:6px; border-radius:999px; background:var(--td-border); overflow:hidden; }
  .pass-bar > i { display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,#22c55e,#4ade80); }
  .badge-fail, .badge-ok { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; min-width:30px; }
  .badge-fail { color:var(--fail); background:var(--badge-fail-bg); }
  .badge-ok { color:var(--ok); background:var(--badge-ok-bg); }
  footer { text-align:center; color:var(--text-sub); font-size:12px; margin-top:8px; }
  .empty { text-align:center; color:var(--text-sub); padding:40px; }
  .theme-toggle {
    position:fixed; top:18px; right:18px; z-index:60; width:42px; height:42px; border-radius:50%;
    border:1px solid var(--card-border); background:var(--card-bg); color:var(--text);
    font-size:18px; line-height:1; cursor:pointer; display:flex; align-items:center; justify-content:center;
    box-shadow:var(--panel-shadow); backdrop-filter:blur(8px); transition:transform .2s, box-shadow .2s;
  }
  .theme-toggle:hover { transform:scale(1.1); }
  [data-theme="light"] .card:hover { box-shadow:0 12px 30px rgba(30,41,82,.12); }
</style>
</head>
<body>
<canvas id="bgParticles"></canvas>
<button class="theme-toggle" id="themeToggle" title="切换浅色/深色">🌙</button>
<div class="container">
  <div class="hero">
    <div class="hero-left">
      <h1>自动化测试汇总报告</h1>
      <p class="subtitle">多维度聚合分析 · 生成时间 <span id="genTime">—</span></p>
      <div class="meta-row">
        <span class="meta-chip">最近执行 <b>__LATEST_TS__</b></span>
        <span class="meta-chip">执行人 <b>__LATEST_EXECUTOR__</b></span>
        <span class="meta-chip">历史记录 <b>__TOTAL_RUNS__</b> 条</span>
        <span class="meta-chip">历史最佳 <b>__BEST_RATE__</b>%</span>
      </div>
    </div>
    <div class="hero-right">
      <div class="ring-wrap">
        <div class="ring-deco"></div>
        <div class="ring-glow"></div>
        <svg class="ring-svg" viewBox="0 0 200 200">
          <defs>
            <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#f87171"/>
              <stop offset="100%" stop-color="#ef4444"/>
            </linearGradient>
          </defs>
          <circle class="ring-track" cx="100" cy="100" r="86"/>
          <circle class="ring-bar" id="ringBar" cx="100" cy="100" r="86"/>
        </svg>
        <div class="ring-center">
          <div class="ring-rate" id="ringRate">__LATEST_RATE__<small>%</small></div>
          <div class="ring-label">最新通过率</div>
        </div>
      </div>
    </div>
  </div>

  <div class="tabs">
    <button class="tab active" data-dim="daily">日报</button>
    <button class="tab" data-dim="weekly">周报</button>
    <button class="tab" data-dim="monthly">月报</button>
    <button class="tab" data-dim="yearly">年报</button>
  </div>

  <div class="cards">
    <div class="card c1"><div class="icon">🔁</div><div class="num" id="cRuns">—</div><div class="label">执行次数（<span id="dimLabel">日报</span>）</div></div>
    <div class="card c2"><div class="icon">📊</div><div class="num" id="cAvg">—</div><div class="label">平均通过率</div></div>
    <div class="card c3"><div class="icon">🧯</div><div class="num" id="cFail">—</div><div class="label">累计失败用例</div></div>
    <div class="card c4"><div class="icon">⏱️</div><div class="num" id="cDur">—</div><div class="label">累计耗时</div></div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>📈 通过率 &amp; 失败数趋势</h3>
      <span class="legend-hint"><span class="legend-dot" style="background:#4f9cf7"></span>通过率(%)　<span class="legend-dot" style="background:rgba(248,113,113,.55)"></span>失败数</span>
    </div>
    <canvas id="trendChart" height="150"></canvas>
  </div>

  <div class="panel">
    <div class="panel-head">
      <h3>📋 明细（<span id="dimLabel2">日报</span>聚合）</h3>
      <span class="legend-hint" id="rowCount">—</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>周期</th><th>覆盖时间</th><th>执行次数</th><th>总数</th><th>通过</th><th>失败</th><th>跳过</th><th>通过率</th><th>耗时</th><th>执行人</th></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>

  <footer>Generated by api_project/common/report_manager.py · Three.js + Chart.js</footer>
</div>

<script>
const DATA = __DATA__;
const META = __META__;
const DIM_NAMES = {daily:"日报", weekly:"周报", monthly:"月报", yearly:"年报"};

/* ============ 主题切换（浅色/深色） ============ */
function cssVar(name){ return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function curTheme(){ return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'; }
const savedTheme = localStorage.getItem('report_theme');
if (savedTheme === 'light' || savedTheme === 'dark') document.documentElement.dataset.theme = savedTheme;
const themeBtn = document.getElementById('themeToggle');
function syncThemeBtn(){
  themeBtn.textContent = curTheme() === 'light' ? '☀️' : '🌙';
  themeBtn.title = curTheme() === 'light' ? '切换到深色模式' : '切换到浅色模式';
}
function applyChartTheme(){
  if (!chart) return;
  const tick = cssVar('--chart-tick'), grid = cssVar('--chart-grid');
  chart.options.plugins.tooltip.backgroundColor = cssVar('--chart-tooltip-bg');
  chart.options.plugins.tooltip.titleColor = cssVar('--chart-tooltip-title');
  chart.options.plugins.tooltip.bodyColor = cssVar('--chart-tooltip-body');
  chart.options.plugins.legend.labels.color = tick;
  chart.options.scales.y.ticks.color = tick;
  chart.options.scales.y.title.color = tick;
  chart.options.scales.y1.ticks.color = tick;
  chart.options.scales.y1.title.color = tick;
  chart.options.scales.x.ticks.color = tick;
  chart.options.scales.y.grid.color = grid;
  chart.update();
}
themeBtn.addEventListener('click', function(){
  const next = curTheme() === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('report_theme', next);
  syncThemeBtn();
  applyChartTheme();
  if (window.__applyBgTheme) window.__applyBgTheme();
});
syncThemeBtn();

document.getElementById('genTime').textContent = new Date().toLocaleString('zh-CN', {hour12:false});

/* ============ 全局粒子星云背景（随主题变色） ============ */
(function(){
  const canvas = document.getElementById('bgParticles');
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(70, innerWidth/innerHeight, 0.1, 100);
  camera.position.z = 30;
  const renderer = new THREE.WebGLRenderer({canvas:canvas, alpha:true, antialias:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  function resize(){ renderer.setSize(innerWidth, innerHeight, false); }
  resize();

  const COUNT = 520, boxW = 48, boxH = 30, boxD = 20;
  const pos = new Float32Array(COUNT*3), seed = new Float32Array(COUNT);
  for (let i=0;i<COUNT;i++){
    pos[i*3]   = (Math.random()-0.5)*boxW;
    pos[i*3+1] = (Math.random()-0.5)*boxH;
    pos[i*3+2] = (Math.random()-0.5)*boxD;
    seed[i] = 0.002 + Math.random()*0.004;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos,3));
  const mat = new THREE.PointsMaterial({
    size:0.12, transparent:true, opacity:0.55, depthWrite:false,
    color:0x7da2ff, blending:THREE.AdditiveBlending
  });
  const points = new THREE.Points(geo, mat);
  scene.add(points);

  function applyBgTheme(){
    const light = curTheme() === 'light';
    if (light){ mat.color.set(0x6b7fc0); mat.opacity = 0.30; mat.blending = THREE.NormalBlending; }
    else { mat.color.set(0x7da2ff); mat.opacity = 0.55; mat.blending = THREE.AdditiveBlending; }
    mat.needsUpdate = true;
  }
  window.__applyBgTheme = applyBgTheme;

  let mx=0, my=0, cmx=0, cmy=0;
  window.addEventListener('mousemove', function(e){
    mx = (e.clientX/innerWidth - 0.5)*2;
    my = (e.clientY/innerHeight - 0.5)*2;
  });

  function animate(){
    requestAnimationFrame(animate);
    cmx += (mx-cmx)*0.04; cmy += (my-cmy)*0.04;
    camera.position.x = cmx*1.4;
    camera.position.y = -cmy*0.9;
    camera.lookAt(0,0,0);
    const p = geo.attributes.position.array;
    for (let i=0;i<COUNT;i++){
      p[i*3+1] += seed[i];
      if (p[i*3+1] > boxH/2) p[i*3+1] = -boxH/2;
    }
    geo.attributes.position.needsUpdate = true;
    points.rotation.y = performance.now()*0.00005;
    renderer.render(scene, camera);
  }
  applyBgTheme();
  animate();
  window.addEventListener('resize', resize);
})();

/* ============ 通过率环形仪表盘 ============ */
(function(){
  const rate = Math.max(0, Math.min(100, META.latest_rate));
  const C = 2*Math.PI*86;
  const bar = document.getElementById('ringBar');
  bar.style.strokeDasharray = C.toFixed(2);
  bar.style.strokeDashoffset = C.toFixed(2);
  requestAnimationFrame(function(){ bar.style.strokeDashoffset = (C*(1-rate/100)).toFixed(2); });
  let c1, c2;
  if (rate >= 80){ c1='#4ade80'; c2='#22c55e'; }
  else if (rate >= 50){ c1='#fbbf24'; c2='#f59e0b'; }
  else { c1='#f87171'; c2='#ef4444'; }
  const stops = document.getElementById('ringGrad').children;
  stops[0].setAttribute('stop-color', c1);
  stops[1].setAttribute('stop-color', c2);
})();

/* ============ 维度切换 + 图表 ============ */
function badge(f){ return '<span class="'+(f?'badge-fail':'badge-ok')+'">'+f+'</span>'; }
function passBar(rate){ return '<span class="pass-badge"><span class="pass-bar"><i style="width:'+rate+'%"></i></span><span>'+rate+'%</span></span>'; }
function buildRows(dim){
  const rows = DATA[dim].rows;
  if (!rows.length) return '<tr><td colspan="10" class="empty">暂无数据</td></tr>';
  return rows.map(function(r){
    return '<tr><td>'+r.period+'</td><td>'+r.timestamp+'</td><td>'+r.runs+'</td><td>'+r.total+'</td><td>'+r.passed+'</td>'
      +'<td>'+badge(r.failed)+'</td><td>'+r.skipped+'</td><td>'+passBar(r.pass_rate)+'</td><td>'+r.duration_sec+'s</td><td>'+(r.executor||'-')+'</td></tr>';
  }).join('');
}
function setNum(id, v){ document.getElementById(id).textContent = v; }

let chart = null;
let currentDim = 'daily';
const ctx = document.getElementById('trendChart').getContext('2d');
const grad = ctx.createLinearGradient(0,0,0,340);
grad.addColorStop(0,'rgba(79,156,247,.32)');
grad.addColorStop(1,'rgba(79,156,247,.02)');

function renderDim(dim){
  const d = DATA[dim];
  const runs = d.rows.reduce(function(s,r){return s+r.runs;},0);
  const avg = d.rows.length ? (d.passRates.reduce(function(s,x){return s+x;},0)/d.rows.length).toFixed(2) : '0';
  const failSum = d.failedList.reduce(function(s,x){return s+x;},0);
  const durSum = d.durations.reduce(function(s,x){return s+x;},0).toFixed(2);
  setNum('cRuns', runs);
  setNum('cAvg', avg+'%');
  setNum('cFail', failSum);
  setNum('cDur', durSum+'s');
  document.getElementById('dimLabel').textContent = DIM_NAMES[dim];
  document.getElementById('dimLabel2').textContent = DIM_NAMES[dim];
  document.getElementById('rowCount').textContent = '共 '+d.rows.length+' 条聚合记录';
  document.getElementById('tbody').innerHTML = buildRows(dim);

  if (!chart){
    chart = new Chart(ctx, {
      data: {
        labels: d.labels,
        datasets: [
          { type:'line', label:'通过率(%)', data:d.passRates, borderColor:'#4f9cf7', backgroundColor:grad, fill:true, yAxisID:'y', tension:.4, borderWidth:3, pointRadius:4, pointHoverRadius:6, pointBackgroundColor:'#fff', pointBorderColor:'#4f9cf7', pointBorderWidth:2 },
          { type:'bar', label:'失败数', data:d.failedList, backgroundColor:'rgba(248,113,113,.5)', yAxisID:'y1', borderRadius:6, borderSkipped:false, maxBarThickness:36 }
        ]
      },
      options: {
        responsive:true,
        interaction:{ mode:'index', intersect:false },
        plugins: {
          tooltip: {
            backgroundColor: cssVar('--chart-tooltip-bg'), titleColor: cssVar('--chart-tooltip-title'), bodyColor: cssVar('--chart-tooltip-body'), padding:12, cornerRadius:10, displayColors:true,
            callbacks: {
              afterBody: function(items){
                const i = items[0].dataIndex;
                const dd = DATA[currentDim];
                return ['总数: '+dd.totals[i]+'  通过: '+dd.passedList[i]+'  跳过: '+dd.skippedList[i], '执行次数: '+dd.runs[i]+'  耗时: '+dd.durations[i]+'s'];
              }
            }
          },
          legend: { labels: { usePointStyle:true, boxWidth:8, padding:18, color: cssVar('--chart-tick') } }
        },
        scales: {
          y: { position:'left', min:0, max:100, grid:{color: cssVar('--chart-grid'), drawTicks:false}, border:{display:false}, ticks:{callback:function(v){return v+'%';}, color: cssVar('--chart-tick')}, title:{display:true, text:'通过率 %', color: cssVar('--chart-tick')} },
          y1: { position:'right', min:0, grid:{display:false}, border:{display:false}, ticks:{stepSize:1, color: cssVar('--chart-tick')}, title:{display:true, text:'失败数', color: cssVar('--chart-tick')} },
          x: { grid:{display:false}, ticks:{maxRotation:30, color: cssVar('--chart-tick')} }
        }
      }
    });
  } else {
    chart.data.labels = d.labels;
    chart.data.datasets[0].data = d.passRates;
    chart.data.datasets[1].data = d.failedList;
    chart.update();
  }
}

renderDim(currentDim);
document.querySelectorAll('.tab').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('.tab').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    currentDim = btn.dataset.dim;
    renderDim(currentDim);
  });
});
</script>
</body>
</html>
"""


def _aggregate_records(records, granularity):
    """按粒度聚合历史记录。

    :param records: 原始记录列表（dict）
    :param granularity: 'daily' | 'weekly' | 'monthly'
    :return: 聚合后的记录列表（按时间正序）
    """
    from collections import OrderedDict

    def _period_key(ts_str):
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return ts_str
        if granularity == 'yearly':
            return dt.strftime("%Y")
        if granularity == 'weekly':
            iso = dt.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        elif granularity == 'monthly':
            return dt.strftime("%Y-%m")
        return dt.strftime("%Y-%m-%d")

    groups = OrderedDict()
    for r in records:
        key = _period_key(r.get('timestamp', ''))
        if key not in groups:
            groups[key] = {
                'period': key,
                'timestamp': r.get('timestamp', ''),
                'runs': 0,
                'total': 0, 'passed': 0, 'failed': 0, 'skipped': 0,
                'duration_sec': 0.0,
                'executor': '',
            }
        g = groups[key]
        g['runs'] += 1
        g['total'] += r.get('total', 0)
        g['passed'] += r.get('passed', 0)
        g['failed'] += r.get('failed', 0)
        g['skipped'] += r.get('skipped', 0)
        g['duration_sec'] += r.get('duration_sec', 0)
        g['timestamp'] = r.get('timestamp', g['timestamp'])
        if r.get('executor'):
            g['executor'] = r['executor']

    result = []
    for g in groups.values():
        g['pass_rate'] = round(g['passed'] / g['total'] * 100, 2) if g['total'] else 0.0
        g['duration_sec'] = round(g['duration_sec'], 2)
        result.append(g)
    return result


def _build_dim_payload(aggregated):
    """将聚合结果转为前端可用的数据包"""
    return {
        "labels": [g['period'] for g in aggregated],
        "passRates": [g['pass_rate'] for g in aggregated],
        "failedList": [g['failed'] for g in aggregated],
        "totals": [g['total'] for g in aggregated],
        "passedList": [g['passed'] for g in aggregated],
        "skippedList": [g['skipped'] for g in aggregated],
        "durations": [g['duration_sec'] for g in aggregated],
        "runs": [g['runs'] for g in aggregated],
        "rows": aggregated,
    }


def generate_summary_report():
    """生成多维度汇总报告（日报/周报/月报 + 全局粒子星云背景 + 环形通过率仪表盘）。

    - 数据来源：run_history.jsonl
    - 输出：api_project/history/summary_report.html
    - 三个维度数据一次性注入，前端 Tab 切换无需请求
    - 全局粒子背景随主题变色（深色加色发光 / 浅色正常混合）
    - 环形仪表盘颜色随最新通过率变化（绿→黄→红）
    """
    if not os.path.exists(HISTORY_FILE):
        logger.info("ℹ️ 暂无历史数据，跳过汇总报告生成")
        return None

    records = []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue
    except Exception as e:
        logger.warning(f"⚠️ 读取历史记录失败: {str(e)}")
        return None

    if not records:
        logger.info("ℹ️ 无有效历史记录，跳过汇总报告生成")
        return None

    daily = _aggregate_records(records, 'daily')
    weekly = _aggregate_records(records, 'weekly')
    monthly = _aggregate_records(records, 'monthly')
    yearly = _aggregate_records(records, 'yearly')

    data_payload = {
        "daily": _build_dim_payload(daily),
        "weekly": _build_dim_payload(weekly),
        "monthly": _build_dim_payload(monthly),
        "yearly": _build_dim_payload(yearly),
    }

    # 全局概要（不随维度变化）
    total_runs = len(records)
    latest_rate = records[-1].get('pass_rate', 0)
    overall_rate = round(sum(r.get('pass_rate', 0) for r in records) / total_runs, 2) if total_runs else 0
    overall_failed = sum(r.get('failed', 0) for r in records)
    overall_duration = round(sum(r.get('duration_sec', 0) for r in records), 2)
    best_rate = max((r.get('pass_rate', 0) for r in records), default=0)
    latest_executor = records[-1].get('executor', '') or '-'
    latest_ts = records[-1].get('timestamp', '')

    meta_payload = {
        "total_runs": total_runs,
        "latest_rate": latest_rate,
        "overall_rate": overall_rate,
        "overall_failed": overall_failed,
        "overall_duration": overall_duration,
        "best_rate": best_rate,
    }

    html = _SUMMARY_HTML_TEMPLATE
    html = html.replace("__DATA__", json.dumps(data_payload, ensure_ascii=False))
    html = html.replace("__META__", json.dumps(meta_payload, ensure_ascii=False))
    html = html.replace("__LATEST_RATE__", str(latest_rate))
    html = html.replace("__LATEST_TS__", latest_ts)
    html = html.replace("__LATEST_EXECUTOR__", latest_executor)
    html = html.replace("__TOTAL_RUNS__", str(total_runs))
    html = html.replace("__BEST_RATE__", str(best_rate))

    summary_path = os.path.join(HISTORY_DIR, 'summary_report.html')
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"🌐 汇总报告已生成: {summary_path}")
        return summary_path
    except Exception as e:
        logger.warning(f"⚠️ 生成汇总报告失败: {str(e)}")
        return None


# ====================== 邮件发送 ======================

def _collect_history_html_reports():
    """收集已生成的历史 HTML 报告；任何异常仅跳过，不影响邮件主流程。"""
    try:
        if not os.path.isdir(HISTORY_DIR):
            return []
        reports = [
            os.path.join(HISTORY_DIR, filename)
            for filename in sorted(os.listdir(HISTORY_DIR))
            if filename.lower().endswith('.html')
            and os.path.isfile(os.path.join(HISTORY_DIR, filename))
        ]
        logger.info(f"📎 检测到 {len(reports)} 份历史 HTML 报告待作为邮件附件")
        return reports
    except Exception as e:
        logger.warning(f"⚠️ 收集历史 HTML 报告失败，已跳过: {e}")
        return []


def send_email_report(html_report_path, allure_zip):
    """根据配置发送邮件，附带主 HTML、Allure 压缩包及历史 HTML 报告。"""
    if not should_send_email():
        if SEND_EMAIL_MODE == "only_failed":
            if not check_test_result():
                logger.info("ℹ️ 全部用例通过，不发送邮件")
            else:
                logger.info("ℹ️ 邮件通知模式：only_failed，但检测到失败，应该发送？请检查逻辑")
        else:
            logger.info("ℹ️ 邮件通知已关闭（SEND_EMAIL=never）")
        return

    files_to_send = []

    if html_report_path and os.path.exists(html_report_path):
        files_to_send.append(html_report_path)
    else:
        logger.warning("HTML 报告不存在，仅发送 Allure 压缩包")

    if allure_zip and os.path.exists(allure_zip):
        files_to_send.append(allure_zip)

    # 历史可视化报告为新增附件：去重后追加，缺失或扫描异常均不影响原附件与发送流程。
    for history_report in _collect_history_html_reports():
        if history_report not in files_to_send:
            files_to_send.append(history_report)

    if files_to_send:
        try:
            EmailService.send(files=files_to_send)
            logger.info("✅ 邮件已发送")
        except Exception as e:
            logger.error(f"❌ 邮件发送失败: {e}")
    else:
        logger.error("❌ 没有可发送的附件，邮件发送失败")


# ====================== 一键后置任务 ======================

def run_post_test_tasks(max_keep_reports=1):
    """
    pytest 执行完毕后的一键后置任务编排：
      1. 按开关启动 Allure 服务（默认关闭）
      2. 生成并压缩 Allure HTML 报告
      3. 清理旧报告
      4. 查找 HTML 报告路径
      5. 发送邮件通知
    """
    # 1. 默认不启动 Allure serve，避免测试完成后自动打开浏览器。
    if AUTO_START_ALLURE:
        allure_server()
    else:
        logger.info("ℹ️ 已跳过 Allure 服务启动（AUTO_START_ALLURE=false）")

    # 2. 压缩 Allure 报告（内含 generate_allure_html_report）
    allure_zip = zip_allure_report()

    # 3. 清理旧报告
    cleanup_old_allure_reports(max_keep=max_keep_reports)

    # 4. 获取 HTML 报告路径
    html_report_path = get_html_report_path()
    if not html_report_path:
        html_report_path = os.path.join(REPORT_DIR_PATH, 'report.html')
        logger.warning(f"⚠️ 未找到任何优先报告，使用默认路径: {html_report_path}")

    # 5. 保存历史记录 + 生成趋势/汇总/性能报告
    save_run_record()
    generate_trend_report()
    generate_summary_report()
    try:
        from api_project.common.performance_manager import generate_performance_report
        generate_performance_report()
    except Exception as e:
        # 性能报告为增强能力，不可影响既有报告、压缩或邮件流程。
        logger.warning(f"⚠️ 生成接口性能报告失败: {e}")

    # 6. 发送邮件
    send_email_report(html_report_path, allure_zip)
