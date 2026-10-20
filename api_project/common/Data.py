'''
Auther      : alvin.zeng
Email       : zengjiangtaoasd@gmail.com
createTime  : 2024/11/26 7:58
fileName    : Data.py

优化说明：
- 报告样式：Linear / 开发者工具美学（浅色背景 + 玻璃拟态 + 3D 球体 + 工程网格）。
- 新增 HTTP 状态码列，自动从 Allure 结果 JSON 中提取（支持多种路径，优先从附件文件中读取）。
- 用例名称自动截断项目前缀（"api_project.testcase."），只保留接口名，节约手机宽度。
- 3D 球体动画改为大幅上下浮动，视觉更活泼。
'''
import glob
import os
import json
import re
from datetime import datetime
from jsonpath import jsonpath

from .. import DATA_DIR_PATH
from ..common.Network import get_ip, get_local_ip
from ..config.allure_config import Allure


def _extract_status_code(content: dict, file_path: str) -> str:
    """从 Allure 结果 JSON 中提取 HTTP 状态码（增强版，优先读取附件文件）。

    Args:
        content: result.json 解析后的字典
        file_path: result.json 的完整路径（用于定位附件文件）
    Returns:
        HTTP 状态码字符串，例如 '200'，获取失败返回 '—'
    """
    # 1. 优先从 attachments 中查找名为“响应状态码”的附件
    attachments = content.get('attachments', [])
    for att in attachments:
        if att.get('name') == '响应状态码':
            source = att.get('source')
            if source:
                # 附件文件与 result.json 位于同一目录
                base_dir = os.path.dirname(file_path)
                attachment_path = os.path.join(base_dir, source)
                try:
                    with open(attachment_path, 'r', encoding='utf-8') as f:
                        code = f.read().strip()
                        if code:
                            return code
                except Exception:
                    pass

    # 2. 回退：在 steps 字段中遍历查找状态码相关字段
    steps = content.get('steps', [])
    if steps:
        # 从后往前遍历，通常 HTTP 响应步骤在最后
        for step in reversed(steps):
            if not isinstance(step, dict):
                continue
            for field in ('statusCode', 'status', 'code', 'responseCode', 'httpCode'):
                val = step.get(field)
                if val is not None:
                    if isinstance(val, str):
                        match = re.search(r'\d{3}', val)
                        if match:
                            return match.group()
                    elif isinstance(val, (int, float)):
                        return str(int(val))
        # 如果后向遍历没找到，再前向遍历一次
        for step in steps:
            if isinstance(step, dict):
                for field in ('statusCode', 'status', 'code', 'responseCode', 'httpCode'):
                    val = step.get(field)
                    if val:
                        if isinstance(val, str):
                            match = re.search(r'\d{3}', val)
                            if match:
                                return match.group()
                        elif isinstance(val, (int, float)):
                            return str(int(val))

    # 3. 尝试从根级字段提取
    for path in ('$.statusCode', '$.responseCode', '$.httpCode'):
        try:
            vals = jsonpath(content, path)
            if vals and vals[0] is not None:
                return str(vals[0])
        except Exception:
            pass

    # 4. 兜底：从 attachment 文件名猜测（例如 "response-200.json"）
    if attachments:
        for att in attachments:
            if isinstance(att, dict):
                name = att.get('name', '') or att.get('source', '')
                match = re.search(r'(?<!\d)(\d{3})(?!\d)', name)
                if match:
                    return match.group()

    return '—'


def _shorten_case_name(raw: str) -> str:
    """截断项目前缀，只保留接口/方法名。"""
    # 移除 "xx.testcase." 前缀
    if '.testcase.' in raw:
        raw = raw.split('.testcase.', 1)[-1]
    # 如果仍然很长（>55 字符），取最后一段
    if len(raw) > 55:
        parts = raw.rsplit('.', 1)
        raw = parts[-1] if len(parts) > 1 else raw
    return raw


