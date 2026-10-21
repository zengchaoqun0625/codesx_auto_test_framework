const $ = (selector) => document.querySelector(selector);
let activeRun = null;
let activeDraft = null;
let casePage = 1;
let caseQuery = '';
let allurePresets = [];
const tabMeta = {dashboard:['OVERVIEW','测试概览'], run:['TEST RUNNER','执行测试'], curl:['CURL → CASE','CURL 转用例'], library:['CASE LIBRARY','用例库'], reports:['REPORTS','结果中心'], allure:['ALLURE PRESETS','Allure 预设'], schedule:['SCHEDULER','定时执行'], settings:['CONFIGURATION','配置中心']};

function escapeHtml(value) { const node = document.createElement('div'); node.textContent = value; return node.innerHTML; }
function setRunState(status) { const state = $('#runState'); state.className = `state ${status}`; state.textContent = ({idle:'就绪', running:'执行中', passed:'已通过', failed:'执行失败'})[status] || status; }
function showToast(message, type = 'success') {
  let container = $('#toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    container.setAttribute('aria-live', 'polite');
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  toast.innerHTML = `<span class="toast-icon">${type === 'error' ? '!' : type === 'info' ? 'i' : '✓'}</span><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('visible'));
  window.setTimeout(() => { toast.classList.remove('visible'); window.setTimeout(() => toast.remove(), 220); }, 3200);
}

async function loadCases(page = casePage) {
  const data = await fetch(`/api/cases?page=${page}&page_size=20&q=${encodeURIComponent(caseQuery)}`).then(r => r.json());
  casePage = data.page;
  $('#fileCount').textContent = `${data.total} 个文件`;
  $('#caseList').innerHTML = data.items.map(c => `<div class="case-row"><label class="case-check"><input class="case-select" type="checkbox" value="${escapeHtml(c.file)}" aria-label="选择 ${escapeHtml(c.file)}"></label><div class="case-main"><b>${escapeHtml(c.file)}</b><br><span>${c.count} 条用例 · ${c.updated_at} · ${escapeHtml(c.preset || '未关联预设')}</span></div><button class="text-button run-one-case" data-file="${escapeHtml(c.file)}">执行</button></div>`).join('') || '<p class="notice">没有匹配的 JSON 用例。</p>';
  $('#casePage').textContent = `第 ${data.page} / ${data.pages} 页`;
  $('#casePrev').disabled = data.page <= 1;
  $('#caseNext').disabled = data.page >= data.pages;
  $('#caseSelectAll').checked = false;
  document.querySelectorAll('.run-one-case').forEach(button => button.addEventListener('click', () => beginRun('', [button.dataset.file])));
}

async function loadSettings() {
  const data = await fetch('/api/settings').then(r => r.json());
  $('#configEmailMode').value = data.email_mode;
  $('#configNotificationMode').value = data.notification_mode;
  $('#configScheduler').checked = data.scheduler_enabled;
  $('#apiVerifyTls').checked = data.api_verify_tls;
  const safeFields = {API_HOST:'#apiHost', API_TIMEOUT:'#apiTimeout', TEST_EXECUTOR:'#testExecutor', ALLURE_URL:'#allureUrl', SMTP_HOST:'#smtpHost', SMTP_PORT:'#smtpPort', SMTP_SUBJECT:'#smtpSubject', SMTP_USERNAME:'#smtpUsername', SMTP_RECEIVERS:'#smtpReceivers'};
  Object.entries(safeFields).forEach(([key, selector]) => { const input = $(selector); input.value = (data.values || {})[key] || ''; const label = input.closest('label'); let badge = label.querySelector('.field-status'); if (!badge) { badge = document.createElement('em'); badge.className = 'field-status'; label.insertBefore(badge, input); } const source = (data.value_sources || {})[key] || 'default'; badge.textContent = source === 'configured' ? '已配置' : '默认值'; badge.classList.toggle('configured', source === 'configured'); });
  const secretFields = {api_token:'#apiToken', api_itoken:'#apiIToken', api_cookie:'#apiCookie', smtp_password:'#smtpPassword', feishu_token:'#feishuToken', dingding_token:'#dingdingToken', dingding_secret:'#dingdingSecret', weixin_token:'#weixinToken', phone_call_webhook:'#phoneCallWebhook'};
  Object.entries(secretFields).forEach(([key, selector]) => { const input = $(selector); const label = input.closest('label'); let badge = label.querySelector('.field-status'); if (!badge) { badge = document.createElement('em'); badge.className = 'field-status'; label.insertBefore(badge, input); } const ready = data.secrets[key]; badge.textContent = ready ? '已配置' : '未配置'; badge.classList.toggle('configured', ready); input.placeholder = ready ? '已配置，输入新值替换' : '未配置，输入后保存'; });
  $('#feishuEnabled').checked = data.channels.feishu.enabled;
  $('#dingdingEnabled').checked = data.channels.dingding.enabled;
  $('#weixinEnabled').checked = data.channels.weixin.enabled;
  $('#phoneCallEnabled').checked = data.channels.phone_call.enabled;
  $('#configState').textContent = `Token ${data.api_token ? '已配置' : '未配置'} · Cookie ${data.api_cookie ? '已配置' : '未配置'} · 域名 ${data.api_host_configured ? '已配置' : '默认'}`;
  const channels = data.channels;
  $('#channelState').textContent = `飞书 ${channels.feishu.configured ? '已配置' : '未配置'} · 钉钉 ${channels.dingding.configured ? '已配置' : '未配置'} · 企微 ${channels.weixin.configured ? '已配置' : '未配置'} · 电话 ${channels.phone_call.configured ? '已配置' : '未配置'}`;
}

async function loadDashboard() {
  const data = await fetch('/api/dashboard').then(r => r.json());
  $('#caseCount').textContent = data.case_count;
  $('#passedCount').textContent = data.report.passed;
  $('#failedCount').textContent = data.report.failed;
  $('#reportTime').textContent = `更新于 ${data.report.updated_at}`;
  $('#tokenState').textContent = data.environment.token_configured ? '已配置' : '未配置';
  const scheduler = data.scheduler;
  $('#schedulerState').textContent = data.environment.scheduler_enabled ? `总开关开启 · ${scheduler.enabled}/${scheduler.total} 项任务启用` : `总开关关闭 · ${scheduler.enabled}/${scheduler.total} 项任务启用`;
  $('#emailMode').textContent = data.environment.email_configured ? `${data.environment.email_mode} · 已配置` : `${data.environment.email_mode} · 未配置`;
  const botStates = Object.fromEntries(data.environment.bots.map(bot => [bot.name, bot.enabled ? '已配置' : '未配置']));
  $('#feishuState').textContent = botStates['飞书'] || '未配置'; $('#dingdingState').textContent = botStates['钉钉'] || '未配置'; $('#weixinState').textContent = botStates['企业微信'] || '未配置'; $('#phoneState').textContent = botStates['电话告警'] || '未配置';
  $('#moduleSelect').innerHTML = '<option value="">全部用例</option>' + data.modules.map(m => `<option value="${escapeHtml(m.value)}">${escapeHtml(m.label)}</option>`).join('');
  const links = await fetch('/api/report-links').then(r => r.json());
  $('#reportLinks').innerHTML = links.map(link => `<a class="report-link" href="${link.url}" target="_blank" rel="noopener">${escapeHtml(link.label)}</a>`).join('') || '<p class="notice">尚未生成可打开的报告。</p>';
  await Promise.all([loadCases(), loadSettings(), loadAllurePresets(), loadSchedules()]);
}

async function monitorRun() {
  if (!activeRun) return;
  try {
    const response = await fetch(`/api/runs/${activeRun}`);
    const run = await response.json();
    if (!response.ok) throw new Error(run.error || '无法读取运行状态');
    const authHint = run.status === 'failed' && /\b401\b/.test(run.log) ? '\n\n[提示] 接口返回 401：请在“配置中心”更新 API iToken / Cookie 后再执行。' : '';
    $('#logs').textContent = run.log + authHint;
    $('#logs').scrollTop = $('#logs').scrollHeight;
    setRunState(run.status);
    if (run.status === 'running') setTimeout(monitorRun, 1000);
    else { activeRun = null; showToast(run.status === 'passed' ? '测试执行完成' : '测试执行失败，请查看日志', run.status === 'passed' ? 'success' : 'error'); loadDashboard(); }
  } catch (error) {
    $('#logs').textContent += `\n[状态读取失败] ${error.message || '无法连接本地服务'}`;
    setRunState('failed');
    activeRun = null;
  }
}

async function beginRun(module, files = []) {
  if (activeRun) return;
  if (module instanceof Event || typeof module === 'undefined') module = $('#moduleSelect').value;
  module = typeof module === 'string' ? module : '';
  activateTab('run');
  $('#logs').textContent = '正在提交执行请求…\n';
  setRunState('running');
  try {
    const response = await fetch('/api/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({module, files})});
    const data = await response.json();
    if (!response.ok) {
      $('#logs').textContent = `无法启动测试：${data.error || '请刷新页面后重试。'}`;
      setRunState('failed');
      showToast(data.error || '无法启动测试', 'error');
      return;
    }
    activeRun = data.id;
    $('#logs').textContent = '正在启动…\n';
    monitorRun();
  } catch (error) {
    $('#logs').textContent = `无法连接本地服务：${error.message || '请求未完成'}`;
    setRunState('failed');
    showToast('无法连接本地服务', 'error');
  }
}

function showDraft(data) { activeDraft = data.draft_id; if (data.url_prefix && !$('#urlPrefix').value.trim()) $('#urlPrefix').value = data.url_prefix; const box = $('#curlPreview'); const count = data.cases.length; box.innerHTML = `<p class="parse-success">解析成功：已生成 ${count} 条可预览用例。请检查下方请求数据后再保存。</p>` + data.cases.map(item => `<div class="draft-row"><strong>${escapeHtml(item.filename)}</strong><div class="draft-meta">Allure：<b>${item.allure.mode === 'mapped' ? escapeHtml(item.allure.preset) : '自动兜底分组'}</b></div><pre class="preview-json">${escapeHtml(JSON.stringify(item.case, null, 2))}</pre></div>`).join('') + '<button id="saveDraft" class="primary save-draft">确认保存用例 <b>↗</b></button>'; $('#saveDraft').addEventListener('click', saveDraft); }
async function previewCurl() { const box = $('#curlPreview'); box.innerHTML = '<p class="notice">正在解析 cURL，请稍候…</p>'; try { const files = $('#curlFiles').files; let response; if (files.length) { const form = new FormData(); [...files].forEach(file => form.append('files', file)); form.append('url_prefix', $('#urlPrefix').value); response = await fetch('/api/curl/upload-preview', {method:'POST', body:form}); } else { response = await fetch('/api/curl/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({curl:$('#curlInput').value, url_prefix:$('#urlPrefix').value})}); } const data = await response.json(); if (!response.ok) { box.innerHTML = `<p class="notice">解析失败：${escapeHtml(data.error || '未知错误')}</p>`; showToast(data.error || 'cURL 解析失败', 'error'); return; } if (!Array.isArray(data.cases) || !data.cases.length) { box.innerHTML = '<p class="notice">未解析到请求。请确认内容以 <code>curl</code> 开头，或填写接口地址前缀。</p>'; showToast('未解析到可用请求', 'info'); return; } showDraft(data); showToast(`已解析 ${data.cases.length} 条用例`); } catch (error) { box.innerHTML = `<p class="notice">解析请求未完成：${escapeHtml(error.message || '无法连接本地服务')}</p>`; showToast('cURL 解析请求未完成', 'error'); } }
async function saveDraft() { if (!activeDraft) return; const box = $('#curlPreview'); box.innerHTML = '<p class="notice">正在保存、同步性能阈值并验证收集结果…</p>'; const response = await fetch('/api/curl/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({draft_id:activeDraft})}); const data = await response.json(); activeDraft = null; if (!response.ok) { box.innerHTML = `<p class="notice">保存失败：${escapeHtml(data.error || '验证未通过')}</p>`; return; } box.innerHTML = `<p class="notice">已保存：${data.saved.map(escapeHtml).join('、')}。性能阈值：${data.performance_synced ? '已同步' : '同步失败'}；用例收集：${data.collect_ok ? '通过' : '失败'}。</p>`; $('#curlInput').value = ''; $('#curlFiles').value = ''; casePage = 1; loadDashboard(); }
function presetOptions(includeBlank = true) { return `${includeBlank ? '<option value="">全部用例 / 取消关联</option>' : ''}${allurePresets.map(item => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.key)} · ${escapeHtml(item.sub_suite)}</option>`).join('')}`; }
async function loadAllurePresets() { const data = await fetch('/api/allure-presets').then(r => r.json()); allurePresets = data.items || []; $('#casePresetSelect').innerHTML = presetOptions(); $('#schedulePreset').innerHTML = presetOptions(); $('#presetList').innerHTML = allurePresets.map(item => `<div class="preset-row"><div><b>${escapeHtml(item.key)}</b><br><span>${escapeHtml(item.title)} · ${escapeHtml(item.sub_suite)} · ${escapeHtml(item.severity)}</span></div><button class="text-button delete-preset" data-preset="${escapeHtml(item.key)}">删除</button></div>`).join('') || '<p class="notice">暂无 Allure 预设。</p>'; document.querySelectorAll('.delete-preset').forEach(button => button.addEventListener('click', () => deletePreset(button.dataset.preset))); }
async function savePreset() { const payload = {key:$('#presetKey').value.trim(), title:$('#presetTitle').value.trim(), sub_suite:$('#presetSubSuite').value.trim(), severity:$('#presetSeverity').value, suite:$('#presetSuite').value.trim(), epic:$('#presetEpic').value.trim(), tags:$('#presetTags').value.split(',').map(tag => tag.trim()).filter(Boolean)}; try { const response = await fetch('/api/allure-presets', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}); const data = await response.json(); if (!response.ok) { $('#presetList').insertAdjacentHTML('afterbegin', `<p class="notice">保存失败：${escapeHtml(data.error || '未知错误')}</p>`); showToast(data.error || '预设保存失败', 'error'); return; } ['#presetKey','#presetTitle','#presetSubSuite','#presetSuite','#presetEpic','#presetTags'].forEach(selector => $(selector).value = ''); await loadAllurePresets(); loadCases(); showToast('Allure 预设已保存'); } catch { showToast('预设保存请求未完成', 'error'); } }
async function deletePreset(preset) { try { const response = await fetch(`/api/allure-presets/${encodeURIComponent(preset)}`, {method:'DELETE'}); if (!response.ok) { showToast('删除预设失败', 'error'); return; } await loadAllurePresets(); loadCases(); showToast('Allure 预设已删除'); } catch { showToast('删除预设请求未完成', 'error'); } }
function selectedCaseFiles() { return [...document.querySelectorAll('.case-select:checked')].map(input => input.value); }
async function applyCasePreset() { const files = selectedCaseFiles(); if (!files.length) { showToast('请先选择至少一个用例', 'info'); return; } try { const response = await fetch('/api/cases/allure', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({files, preset:$('#casePresetSelect').value})}); if (!response.ok) { showToast('应用预设失败', 'error'); return; } await loadCases(); showToast('预设已应用到所选用例'); } catch { showToast('应用预设请求未完成', 'error'); } }
async function loadSchedules() { const data = await fetch('/api/schedules').then(r => r.json()); const runtime = data.runtime || {}; $('#schedulerRuntime').textContent = runtime.running ? `调度器运行中 · PID ${runtime.pid}` : '调度器未运行'; $('#runScheduler').disabled = Boolean(runtime.running); $('#runScheduler').textContent = runtime.running ? '调度器运行中' : '运行调度器'; $('#stopScheduler').disabled = !runtime.running; $('#scheduleList').innerHTML = (data.items || []).map(job => `<div class="preset-row"><div><b>${escapeHtml(job.name)}</b><br><span>${escapeHtml(job.cron)} · ${job.enabled ? '已启用' : '已停用'} · ${escapeHtml((job.env || {}).RUN_MODULE || '全部用例')}</span></div><div class="row-actions"><button class="text-button toggle-schedule" data-id="${escapeHtml(job.id || '')}">${job.enabled ? '关闭' : '开启'}</button><button class="text-button delete-schedule" data-id="${escapeHtml(job.id || '')}">删除</button></div></div>`).join('') || '<p class="notice">暂无定时任务。</p>'; document.querySelectorAll('.delete-schedule').forEach(button => button.addEventListener('click', () => deleteSchedule(button.dataset.id))); document.querySelectorAll('.toggle-schedule').forEach(button => button.addEventListener('click', () => toggleSchedule(button.dataset.id))); return data; }
async function reconcileScheduler(scheduleData) { const runtime = scheduleData.runtime || {}; const hasEnabledJobs = (scheduleData.items || []).some(job => job.enabled); if (!hasEnabledJobs) { if (runtime.running) await stopScheduler(false); return; } if (runtime.running) await stopScheduler(false); await runScheduler(false); }
async function saveSchedule() { const payload = {name:$('#scheduleName').value.trim(), cron:$('#scheduleCron').value.trim(), preset:$('#schedulePreset').value, timeout_sec:$('#scheduleTimeout').value, enabled:$('#scheduleEnabled').checked}; try { const response = await fetch('/api/schedules', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}); const data = await response.json(); if (!response.ok) { $('#scheduleList').insertAdjacentHTML('afterbegin', `<p class="notice">保存失败：${escapeHtml(data.error || '未知错误')}</p>`); showToast(data.error || '定时任务保存失败', 'error'); return; } $('#scheduleName').value = ''; $('#scheduleCron').value = ''; const schedules = await loadSchedules(); if (data.enabled) await reconcileScheduler(schedules); showToast('定时任务已保存'); } catch { showToast('定时任务保存请求未完成', 'error'); } }
async function deleteSchedule(id) { try { const response = await fetch(`/api/schedules/${encodeURIComponent(id)}`, {method:'DELETE'}); if (!response.ok) { showToast('删除定时任务失败', 'error'); return; } const schedules = await loadSchedules(); await reconcileScheduler(schedules); showToast('定时任务已删除'); } catch { showToast('删除定时任务请求未完成', 'error'); } }
async function toggleSchedule(id) { try { const response = await fetch(`/api/schedules/${encodeURIComponent(id)}/toggle`, {method:'POST'}); const data = await response.json(); if (!response.ok) { showToast(data.error || '切换定时任务失败', 'error'); return; } const schedules = await loadSchedules(); await reconcileScheduler(schedules); showToast(data.enabled ? '定时任务已开启' : '定时任务已关闭'); } catch { showToast('切换定时任务请求未完成', 'error'); } }
async function runScheduler(notify = true) { try { const response = await fetch('/api/scheduler/run', {method:'POST'}); const data = await response.json(); if (!response.ok && response.status !== 409) { $('#schedulerRuntime').textContent = `启动失败：${data.error || '未知错误'}`; if (notify) showToast(data.error || '调度器启动失败', 'error'); return false; } await loadSchedules(); if (notify) showToast(response.status === 409 ? '调度器已在运行中' : `调度器已启动（PID ${data.pid}）`, 'info'); return true; } catch { if (notify) showToast('调度器启动请求未完成', 'error'); return false; } }
async function stopScheduler(notify = true) { try { const response = await fetch('/api/scheduler/stop', {method:'POST'}); const data = await response.json(); if (!response.ok && response.status !== 409) { if (notify) showToast(data.error || '调度器停止失败', 'error'); return false; } await loadSchedules(); if (notify) showToast(response.status === 409 ? '调度器当前未运行' : '调度器已停止', 'info'); return response.ok; } catch { if (notify) showToast('调度器停止请求未完成', 'error'); return false; } }
async function saveSettings() {
  const payload = {email_mode: $('#configEmailMode').value, notification_mode: $('#configNotificationMode').value, scheduler_enabled: $('#configScheduler').checked, api_verify_tls: $('#apiVerifyTls').checked, feishu_enabled: $('#feishuEnabled').checked, dingding_enabled: $('#dingdingEnabled').checked, weixin_enabled: $('#weixinEnabled').checked, phone_call_enabled: $('#phoneCallEnabled').checked};
  const fields = {api_token:'#apiToken', api_itoken:'#apiIToken', api_cookie:'#apiCookie', api_host:'#apiHost', api_timeout:'#apiTimeout', test_executor:'#testExecutor', allure_url:'#allureUrl', smtp_host:'#smtpHost', smtp_port:'#smtpPort', smtp_subject:'#smtpSubject', smtp_username:'#smtpUsername', smtp_password:'#smtpPassword', smtp_receivers:'#smtpReceivers', feishu_token:'#feishuToken', dingding_token:'#dingdingToken', dingding_secret:'#dingdingSecret', weixin_token:'#weixinToken', phone_call_webhook:'#phoneCallWebhook'};
  Object.entries(fields).forEach(([key, selector]) => { const value = $(selector).value.trim(); if (value) payload[key] = value; });
  const button = $('#saveSettings'); const originalText = button.innerHTML;
  button.disabled = true; button.textContent = '正在保存…'; $('#configState').textContent = '正在保存本地配置…';
  try {
    const response = await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) { $('#configState').textContent = `保存失败：${data.error || '未知错误'}`; showToast(data.error || '本地配置保存失败', 'error'); return; }
    await loadDashboard();
    $('#configState').textContent = '已保存；配置将在下次执行时生效';
    showToast('本地配置已保存');
  } catch (error) {
    $('#configState').textContent = `保存失败：${error.message || '无法连接本地服务'}`;
    showToast('本地配置保存失败', 'error');
  } finally {
    button.disabled = false; button.innerHTML = originalText;
  }
}

