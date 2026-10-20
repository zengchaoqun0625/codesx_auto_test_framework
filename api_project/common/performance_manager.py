# -*- coding: utf-8 -*-
"""接口性能基准：阈值匹配、历史沉淀与可视化报告。"""
import json
import logging
import os
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from api_project import PROJECT_ABS_PATH

logger = logging.getLogger(__name__)
HISTORY_DIR = Path(PROJECT_ABS_PATH) / "history"
PERFORMANCE_HISTORY_FILE = HISTORY_DIR / "performance_history.jsonl"
PERFORMANCE_REPORT_PATH = HISTORY_DIR / "performance_report.html"
PERFORMANCE_CONFIG_FILE = Path(PROJECT_ABS_PATH) / "config" / "performance_thresholds.json"


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_performance_config():
    """读取性能阈值配置；缺失或格式错误时安全降级为关闭状态。"""
    default = {"enabled": False, "default_threshold_sec": 2.0, "rules": []}
    if not PERFORMANCE_CONFIG_FILE.exists():
        return default
    try:
        data = json.loads(PERFORMANCE_CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("根节点必须为对象")
        data.setdefault("enabled", False)
        data["default_threshold_sec"] = _as_float(data.get("default_threshold_sec"), 2.0)
        data["rules"] = data.get("rules") if isinstance(data.get("rules"), list) else []
        return data
    except Exception as exc:
        logger.warning("⚠️ 性能阈值配置读取失败，已跳过性能告警: %s", exc)
        return default


def build_endpoint_key(method, url, fallback_name=""):
    """用 HTTP 方法 + 路径作为稳定接口标识，避免域名/查询参数干扰历史对比。"""
    try:
        path = urlparse(url or "").path or ""
    except Exception:
        path = ""
    if path:
        return f"{(method or 'API').upper()} {path}"
    return fallback_name or "未识别接口"


def resolve_threshold(case, config=None):
    """按规则顺序匹配路径、HTTP 方法或用例名；未命中时使用全局阈值。"""
    config = config or load_performance_config()
    endpoint = case.get("endpoint", "")
    case_name = case.get("name", "")
    method = endpoint.split(" ", 1)[0].upper() if " " in endpoint else ""
    for rule in config.get("rules", []):
        if not isinstance(rule, dict) or rule.get("enabled", True) is False:
            continue
        endpoint_match = str(rule.get("endpoint_contains", "")).strip()
        name_match = str(rule.get("case_name_contains", "")).strip()
        method_match = str(rule.get("method", "")).upper().strip()
        matches_endpoint = bool(endpoint_match and endpoint_match in endpoint)
        matches_name = bool(name_match and name_match in case_name)
        # method 仅作为 endpoint 规则的额外约束；兼容未配置 method 的旧规则。
        method_ok = not method_match or method_match == method
        if (matches_endpoint and method_ok) or matches_name:
            return _as_float(rule.get("threshold_sec"), config["default_threshold_sec"]), str(rule.get("name", "自定义规则"))
    return config["default_threshold_sec"], "默认阈值"


def evaluate_cases(test_results):
    """将 pytest 结果转为接口性能记录，并返回超阈值告警列表。"""
    config = load_performance_config()
    if not config.get("enabled"):
        return [], []

    records, alerts = [], []
    for item in test_results:
        # 仅纳入真正发起过 HTTP 请求的 call 阶段用例；pytest 用例总耗时用于诊断测试开销。
        url = item.get("request_url", "")
        method = item.get("request_method", "")
        if not url and not method:
            continue
        endpoint = build_endpoint_key(method, url, item.get("name", ""))
        elapsed = _as_float(item.get("response_elapsed"), _as_float(item.get("duration"), 0.0))
        threshold, rule_name = resolve_threshold({"endpoint": endpoint, "name": item.get("name", "")}, config)
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "endpoint": endpoint,
            "case_name": item.get("name", ""),
            "duration_sec": round(elapsed, 4),
            "test_duration_sec": round(_as_float(item.get("duration"), 0.0), 4),
            "threshold_sec": threshold,
            "rule_name": rule_name,
            "outcome": item.get("outcome", "unknown"),
            "status_code": item.get("status_code"),
        }
        records.append(record)
        if elapsed > threshold:
            record["slow"] = True
            alerts.append(record)
        else:
            record["slow"] = False
    return records, alerts


def append_performance_records(records):
    if not records:
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with PERFORMANCE_HISTORY_FILE.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("⏱️ 已保存 %s 条接口性能记录", len(records))