def get_all_case_result():
    '''获取所有api运行结果:名称、时间、状态、HTTP状态码
    {'用例名称': {'time': 时间, 'status': 状态, 'status_code': http状态码}}'''
    all_result = {}
    all_result_files = glob.iglob(os.path.join(DATA_DIR_PATH, '*-result.json'), recursive=True)
    for file_path in all_result_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
            # 字段缺失/损坏时跳过单个文件，不中断整封邮件（jsonpath 返回空列表时 [0] 会抛 IndexError）
            raw_names = jsonpath(content, '$..fullName')
            stops = jsonpath(content, '$..stop')
            starts = jsonpath(content, '$..start')
            statuses = jsonpath(content, '$..status')
            if not (raw_names and stops and starts and statuses):
                continue
            # 优先用 name（参数化子用例的真实名称，如 "#1支付订单统计接口测试'payOrder_payCount.json"），
            # fullName 兜底（参数化测试的 fullName 全部相同，直接用会导致子用例被合并只剩 1 条）
            names = jsonpath(content, '$..name')
            if names:
                # name 形如 "#1xxx"：# 开头的数字是参数化序号，去掉；其余部分即用例名称
                raw_name = re.sub(r'^#\d+\s*', '', str(names[0]))
            else:
                # fullName 形如 "path#test_api"：取 # 前部分
                raw_name = str(raw_names[0]).split('#')[0]
            case_name = _shorten_case_name(raw_name)
            case_time = float((int(stops[0]) - int(starts[0])) / 1000)
            case_status = statuses[0]
            # 传入 file_path 以读取附件
            status_code = _extract_status_code(content, file_path)
            # 同名用例仅保留首次记录
            if case_name not in all_result:
                all_result[case_name] = {
                    'time': case_time,
                    'status': case_status,
                    'status_code': status_code,
                }
        except Exception:
            # 单个结果文件解析失败不影响整体报告
            continue
    return all_result