$('#runAll').addEventListener('click', () => { $('#moduleSelect').value = ''; beginRun(); }); $('#runSelected').addEventListener('click', () => beginRun()); $('#copyLog').addEventListener('click', async () => { try { await navigator.clipboard.writeText($('#logs').textContent); $('#copyLog').textContent = '已复制'; showToast('运行日志已复制'); setTimeout(() => $('#copyLog').textContent = '复制', 1200); } catch { showToast('复制失败，请手动选择日志', 'error'); } }); $('#previewCurl').addEventListener('click', previewCurl); $('#caseSearchButton').addEventListener('click', () => { caseQuery = $('#caseSearch').value; casePage = 1; loadCases().then(() => showToast('用例列表已更新', 'info')).catch(() => showToast('搜索失败', 'error')); }); $('#caseSearch').addEventListener('keydown', e => { if (e.key === 'Enter') { caseQuery = e.target.value; casePage = 1; loadCases().then(() => showToast('用例列表已更新', 'info')).catch(() => showToast('搜索失败', 'error')); } }); $('#casePrev').addEventListener('click', () => loadCases(casePage - 1)); $('#caseNext').addEventListener('click', () => loadCases(casePage + 1)); $('#caseSelectAll').addEventListener('change', event => { document.querySelectorAll('.case-select').forEach(input => input.checked = event.target.checked); showToast(event.target.checked ? '已选择本页全部用例' : '已取消选择本页用例', 'info'); }); $('#runSelectedCases').addEventListener('click', () => { const files = selectedCaseFiles(); if (files.length) beginRun('', files); else showToast('请先选择至少一个用例', 'info'); }); $('#applyCasePreset').addEventListener('click', applyCasePreset); $('#savePreset').addEventListener('click', savePreset); $('#saveSchedule').addEventListener('click', saveSchedule); $('#saveSettings').addEventListener('click', saveSettings);
function activateTab(tab) { document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.tab === tab)); document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === tab)); const [kicker, title] = tabMeta[tab]; $('#pageKicker').textContent = kicker; $('#pageTitle').textContent = title; window.scrollTo({top:0, behavior:'smooth'}); }
function setTheme(theme) { document.body.dataset.theme = theme === 'current' ? '' : theme; localStorage.setItem('api-console-theme', theme); document.querySelectorAll('[data-theme-choice]').forEach(button => button.classList.toggle('selected', button.dataset.themeChoice === theme)); }
function closeThemeMenu() { $('#themeMenu').hidden = true; $('#themeToggle').setAttribute('aria-expanded', 'false'); }
const savedTheme = localStorage.getItem('api-console-theme') || 'current'; setTheme(savedTheme);
$('#themeToggle').addEventListener('click', () => { const opening = $('#themeMenu').hidden; $('#themeMenu').hidden = !opening; $('#themeToggle').setAttribute('aria-expanded', String(opening)); });
document.querySelectorAll('[data-theme-choice]').forEach(button => button.addEventListener('click', () => { setTheme(button.dataset.themeChoice); closeThemeMenu(); showToast('界面配色已切换', 'info'); }));
document.addEventListener('click', event => { if (!event.target.closest('.theme-switcher')) closeThemeMenu(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeThemeMenu(); });
const schedulePanel = document.querySelector('.config-panel:has(#scheduleName)');
const allurePanel = document.querySelector('.config-panel:has(#presetKey)');
if (allurePanel) {
  const allureTab = document.createElement('section');
  allureTab.className = 'tab-panel allure-tab';
  allureTab.dataset.panel = 'allure';
  allureTab.innerHTML = '<div class="settings-intro"><p class="eyebrow">ALLURE PRESETS</p><h2>Allure 预设</h2><p>维护接口的报告分组、标题、严重级别和标签。为用例关联预设后，统一参数化入口会在执行时应用对应分组。</p></div>';
  document.querySelector('[data-panel="settings"]').before(allureTab);
  allureTab.appendChild(allurePanel);
  document.querySelector('.nav-item[data-tab="library"]').insertAdjacentHTML('beforebegin', '<button class="nav-item" data-tab="allure"><span aria-hidden="true">◉</span>Allure 预设</button>');
}
if (schedulePanel) {
  const scheduleTab = document.createElement('section');
  scheduleTab.className = 'tab-panel schedule-tab';
  scheduleTab.dataset.panel = 'schedule';
  scheduleTab.innerHTML = '<div class="settings-intro"><p class="eyebrow">SCHEDULER</p><h2>定时执行</h2><p>开启任务后会自动启动或重载调度器；关闭最后一个任务会停止调度器。定时调度总开关须先在“配置中心”保存。</p><div class="scheduler-runtime"><span id="schedulerRuntime" class="subtle">读取中…</span><button id="runScheduler" class="primary">运行调度器</button><button id="stopScheduler" class="secondary" disabled>停止调度器</button></div></div>';
  document.querySelector('[data-panel="settings"]').before(scheduleTab);
  scheduleTab.appendChild(schedulePanel);
  document.querySelector('.nav-item[data-tab="library"]').insertAdjacentHTML('beforebegin', '<button class="nav-item" data-tab="schedule"><span aria-hidden="true">▣</span>定时执行</button>');
  $('#runScheduler').addEventListener('click', runScheduler);
  $('#stopScheduler').addEventListener('click', () => stopScheduler());
}
document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', () => activateTab(item.dataset.tab))); document.querySelectorAll('[data-open-tab]').forEach(item => item.addEventListener('click', () => activateTab(item.dataset.openTab)));
document.querySelector('.metrics').insertAdjacentHTML('afterend', '<article class="panel overview-card conversion-card"><div><p class="eyebrow">CURL CONVERTER</p><h3>推荐使用 AI 全流程操作：一句话即可完成 cURL 转测试用例。</h3><p>大致步骤：把抓取的接口放到项目内任意 txt 文件内，告诉 AI “帮我转换 curl 文件并生成测试用例”。</p></div></article>');
// Keep the save action next to the preview action so it remains reachable
// even when a conversion contains many requests.
const curlSaveButton = document.createElement('button');
curlSaveButton.id = 'saveDraftFixed';
curlSaveButton.className = 'secondary wide save-draft';
curlSaveButton.type = 'button';
curlSaveButton.disabled = true;
curlSaveButton.innerHTML = '确认保存用例 <b>↗</b>';
$('#previewCurl').after(curlSaveButton);

function setDraftSaveEnabled(enabled) {
  curlSaveButton.disabled = !enabled;
}

function showDraft(data) {
  activeDraft = data.draft_id;
  if (data.url_prefix && !$('#urlPrefix').value.trim()) $('#urlPrefix').value = data.url_prefix;
  const box = $('#curlPreview');
  const count = data.cases.length;
  box.innerHTML = `<p class="parse-success">解析成功：已生成 ${count} 条可预览用例。请检查请求数据后，使用上方“确认保存用例”。</p>` + data.cases.map(item => `<div class="draft-row"><strong>${escapeHtml(item.filename)}</strong><div class="draft-meta">Allure：<b>${item.allure.mode === 'mapped' ? escapeHtml(item.allure.preset) : '自动兜底分组'}</b></div><pre class="preview-json">${escapeHtml(JSON.stringify(item.case, null, 2))}</pre></div>`).join('');
  setDraftSaveEnabled(true);
}

async function saveDraft() {
  if (!activeDraft) return;
  const box = $('#curlPreview');
  curlSaveButton.disabled = true;
  box.innerHTML = '<p class="notice">正在保存、同步性能阈值并验证收集结果…</p>';
  try {
    const response = await fetch('/api/curl/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({draft_id:activeDraft})});
    const data = await response.json();
    activeDraft = null;
    if (!response.ok) {
      box.innerHTML = `<p class="notice">保存失败：${escapeHtml(data.error || '未写入用例文件')}</p>`;
      showToast(data.error || '用例保存失败', 'error');
      return;
    }
    const validation = data.collect_ok ? '用例收集：通过' : '用例已保存，但收集校验失败；请查看下方日志。';
    const savedText = data.saved.length ? `已保存：${data.saved.map(escapeHtml).join('、')}。` : '没有新增用例。';
    const skippedText = data.skipped && data.skipped.length ? `已忽略重复请求：${data.skipped.map(escapeHtml).join('、')}。` : '';
    box.innerHTML = `<p class="notice">${savedText}${skippedText}性能阈值：${data.performance_synced ? '已同步' : '同步失败'}；${validation}</p>${data.collect_ok ? '' : `<pre class="preview-json">${escapeHtml(data.collect_log || '未返回校验日志')}</pre>`}`;
    $('#curlInput').value = '';
    $('#curlFiles').value = '';
    casePage = 1;
    loadDashboard();
    showToast(data.saved.length ? '用例已保存' : '没有新增用例', data.saved.length ? 'success' : 'info');
  } catch (error) {
    box.innerHTML = `<p class="notice">保存请求未完成：${escapeHtml(error.message || '无法连接本地服务')}</p>`;
    setDraftSaveEnabled(Boolean(activeDraft));
    showToast('用例保存请求未完成', 'error');
  }
}

curlSaveButton.addEventListener('click', saveDraft);
loadDashboard().catch(() => { $('#logs').textContent = '控制台加载失败，请检查本地服务是否已启动。'; });