def _read_records():
    if not PERFORMANCE_HISTORY_FILE.exists():
        return []
    rows = []
    for line in PERFORMANCE_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def generate_performance_report():
    """生成性能报告：总接口执行耗时趋势 + 各接口最近 10 次耗时对比。"""
    rows = _read_records()
    if not rows:
        logger.info("ℹ️ 暂无接口性能历史，跳过性能报告生成")
        return None

    # 每次执行的时间戳按接口耗时求和；同一秒并发用例归入同一次会话。
    run_map = {}
    endpoint_map = {}
    for row in rows:
        timestamp = row.get("timestamp", "")
        duration = _as_float(row.get("duration_sec"), 0)
        run_map[timestamp] = round(run_map.get(timestamp, 0) + duration, 4)
        endpoint_map.setdefault(row.get("endpoint", "未识别接口"), []).append(row)

    run_items = sorted(run_map.items())[-30:]
    endpoint_items = sorted(endpoint_map.items(), key=lambda pair: pair[0])
    endpoint_payload = []
    for endpoint, samples in endpoint_items:
        samples = sorted(samples, key=lambda item: item.get("timestamp", ""))[-10:]
        endpoint_payload.append({
            "endpoint": endpoint,
            "labels": [item.get("timestamp", "")[5:] for item in samples],
            "durations": [_as_float(item.get("duration_sec"), 0) for item in samples],
            "threshold": max([_as_float(item.get("threshold_sec"), 0) for item in samples] or [0]),
            "slow_count": sum(1 for item in samples if item.get("slow")),
            "latest": _as_float(samples[-1].get("duration_sec"), 0),
        })

    recent_alerts = sorted((row for row in rows if row.get("slow")), key=lambda item: item.get("timestamp", ""), reverse=True)[:20]
    avg_duration = round(sum(_as_float(row.get("duration_sec"), 0) for row in rows) / len(rows), 3)
    html = _PERFORMANCE_TEMPLATE.replace("__RUN_LABELS__", json.dumps([item[0] for item in run_items], ensure_ascii=False)) \
        .replace("__RUN_DURATIONS__", json.dumps([item[1] for item in run_items])) \
        .replace("__ENDPOINT_DATA__", json.dumps(endpoint_payload, ensure_ascii=False)) \
        .replace("__TOTAL_ENDPOINTS__", str(len(endpoint_payload))) \
        .replace("__TOTAL_SAMPLES__", str(len(rows))) \
        .replace("__AVG_DURATION__", str(avg_duration)) \
        .replace("__ALERT_COUNT__", str(len(recent_alerts))) \
        .replace("__ALERT_ROWS__", "".join(
            f"<tr><td>{escape(str(r.get('timestamp','-')))}</td><td>{escape(str(r.get('endpoint','-')))}</td><td>{r.get('duration_sec', 0)}s</td><td>{r.get('threshold_sec', 0)}s</td><td><b>超出 {round(_as_float(r.get('duration_sec'),0)-_as_float(r.get('threshold_sec'),0), 3)}s</b></td></tr>"
            for r in recent_alerts
        ) or "<tr><td colspan='5' class='empty'>暂无超阈值记录</td></tr>")
    PERFORMANCE_REPORT_PATH.write_text(html, encoding="utf-8")
    logger.info("🌐 性能报告已生成: %s", PERFORMANCE_REPORT_PATH)
    return str(PERFORMANCE_REPORT_PATH)