# ---------------- Linear 风格样式（浅色主题） ----------------
_REPORT_CSS = r"""
:root{
  --bg:#F7F8FA;
  --surface:rgba(255,255,255,0.65);
  --border:rgba(16,24,40,0.08);
  --text:#1B1E24;
  --text-2:#5C6470;
  --text-3:#8A919C;
  --accent:#5E6AD2;
  --accent-2:#7C89F0;
  --success:#4CB782;
  --danger:#EB5757;
  --warn:#D4A52A;
  --grid-line:rgba(16,24,40,.05);
  --glow-a:rgba(94,106,210,.30);
  --glow-b:rgba(138,99,210,.24);
  --glow-c:rgba(96,165,250,.26);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  background:var(--bg);
  color:var(--text);
  line-height:1.5;
  -webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
  position:relative;
  min-height:100vh;
  padding:32px 20px;
  overflow-x:hidden;
}
.mono{font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace}

/* ---------- 背景：极光 Orb + 网格 + 3D 球体 ---------- */
.bg-stage{position:fixed;inset:0;z-index:-1;overflow:hidden;background:var(--bg)}
.bg-grid{
  position:absolute;inset:0;
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size:52px 52px;
  -webkit-mask-image:radial-gradient(ellipse 90% 62% at 50% 0%, #000 25%, transparent 78%);
          mask-image:radial-gradient(ellipse 90% 62% at 50% 0%, #000 25%, transparent 78%);
}
.orb{position:absolute;border-radius:50%;filter:blur(90px);will-change:transform}
.orb-a{width:580px;height:580px;top:-190px;left:6%;
  background:radial-gradient(circle, var(--glow-a), transparent 65%);
  animation:drift-a 26s ease-in-out infinite alternate}
.orb-b{width:500px;height:500px;top:8%;right:-130px;
  background:radial-gradient(circle, var(--glow-b), transparent 65%);
  animation:drift-b 32s ease-in-out infinite alternate}
.orb-c{width:440px;height:440px;bottom:-170px;left:30%;
  background:radial-gradient(circle, var(--glow-c), transparent 65%);
  animation:drift-c 24s ease-in-out infinite alternate}
@keyframes drift-a{to{transform:translate(90px,60px) scale(1.12)}}
@keyframes drift-b{to{transform:translate(-70px,90px) scale(.92)}}
@keyframes drift-c{to{transform:translate(60px,-70px) scale(1.08)}}
.sphere{position:absolute;border-radius:50%;will-change:transform;
  background:
    radial-gradient(circle at 30% 26%, rgba(255,255,255,.85), rgba(255,255,255,0) 38%),
    radial-gradient(circle at 72% 82%, rgba(0,0,0,.42), transparent 55%),
    linear-gradient(135deg, #8A90FF, #5E6AD2 55%, #3D44A8);
  box-shadow:
    inset -12px -18px 40px rgba(0,0,0,.35),
    inset 8px 10px 24px rgba(255,255,255,.25),
    0 30px 60px -18px rgba(94,106,210,.30);
  animation:bounce 5s ease-in-out infinite;
}
.sphere-a{width:150px;height:150px;top:130px;right:10%}
.sphere-b{width:84px;height:84px;top:360px;left:5%;opacity:.92;animation-delay:-2.5s}
@keyframes bounce{
  0%,100%{transform:translateY(35px) rotate(-3deg)}
  25%{transform:translateY(-50px) rotate(0deg)}
  50%{transform:translateY(15px) rotate(3deg)}
  75%{transform:translateY(-65px) rotate(-1deg)}
}
@media (prefers-reduced-motion: reduce){
  .orb,.sphere{animation:none!important}
}

/* ---------- 玻璃拟态卡片 ---------- */
.container{
  max-width:900px;margin:0 auto;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:16px;
  backdrop-filter:blur(18px) saturate(140%);
  -webkit-backdrop-filter:blur(18px) saturate(140%);
  box-shadow:0 1px 2px rgba(16,24,40,.05),0 16px 40px -20px rgba(16,24,40,.14);
  overflow:hidden;position:relative;
}

/* ---------- 头部 ---------- */
.header{
  padding:28px 28px 22px;
  border-bottom:1px solid var(--border);
  background:linear-gradient(180deg, rgba(94,106,210,0.06), transparent);
}
.header .eyebrow{
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:0.18em;
  text-transform:uppercase;color:var(--accent-2);margin-bottom:8px;
}
.header h1{font-size:22px;font-weight:650;letter-spacing:-0.01em;color:var(--text)}
.header .sub{color:var(--text-2);font-size:13px;margin-top:6px}

/* ---------- 摘要 ---------- */
.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border)}
.stat{background:rgba(247,248,250,0.65);padding:20px 18px;text-align:center}
.stat-value{font-family:'JetBrains Mono',monospace;font-size:30px;font-weight:600;line-height:1;letter-spacing:-0.02em}
.stat-value.passed{color:var(--success)}
.stat-value.failed{color:var(--danger)}
.stat-value.time{color:var(--accent-2)}
.stat-label{margin-top:8px;font-size:12px;color:var(--text-2);letter-spacing:0.02em}

/* ---------- 表格 ---------- */
.table-wrap{padding:8px 12px 4px;overflow-x:auto}
.results-table{width:100%;border-collapse:collapse;font-size:13px}
.results-table thead th{
  text-align:left;font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;
  color:var(--text-3);padding:12px 14px;border-bottom:1px solid var(--border);white-space:nowrap;
}
.results-table tbody td{padding:11px 14px;border-bottom:1px solid rgba(16,24,40,0.05);vertical-align:middle}
.results-table tbody tr{transition:background .15s ease}
.results-table tbody tr:hover{background:rgba(16,24,40,0.04)}
.case-name{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--text);word-break:break-word}
.case-time{font-family:'JetBrains Mono',monospace;color:var(--text-2);text-align:right;white-space:nowrap}
.case-code{text-align:center}
.case-status{text-align:right;white-space:nowrap}
/* 列宽——桌面端 */
.results-table th.case-name{width:52%}
.results-table th.case-time{width:13%}
.results-table th.case-code{width:11%}
.results-table th.case-status{width:24%}

/* 状态码标签 */
.code-tag{display:inline-block;font-family:'JetBrains Mono',monospace;font-size:12px;
  font-weight:600;padding:2px 10px;border-radius:6px;line-height:1.4}
.code-2xx{color:#1a7d4c;background:rgba(76,183,130,.12)}
.code-3xx{color:#8d6e00;background:rgba(210,165,40,.12)}
.code-4xx{color:#b02828;background:rgba(235,87,87,.10)}
.code-5xx{color:#9b1b1b;background:rgba(235,87,87,.16)}
.code-unk{color:var(--text-3);background:rgba(16,24,40,.05)}

/* ---------- 状态徽标 ---------- */
.badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:500;border:1px solid transparent}
.badge .dot{width:6px;height:6px;border-radius:50%}
.badge.passed{color:var(--success);background:rgba(76,183,130,0.12);border-color:rgba(76,183,130,0.25)}
.badge.passed .dot{background:var(--success);box-shadow:0 0 8px rgba(76,183,130,0.7)}
.badge.failed{color:var(--danger);background:rgba(235,87,87,0.10);border-color:rgba(235,87,87,0.25)}
.badge.failed .dot{background:var(--danger);box-shadow:0 0 8px rgba(235,87,87,0.6)}

/* ---------- 底部链接 ---------- */
.footer{
  padding:20px 24px 24px;border-top:1px solid var(--border);text-align:center;
  background:linear-gradient(0deg, rgba(94,106,210,0.04), transparent);
}
.footer .links{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.report-link{
  display:inline-flex;align-items:center;gap:8px;padding:10px 16px;border-radius:10px;
  font-size:13px;font-weight:550;color:#fff;text-decoration:none;
  background:linear-gradient(180deg,#6E79E0,#5E6AD2);
  border:1px solid rgba(255,255,255,0.18);
  box-shadow:0 1px 0 rgba(255,255,255,0.20) inset, 0 6px 18px rgba(94,106,210,0.30);
  transition:transform .15s ease, box-shadow .15s ease, filter .15s ease;
}
.report-link:hover{transform:translateY(-1px);filter:brightness(1.06);
  box-shadow:0 1px 0 rgba(255,255,255,0.25) inset, 0 10px 26px rgba(94,106,210,0.45)}
.report-link svg{width:15px;height:15px}
.note{margin-top:14px;font-size:11px;color:var(--text-3);line-height:1.6}

/* ---------- 移动端适配 ---------- */
@media (max-width:640px){
  body{padding:16px 12px}
  .header{padding:22px 18px 18px}
  .header h1{font-size:19px}
  .stat{padding:16px 8px}
  .stat-value{font-size:24px}
  .stat-label{font-size:11px}
  .results-table{font-size:12px}
  .results-table thead th,.results-table tbody td{padding:9px 8px}
  .case-name{font-size:11.5px}
  .code-tag{font-size:11px;padding:2px 7px}
  .badge{font-size:11px;padding:2px 8px;gap:4px}
  .footer .links{flex-direction:column}
  .report-link{width:100%;justify-content:center}
  .orb-a{width:340px;height:340px;top:-120px}
  .orb-b{width:280px;height:280px;right:-80px}
  .orb-c{width:260px;height:260px;bottom:-100px}
  .sphere-a{width:100px;height:100px;top:100px;right:5%}
  .sphere-b{width:56px;height:56px;top:280px;left:3%}
}
@media (max-width:380px){
  .stat-value{font-size:20px}
  .case-time{padding-right:4px}
}
"""

_REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>自动化测试报告</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>__CSS__</style>
</head>
<body>
<div class="bg-stage" aria-hidden="true">
  <div class="bg-grid"></div>
  <div class="orb orb-a"></div>
  <div class="orb orb-b"></div>
  <div class="orb orb-c"></div>
  <div class="sphere sphere-a"></div>
  <div class="sphere sphere-b"></div>
</div>
<div class="container">
  <header class="header">
    <div class="eyebrow">Automation · Test Report</div>
    <h1>自动化测试报告</h1>
    <div class="sub">Pytest 自动化测试执行摘要 · 生成于 <span class="mono">__GENERATED_AT__</span></div>
  </header>
  <section class="summary">
    <div class="stat">
      <div class="stat-value passed">__PASSED__</div>
      <div class="stat-label">通过用例</div>
    </div>
    <div class="stat">
      <div class="stat-value failed">__FAILED__</div>
      <div class="stat-label">失败用例</div>
    </div>
    <div class="stat">
      <div class="stat-value time">__TOTAL__</div>
      <div class="stat-label">总耗时</div>
    </div>
  </section>
  <div class="table-wrap">
    <table class="results-table">
      <thead>
        <tr>
          <th class="case-name">用例名称</th>
          <th class="case-time">执行时间</th>
          <th class="case-code">状态码</th>
          <th class="case-status">状态</th>
        </tr>
      </thead>
      <tbody>