_PERFORMANCE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>接口性能基准报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.149.0/build/three.min.js"></script>
<style>
:root{--bg:#0b1020;--panel:rgba(20,28,49,.88);--border:rgba(114,139,199,.20);--text:#e9efff;--sub:#91a0c5;--grid:rgba(145,160,197,.15);--red:#fb7185;--blue:#5aa8ff;--purple:#a78bfa;--shadow:0 14px 42px rgba(0,0,0,.24)} [data-theme="light"]{--bg:#f4f7fc;--panel:rgba(255,255,255,.90);--border:rgba(48,70,112,.13);--text:#1d2942;--sub:#64748b;--grid:rgba(71,85,105,.16);--shadow:0 12px 34px rgba(38,61,102,.10)} *{box-sizing:border-box}html{background:var(--bg)}body{margin:0;padding:26px 18px 42px;min-height:100vh;font-family:"Segoe UI","Microsoft YaHei",sans-serif;background:radial-gradient(800px 460px at 8% -10%,rgba(90,168,255,.18),transparent 70%),radial-gradient(760px 420px at 94% 5%,rgba(167,139,250,.12),transparent 72%),var(--bg);color:var(--text);transition:background-color .4s,color .4s} [data-theme="light"] body{background:radial-gradient(800px 460px at 8% -10%,rgba(90,168,255,.10),transparent 70%),radial-gradient(760px 420px at 94% 5%,rgba(167,139,250,.08),transparent 72%),var(--bg)}#bgParticles{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}.container{position:relative;z-index:1;max-width:1160px;margin:auto}.theme{position:fixed;right:18px;top:18px;z-index:60;border:1px solid var(--border);background:var(--panel);color:var(--text);border-radius:99px;width:42px;height:42px;cursor:pointer;font-size:18px;box-shadow:var(--shadow);backdrop-filter:blur(12px);transition:transform .2s,background .4s}.theme:hover{transform:scale(1.08)}.hero{display:flex;justify-content:space-between;gap:20px;align-items:end;margin:14px 0 22px;padding:22px 2px}.hero h1{margin:0 0 8px;font-size:30px;letter-spacing:.3px;text-shadow:0 4px 18px rgba(90,168,255,.16)}.hero p{margin:0;color:var(--sub)}.hero-badge{border:1px solid var(--border);background:var(--panel);backdrop-filter:blur(12px);color:var(--sub);border-radius:99px;padding:9px 14px;font-size:12px;box-shadow:var(--shadow)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card,.panel{background:var(--panel);border:1px solid var(--border);border-radius:18px;box-shadow:var(--shadow);backdrop-filter:blur(16px);transition:border-color .3s,box-shadow .3s,transform .25s}.card:hover{transform:translateY(-2px);border-color:rgba(90,168,255,.32)}.card{position:relative;overflow:hidden;padding:19px}.card:before{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:linear-gradient(180deg,var(--blue),var(--purple));opacity:.75}.num{font-size:29px;font-weight:800;margin-bottom:6px}.label{color:var(--sub);font-size:13px}.panel{padding:20px;margin-top:16px}.panel h2{font-size:16px;margin:0 0 16px}.endpoint-toolbar{display:flex;gap:10px;align-items:center;margin-bottom:12px}.endpoint-toolbar select{background:color-mix(in srgb,var(--bg) 82%,transparent);color:var(--text);border:1px solid var(--border);padding:9px 11px;border-radius:10px;min-width:330px;outline:none}.endpoint-toolbar select:focus{border-color:rgba(90,168,255,.55);box-shadow:0 0 0 3px rgba(90,168,255,.12)}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:11px 9px;text-align:left;border-bottom:1px solid var(--border)}th{color:var(--sub);font-weight:600}tbody tr:hover{background:rgba(90,168,255,.055)}.empty{text-align:center;color:var(--sub)}.alert{color:var(--red);text-shadow:0 0 18px rgba(251,113,133,.24)}footer{text-align:center;color:var(--sub);font-size:12px;padding:20px 0 0}@media(max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}.hero{display:block}.hero-badge{display:inline-block;margin-top:14px}.endpoint-toolbar select{min-width:0;width:100%}}
.search-hint{color:var(--sub);font-size:12px;white-space:nowrap}.endpoint-search{position:relative;flex:1;max-width:420px}.endpoint-search input{width:100%;background:color-mix(in srgb,var(--bg) 82%,transparent);color:var(--text);border:1px solid var(--border);padding:9px 12px 9px 34px;border-radius:10px;outline:none;transition:border-color .2s,box-shadow .2s}.endpoint-search input:focus{border-color:rgba(90,168,255,.62);box-shadow:0 0 0 3px rgba(90,168,255,.13)}.endpoint-search:before{content:"⌕";position:absolute;left:12px;top:7px;color:var(--sub);font-size:18px;line-height:1}@media(max-width:760px){.endpoint-toolbar{flex-wrap:wrap}.endpoint-search{flex-basis:100%;max-width:none}.search-hint{order:3}}

/* 手机端：仅调整尺寸、间距和横向浏览；图表/搜索/告警数据逻辑不变。 */
@media(max-width:640px){body{padding:18px 12px 30px}.container{max-width:100%}.theme{top:12px;right:12px;width:38px;height:38px}.hero{display:block;margin:6px 0 16px;padding:16px 2px}.hero h1{font-size:22px;line-height:1.35;padding-right:42px}.hero p{font-size:12px;line-height:1.65}.hero-badge{display:inline-block;margin-top:12px;padding:7px 10px;font-size:11px}.cards{grid-template-columns:1fr 1fr;gap:10px}.card{padding:15px}.num{font-size:25px}.label{font-size:11px}.panel{padding:16px 14px;margin-top:14px;border-radius:15px}.panel h2{font-size:14px;line-height:1.5;margin-bottom:13px}.endpoint-toolbar{align-items:stretch;flex-wrap:wrap;gap:8px}.endpoint-search{flex-basis:100%;max-width:none}.endpoint-toolbar select{width:100%;min-width:0;padding:9px 10px}.search-hint{font-size:11px}.panel canvas{min-height:190px}.panel>div[style]{margin:0 -2px;-webkit-overflow-scrolling:touch}table{min-width:610px;font-size:12px}th,td{padding:9px 8px;white-space:nowrap}footer{padding-top:16px;line-height:1.6}}@media(max-width:420px){.cards{grid-template-columns:1fr}.hero h1{font-size:21px}}
</style></head>
<body><canvas id="bgParticles"></canvas><button class="theme" id="theme" title="切换主题">🌙</button><main class="container"><section class="hero"><div><h1>⏱️ 接口性能基准报告</h1><p>响应耗时按接口路径聚合 · 每个接口保留最近 10 次执行记录</p></div><span class="hero-badge">Three.js 动态性能星云</span></section><section class="cards"><div class="card"><div class="num">__TOTAL_ENDPOINTS__</div><div class="label">已监控接口</div></div><div class="card"><div class="num">__TOTAL_SAMPLES__</div><div class="label">性能采样数</div></div><div class="card"><div class="num">__AVG_DURATION__s</div><div class="label">接口平均响应耗时</div></div><div class="card"><div class="num alert">__ALERT_COUNT__</div><div class="label">历史超阈值告警</div></div></section><section class="panel"><h2>📊 总接口执行耗时对比（最近 30 次）</h2><canvas id="runChart" height="105"></canvas></section><section class="panel"><h2>🔍 单接口近期耗时对比</h2><div class="endpoint-toolbar"><div class="endpoint-search"><input id="endpointSearch" type="search" autocomplete="off" placeholder="搜索方法、路径或告警接口，例如 payment / GET" aria-label="搜索接口"></div><select id="endpointSelect" aria-label="选择接口"></select><span class="search-hint" id="searchHint"></span></div><canvas id="endpointChart" height="120"></canvas></section><section class="panel"><h2>⚠️ 最近超阈值告警</h2><div style="overflow:auto"><table><thead><tr><th>执行时间</th><th>接口</th><th>实际耗时</th><th>阈值</th><th>超出</th></tr></thead><tbody>__ALERT_ROWS__</tbody></table></div></section><footer>Generated by api_project/common/performance_manager.py · Three.js + Chart.js</footer></main><script>
const RUN_LABELS=__RUN_LABELS__, RUN_DURATIONS=__RUN_DURATIONS__, ENDPOINTS=__ENDPOINT_DATA__;
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim()}
function theme(){return document.documentElement.dataset.theme==='light'?'light':'dark'}
const saved=localStorage.getItem('performance_theme');if(saved)document.documentElement.dataset.theme=saved;
const button=document.getElementById('theme');function sync(){button.textContent=theme()==='light'?'☀️':'🌙'}sync();
button.onclick=()=>{const next=theme()==='light'?'dark':'light';document.documentElement.dataset.theme=next;localStorage.setItem('performance_theme',next);sync();if(window.__applyBgTheme)window.__applyBgTheme();[runChart,endpointChart].filter(Boolean).forEach(c=>{c.options.plugins.legend.labels.color=css('--sub');c.options.plugins.tooltip.backgroundColor=css('--panel');c.options.plugins.tooltip.titleColor=css('--text');c.options.plugins.tooltip.bodyColor=css('--sub');c.options.scales.x.ticks.color=css('--sub');c.options.scales.y.ticks.color=css('--sub');c.options.scales.y.grid.color=css('--grid');c.update()})};