__ROWS__
      </tbody>
    </table>
  </div>
  <footer class="footer">
    <div class="links">__LINKS__</div>
    <div class="note">* 附件为 pytest 的 HTML 报告<br>* 局域网报告仅在内网有效，公网报告仅在公网服务器有效</div>
  </footer>
</div>
</body>
</html>"""


def get_case_result_html():
    '''生成 Linear 风格（开发者工具美学）的测试报告 HTML，用于邮件发送。
    :return: 格式化后的 HTML 字符串
    '''
    case_results = get_all_case_result()
    passed_count = sum(1 for v in case_results.values() if v['status'] == 'passed')
    failed_count = sum(1 for v in case_results.values() if v['status'] == 'failed')
    total_time = sum(v['time'] for v in case_results.values())

    rows = []
    for name, v in case_results.items():
        is_passed = v['status'] == 'passed'
        badge_cls = 'passed' if is_passed else 'failed'
        badge_text = '通过' if is_passed else '失败'

        # 状态码分类
        code = str(v.get('status_code', '—'))
        if code == '—' or not code:
            code_cls = 'code-unk'
        elif code.startswith('2'):
            code_cls = 'code-2xx'
        elif code.startswith('3'):
            code_cls = 'code-3xx'
        elif code.startswith('4'):
            code_cls = 'code-4xx'
        elif code.startswith('5'):
            code_cls = 'code-5xx'
        else:
            code_cls = 'code-unk'

        rows.append(
            '<tr>'
            f'<td class="case-name" title="{name}">{name}</td>'
            f'<td class="case-time">{v["time"]:.2f}s</td>'
            f'<td class="case-code"><span class="code-tag {code_cls}">{code}</span></td>'
            f'<td class="case-status"><span class="badge {badge_cls}"><span class="dot"></span>{badge_text}</span></td>'
            '</tr>'
        )
    rows_html = '\n'.join(rows)

    lan_ip = get_local_ip()
    port = Allure.PORT
    icon = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
            '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>')
    links = (
        f'<a class="report-link" href="http://{lan_ip}:{port}">{icon}查看局域网 Allure 报告</a>'
        f'<a class="report-link" href="https://zx6122129mx.vicp.fun">{icon}查看公网 Allure 报告</a>'
    )

    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M')

    html = _REPORT_TEMPLATE
    html = html.replace('__CSS__', _REPORT_CSS)
    html = html.replace('__PASSED__', str(passed_count))
    html = html.replace('__FAILED__', str(failed_count))
    html = html.replace('__TOTAL__', f'{total_time:.2f}s')
    html = html.replace('__ROWS__', rows_html)
    html = html.replace('__LINKS__', links)
    html = html.replace('__GENERATED_AT__', generated_at)
    return html