/* 全局 3D 粒子星云：上浮、缓旋、鼠标视差，并随深浅主题切换混合方式。 */
(function(){
  const canvas=document.getElementById('bgParticles');
  if(!canvas||typeof THREE==='undefined')return;
  const scene=new THREE.Scene();
  const camera=new THREE.PerspectiveCamera(70,innerWidth/innerHeight,.1,100);camera.position.z=30;
  const renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  function resize(){renderer.setSize(innerWidth,innerHeight,false);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix()}resize();
  const COUNT=520,boxW=48,boxH=30,boxD=20,pos=new Float32Array(COUNT*3),speed=new Float32Array(COUNT);
  for(let i=0;i<COUNT;i++){pos[i*3]=(Math.random()-.5)*boxW;pos[i*3+1]=(Math.random()-.5)*boxH;pos[i*3+2]=(Math.random()-.5)*boxD;speed[i]=.002+Math.random()*.004}
  const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(pos,3));
  const mat=new THREE.PointsMaterial({size:.12,transparent:true,opacity:.55,depthWrite:false,color:0x7da2ff,blending:THREE.AdditiveBlending});
  const points=new THREE.Points(geo,mat);scene.add(points);
  function applyBgTheme(){const light=theme()==='light';if(light){mat.color.set(0x6075b5);mat.opacity=.28;mat.blending=THREE.NormalBlending}else{mat.color.set(0x7da2ff);mat.opacity=.55;mat.blending=THREE.AdditiveBlending}mat.needsUpdate=true}window.__applyBgTheme=applyBgTheme;
  let mx=0,my=0,cmx=0,cmy=0;addEventListener('mousemove',e=>{mx=(e.clientX/innerWidth-.5)*2;my=(e.clientY/innerHeight-.5)*2});
  function animate(){requestAnimationFrame(animate);cmx+=(mx-cmx)*.04;cmy+=(my-cmy)*.04;camera.position.x=cmx*1.4;camera.position.y=-cmy*.9;camera.lookAt(0,0,0);const p=geo.attributes.position.array;for(let i=0;i<COUNT;i++){p[i*3+1]+=speed[i];if(p[i*3+1]>boxH/2)p[i*3+1]=-boxH/2}geo.attributes.position.needsUpdate=true;points.rotation.y=performance.now()*.00005;renderer.render(scene,camera)}
  applyBgTheme();animate();addEventListener('resize',resize);
})();
const base={responsive:true,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:css('--sub'),usePointStyle:true}},tooltip:{backgroundColor:css('--panel'),titleColor:css('--text'),bodyColor:css('--sub')}},scales:{x:{ticks:{color:css('--sub'),maxRotation:30},grid:{display:false}},y:{beginAtZero:true,ticks:{color:css('--sub'),callback:v=>v+'s'},grid:{color:css('--grid')}}}};
const runChart=new Chart(document.getElementById('runChart'),{type:'bar',data:{labels:RUN_LABELS,datasets:[{label:'总接口响应耗时（秒）',data:RUN_DURATIONS,backgroundColor:'rgba(90,168,255,.55)',borderRadius:7}]},options:base});
const select=document.getElementById('endpointSelect'),search=document.getElementById('endpointSearch'),searchHint=document.getElementById('searchHint');
let endpointChart,visibleEndpoints=[];
function endpointLabel(x){return x.endpoint+(x.slow_count?' · '+x.slow_count+' 次告警':'')}
function renderOptions(query,keepEndpoint){const keyword=(query||'').trim().toLowerCase();visibleEndpoints=ENDPOINTS.filter(x=>endpointLabel(x).toLowerCase().includes(keyword));select.innerHTML='';visibleEndpoints.forEach(x=>{const option=new Option(endpointLabel(x),x.endpoint);if(x.endpoint===keepEndpoint)option.selected=true;select.add(option)});searchHint.textContent=keyword?'匹配 '+visibleEndpoints.length+' / '+ENDPOINTS.length+' 个接口':'共 '+ENDPOINTS.length+' 个接口';if(!visibleEndpoints.length){select.add(new Option('未找到匹配接口',''));searchHint.textContent='未找到匹配接口'}draw()}
function draw(){const x=visibleEndpoints.find(item=>item.endpoint===select.value)||visibleEndpoints[0];if(!x){if(endpointChart){endpointChart.destroy();endpointChart=null}return}if(endpointChart)endpointChart.destroy();endpointChart=new Chart(document.getElementById('endpointChart'),{data:{labels:x.labels,datasets:[{type:'line',label:'实际响应耗时（秒）',data:x.durations,borderColor:'#a78bfa',backgroundColor:'rgba(167,139,250,.18)',fill:true,tension:.35,borderWidth:3,pointRadius:4},{type:'line',label:'告警阈值（秒）',data:x.durations.map(()=>x.threshold),borderColor:'#fb7185',borderDash:[7,5],pointRadius:0,borderWidth:2}]},options:base})}
search.addEventListener('input',()=>renderOptions(search.value,select.value));select.addEventListener('change',draw);renderOptions('',ENDPOINTS[0]&&ENDPOINTS[0].endpoint);
</script></body></html>'''
