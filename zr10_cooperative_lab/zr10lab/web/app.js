/**
 * 控制中心交互层。
 * 1. 状态、3D、JPEG 独立限频读取；每条读取链等待上次结束，避免网络请求堆积。
 * 2. 所有设备动作仅交给 Python /api/command 校验执行，页面不直接访问设备。
 * 3. 手动目标、配置初值和实际反馈分开保存，轮询不会覆盖正在输入的目标。
 * 4. 浏览器仅保存当前本机会话令牌，不把令牌放入图片地址或任何外部请求。
 */
const $ = id => document.getElementById(id);
const COLORS = ['#14899c', '#4382e7', '#9a6cdd', '#d79135', '#ce6f9c', '#639855'];
const tokenKey = `zr10-control-token:${location.origin}`;
const hashToken = new URLSearchParams(location.hash.slice(1)).get('token');
let token = hashToken || '';
try {
  if (hashToken) sessionStorage.setItem(tokenKey, hashToken);
  else token = sessionStorage.getItem(tokenKey) || '';
} catch { /* 隐私模式可能禁止存储；本页内存中的令牌仍可正常使用。 */ }
if (hashToken) history.replaceState(null, '', location.pathname + location.search);

const state = {
  snapshot: null, scene: null, schema: {}, selected: null, online: false,
  sceneView: null, config: null, configDirty: false, configDevice: null,
  configSignature: '', deviceSignature: '', modesSignature: '', schemaSignature: '',
  videos: new Map(), hiddenVideos: new Set(), drafts: new Map(), parameterDrafts: new Map(),
  busy: new Set(), alive: true, lastSession: null, sceneError: null,
};
const statusLabels = {idle: '待机', starting: '正在初始化', running: '实验运行中', paused: '实验已暂停', stopped: '实验已结束', error: '运行异常', estopped: '已紧急停止'};
const sourceLabels = {simulation: '仿真反馈', hardware: '设备反馈', measured_pose_calibrated_intrinsics: '实测姿态 + 标定内参', configuration_preview: '配置预览', unavailable: '无反馈', localization_update: '定位测量', prediction: '轨迹预测'};
const reasonLabels = {unavailable: '未收到反馈', disabled: '未参与实验', offline: '设备离线', telemetry_stale: '姿态过期', zoom_unknown: '倍率未确认', zoom_stale: '倍率反馈过期', zoom_unstable: '倍率调整中', calibration_unverified: '标定未确认', configuration_preview: '配置预览', simulation: '仿真几何', measured_pose_calibrated_intrinsics: '实测姿态 + 标定内参'};
const parameterLabels = {yaw_deg: '目标方位 A', pitch_deg: '目标俯仰 E', zoom: '光学倍率', focal_length_mm: '焦距 / mm', focus_direction: '聚焦方向', zoom_direction: '连续变焦', autofocus: '自动对焦', gimbal_mode: '云台模式', photo: '单次拍照', record_toggle: '切换设备录像', hdr_toggle: '切换 HDR', osd: 'OSD 显示', encoding: '视频编码', roll_deg: '横滚角', aperture: '光圈', exposure: '曝光', white_balance: '白平衡', gain: '增益'};
const number = (v, digits = 1) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—';
const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const clone = value => JSON.parse(JSON.stringify(value));
const shortId = id => id?.replace(/^zr10_/, '') || '—';
const color = id => COLORS[Math.max(0, (state.snapshot?.devices || []).findIndex(d => d.id === id)) % COLORS.length];
const activeSession = () => ['starting', 'running', 'paused'].includes(state.snapshot?.status);
const canControl = () => state.online && state.snapshot?.status === 'running';
const selectedDevice = () => state.snapshot?.devices?.find(d => d.id === state.selected);
const selectedConfig = () => state.snapshot?.config?.devices?.find(d => d.id === state.selected);
const sceneDevice = id => state.scene?.devices?.find(d => d.id === id);
const formatTime = seconds => {
  if (!Number.isFinite(seconds)) return '00:00';
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60).toString().padStart(2, '0')}:${(total % 60).toString().padStart(2, '0')}`;
};
const setText = (id, text) => {if ($(id).textContent !== String(text)) $(id).textContent = text;};
const safe = task => async event => {
  try {await task(event);} catch (error) {toast(error.message || String(error), true);}
};

function toast(message, error = false, detail = '') {
  const item = document.createElement('div');
  item.className = `toast${error ? ' error' : ''}`;
  item.textContent = message;
  if (detail) {const small = document.createElement('small'); small.textContent = detail; item.append(small);}
  $('toast-container').append(item);
  setTimeout(() => item.remove(), error ? 10000 : 5500);
  while ($('toast-container').children.length > 5) $('toast-container').firstChild.remove();
}

async function api(path, options = {}) {
  const headers = {'X-ZR10-Token': token, ...(options.body ? {'Content-Type': 'application/json'} : {}), ...(options.headers || {})};
  const response = await fetch(path, {...options, headers, cache: 'no-store', signal: options.signal || AbortSignal.timeout(10000)});
  const body = await response.json().catch(() => ({error: `服务端返回无效数据 (${response.status})`}));
  if (!response.ok || body.ok === false) throw new Error(body.error || `请求失败 (${response.status})`);
  return body;
}

async function command(action, payload = {}, successMessage = '') {
  if (action !== 'heartbeat' && state.busy.has(action)) return null;
  state.busy.add(action);
  renderButtons();
  try {
    const result = await api('/api/command', {method: 'POST', body: JSON.stringify({action, ...payload}), signal: AbortSignal.timeout(action === 'probe' ? 35000 : 12000)});
    if (successMessage) toast(successMessage, false, result.message || '');
    return result;
  } finally {state.busy.delete(action); renderButtons();}
}

function showTab(name, scroll = false) {
  document.querySelectorAll('[data-tab]').forEach(button => {const selected = button.dataset.tab === name; button.classList.toggle('active', selected); button.setAttribute('aria-selected', String(selected));});
  document.querySelectorAll('.tab-content').forEach(panel => panel.classList.toggle('active', panel.id === `tab-${name}`));
  if (scroll) $('tab-' + name).closest('.panel').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function setSelected(id) {
  if (state.selected === id) return;
  saveManualDraft();
  state.selected = id;
  const draft = state.drafts.get(id) || {};
  for (const key of ['yaw', 'pitch', 'zoom']) $('target-' + key).value = draft[key] ?? '';
  state.schemaSignature = '';
  state.sceneView?.select(id);
  renderSelected();
  renderDeviceSelection();
}

function saveManualDraft() {
  if (state.selected) state.drafts.set(state.selected, Object.fromEntries(['yaw', 'pitch', 'zoom'].map(k => [k, $('target-' + k).value])));
}

function renderDeviceStructure(devices) {
  const signature = JSON.stringify(devices.map(d => [d.id, d.enabled]));
  if (signature === state.deviceSignature) return;
  state.deviceSignature = signature;
  $('device-selector').innerHTML = devices.map((d, i) => `<button type="button" role="tab" data-select-device="${escape(d.id)}" style="--device-color:${COLORS[i % COLORS.length]}">${escape(shortId(d.id))}<span class="device-online-dot"></span></button>`).join('');
  $('device-legend').innerHTML = devices.map((d, i) => `<label style="color:${COLORS[i % COLORS.length]}"><input type="checkbox" data-visible-device="${escape(d.id)}" checked><i class="legend-dot" style="background:${COLORS[i % COLORS.length]}"></i>${escape(shortId(d.id))} 号</label>`).join('');
  for (const video of state.videos.values()) {if (video.url) URL.revokeObjectURL(video.url);}
  state.videos.clear();
  $('video-grid').innerHTML = devices.map((d, i) => `<article class="video-card" data-video-card="${escape(d.id)}"><div class="video-frame" data-select-device="${escape(d.id)}"><div class="video-empty"><span class="video-empty-icon" aria-hidden="true">▣</span><span class="video-empty-text">视频预览已关闭</span></div><img alt="${escape(d.id)} 视频预览" hidden><span class="video-overlay-label">${escape(d.id)}</span><span class="video-overlay-info"></span></div><div class="video-caption"><span><i class="legend-dot" style="background:${COLORS[i % COLORS.length]}"></i>${escape(d.id)}</span><label><input type="checkbox" data-video-device="${escape(d.id)}" checked>显示</label></div></article>`).join('');
  document.querySelectorAll('[data-video-card]').forEach(card => state.videos.set(card.dataset.videoCard, {card, image: card.querySelector('img'), url: null, busy: false, last: 0}));
  if (!devices.some(d => d.id === state.selected)) setSelected(devices[0]?.id || null);
}

function renderDeviceSelection() {
  document.querySelectorAll('[data-select-device]').forEach(button => {
    const selected = button.dataset.selectDevice === state.selected;
    if (button.tagName === 'BUTTON') {button.classList.toggle('active', selected); button.setAttribute('aria-selected', String(selected));}
  });
  document.querySelectorAll('[data-video-card]').forEach(card => card.classList.toggle('selected', card.dataset.videoCard === state.selected));
}

function renderModes(snapshot) {
  const modes = snapshot.modes || [];
  const signature = JSON.stringify(modes);
  if (signature !== state.modesSignature) {
    const old = $('mode').value;
    state.modesSignature = signature;
    $('mode').innerHTML = modes.map(m => `<option value="${escape(m.id)}">${escape(m.label || m.id)}</option>`).join('');
    $('mode').value = modes.some(m => m.id === old) ? old : snapshot.mode;
  }
  if (activeSession() || !state.initializedMode) {
    if (snapshot.mode) $('mode').value = snapshot.mode;
    $('environment').value = snapshot.environment || 'sim';
    state.initializedMode = true;
  }
  updateModeDescription();
}

function updateModeDescription() {
  const mode = state.snapshot?.modes?.find(m => m.id === $('mode').value);
  setText('mode-description', mode?.description || '选择任务模式，开始一次可记录、可回放分析的实验。');
  $('armed-label').hidden = $('environment').value !== 'hardware';
}

function renderButtons() {
  const s = state.snapshot;
  const online = state.online && !!s;
  const active = activeSession();
  $('start-button').disabled = !online || active || s?.status === 'estopped' || state.busy.has('start');
  $('start-button').textContent = s?.status === 'starting' ? '正在初始化…' : '▶ 开始实验';
  $('pause-button').disabled = !online || !['running', 'paused'].includes(s?.status) || state.busy.has('pause') || state.busy.has('resume');
  $('pause-button').textContent = s?.status === 'paused' ? '▶ 继续' : 'Ⅱ 暂停';
  $('stop-button').disabled = !online || !active || state.busy.has('stop');
  $('estop-button').disabled = !online || state.busy.has('estop');
  $('estop-button').textContent = s?.status === 'estopped' ? '解除急停' : '紧急停止';
  $('environment').disabled = !online || active;
  $('duration').disabled = !online || active;
  $('armed').disabled = !online || active;
  $('mode').disabled = !online || s?.status === 'starting' || s?.status === 'estopped' || state.busy.has('mode');
  $('reload-policy').disabled = !online || s?.status === 'starting' || state.busy.has('reload_policy');
  $('video-enabled').disabled = !online || state.busy.has('video');
  $('manual-submit').disabled = !canControl() || !selectedDevice() || state.busy.has('manual');
  $('initialize-device').disabled = !canControl() || !selectedDevice() || state.busy.has('initialize');
  $('connect-device').disabled = !canControl() || !selectedDevice() || state.busy.has('connect') || state.busy.has('disconnect');
  $('stop-device').disabled = !canControl() || !selectedDevice() || state.busy.has('stop_device');
  $('release-device').disabled = !canControl() || !selectedDevice()?.manual_override || state.busy.has('release_manual');
  $('copy-feedback').disabled = !selectedDevice()?.feedback || !selectedDevice()?.connected;
  const configLocked = active || s?.status === 'estopped' || !online;
  $('config-lock-note').hidden = !active;
  document.querySelectorAll('.config-content input,.config-content textarea,.config-content select,.config-content button').forEach(el => {
    const unsupported = el.dataset.maskKey && ['unsupported', 'read_only'].includes(state.schema[el.dataset.maskKey]?.support);
    el.disabled = configLocked || !!unsupported;
  });
  $('config-save').disabled = !online || configLocked || state.busy.has('save_config');
  if ($('probe-devices')) $('probe-devices').disabled = !online || active || state.busy.has('probe');
}

function renderBanner() {
  const s = state.snapshot;
  let message = '', danger = false;
  if (!state.online) {message = '与本机服务的连接已中断。请保持 Python 控制中心进程运行；重新连接后不会自动恢复动作。'; danger = true;}
  else if (s?.status === 'estopped') {message = '紧急停止已生效。解除急停不会恢复运动；当前实验仍需点击“继续”，或结束后重新开始。'; danger = true;}
  else if (s?.error) {message = s.error; danger = true;}
  else if (s?.status === 'paused') message = '实验已暂停。设备保持停机，点击“继续”后才恢复任务；暂停期间不能发送手动动作。';
  else if (s?.environment === 'hardware' && (s.devices || []).some(d => d.enabled !== false && !s.config?.devices?.find(c => c.id === d.id)?.calibration_verified)) message = '存在尚未完成标定确认的设备。请在配置中填写实测坐标、安装姿态及内参；未验证设备不会显示为有效实机视场。';
  $('global-banner').hidden = !message;
  $('global-banner').classList.toggle('error', danger);
  $('global-banner').textContent = message;
}

function parameterAvailability(key, device) {
  const spec = state.schema[key] || {};
  if (key === 'encoding') return '需结束实验后在外部修改，并重新校验分辨率、内参与视频延迟';
  if (['read_only', 'unsupported'].includes(spec.support)) return spec.description || '不支持写入';
  if (!state.snapshot?.config?.action_space?.enabled?.includes(key)) return '当前动作空间未开放';
  if (key === 'focal_length_mm') {
    if ((device?.camera?.focal_length_table?.length || 0) < 2) return '需要至少两个实测焦距—倍率标定点';
    if (device?.capabilities?.zoom === false) return '此设备不允许绝对变焦';
  } else if (!['yaw_deg', 'pitch_deg', 'zoom'].includes(key) && device?.capabilities?.[key] !== true) return '设备能力尚未确认';
  if (key === 'zoom' && device?.capabilities?.zoom === false) return '此设备不允许绝对变焦';
  return '';
}

function renderParameters(device) {
  const signature = JSON.stringify([state.selected, state.schema, device?.capabilities, device?.camera?.focal_length_table, state.snapshot?.config?.action_space]);
  if (signature === state.schemaSignature) return;
  state.schemaSignature = signature;
  const entries = Object.entries(state.schema).filter(([key]) => !['yaw_deg', 'pitch_deg', 'zoom'].includes(key));
  $('parameter-count').textContent = `${entries.length} 项`;
  $('parameter-fields').innerHTML = entries.map(([key, spec]) => {
    const unavailable = parameterAvailability(key, device);
    let input;
    if (key === 'gimbal_mode') input = '<select data-parameter-value><option value="lock">锁定 lock</option><option value="follow">跟随 follow</option><option value="fpv">FPV</option></select>';
    else if (['focus_direction', 'zoom_direction'].includes(key)) input = `<select data-parameter-value><option value="0">停止 0</option><option value="-1">${key === 'zoom_direction' ? '缩小' : '负向'} −1</option><option value="1">${key === 'zoom_direction' ? '放大' : '正向'} +1</option></select>`;
    else if (spec.unit === 'bool') input = '<select data-parameter-value><option value="true">是 / 开启 / 执行</option><option value="false">否 / 关闭</option></select>';
    else if (spec.unit === 'object') input = '<textarea data-parameter-value rows="3" placeholder="{ }" spellcheck="false"></textarea>';
    else if (['mm', 'deg', 'f_number', 's', 'dB'].includes(spec.unit)) input = '<input data-parameter-value type="number" step="any" placeholder="输入目标值">';
    else input = '<input data-parameter-value type="text" placeholder="参数值">';
    return `<div class="parameter-field ${unavailable ? 'unavailable' : ''} ${spec.unit === 'object' ? 'span-two' : ''}" data-parameter="${escape(key)}"><label title="${escape(spec.description)}"><input type="checkbox" data-parameter-use ${unavailable ? 'disabled' : ''}>${escape(parameterLabels[key] || key)}</label>${input}<small>${escape(unavailable || spec.description || spec.unit)}</small></div>`;
  }).join('');
  for (const field of $('parameter-fields').children) field.querySelector('[data-parameter-value]').disabled = true;
  for (const [key, field] of [['yaw_deg', 'target-yaw'], ['pitch_deg', 'target-pitch'], ['zoom', 'target-zoom']]) {
    const reason = parameterAvailability(key, device);
    $(field).disabled = !!reason;
    $(field).title = reason || '';
  }
}

function renderSelected() {
  const d = selectedDevice();
  const cfg = selectedConfig();
  const feedback = d?.feedback;
  const geometry = sceneDevice(d?.id);
  const connected = d?.connected === true;
  const source = feedback?.source;
  setText('selected-name', d?.id || '尚未选择设备');
  setText('selected-ip', d ? `${d.ip || cfg?.ip || '—'} : ${d.port || cfg?.port || '—'}` : '—');
  setText('selected-status', d?.enabled === false ? '未启用' : connected ? '反馈在线' : '未连接');
  $('selected-status').className = `small-badge ${connected ? 'success' : ''}`;
  $('selected-dot').className = `status-dot ${connected ? 'running' : ''}`;
  setText('feedback-source', sourceLabels[source] || (source ? '设备反馈' : '无数据'));
  setText('actual-yaw', connected ? number(feedback?.yaw_deg) : '—');
  setText('actual-pitch', connected ? number(feedback?.pitch_deg) : '—');
  const zoomKnown = connected && (source === 'simulation' || feedback?.raw?.zoom_known === true);
  setText('actual-zoom', zoomKnown ? number(feedback?.zoom, 2) : '—');
  setText('actual-roll', connected ? number(feedback?.roll_deg) : '—');
  setText('actual-focal', geometry?.focal_length_mm != null && connected ? `${number(geometry.focal_length_mm, 2)} mm*` : '未知');
  $('actual-focal').title = '毫米焦距仅由实测焦距—倍率表换算，* 表示标定换算值，不是独立测量。';
  setText('feedback-age', connected ? feedback?.age_s != null ? `${number(feedback.age_s * 1000, 0)} ms 前` : '反馈有效' : '无有效反馈');
  setText('ownership-badge', d?.stopped_by_operator ? '本台已停机' : d?.manual_override ? '手动接管' : state.snapshot?.mode === 'manual' ? '手动模式' : activeSession() ? '算法控制' : '待机');
  $('ownership-badge').className = `small-badge ${d?.manual_override ? 'manual' : ''}`;
  const notice = !activeSession() ? '先开始一次实验，再连接和控制设备。初始化将移动至配置初始姿态与倍率。' : !canControl() ? '实验暂停期间禁止发送运动；点击“继续”后可手动接管。' : d?.stopped_by_operator ? '本台已单独停止并保持锁定；“交回算法”后恢复自动控制。' : d?.manual_override ? '本台已由手动接管；“交回算法”后恢复自动分工。' : '发送手动目标后，本台交由手动控制；其余设备继续当前任务。';
  setText('control-notice', notice);
  $('control-notice').classList.toggle('warning', !!d?.manual_override);
  setText('limit-hint', cfg ? `A [${(cfg.yaw_limits_deg || []).join(', ')}]° · E [${(cfg.pitch_limits_deg || []).join(', ')}]° · 倍率 [${(cfg.zoom_limits || []).join(', ')}]×` : '动作受设备限位、能力和动作掩码约束。');
  $('connect-device').textContent = connected ? '断开' : '连接';
  const cmd = d?.command;
  const commandStates = {sent: '已发送', applied: '已应用', acknowledged: '设备已应答', rejected: '已拒绝', failed: '执行失败', expired: '动作过期', held: '保持', simulated: '仿真执行', accepted: '已接收', success: '成功'};
  setText('last-command', cmd ? `${commandStates[cmd.status] || cmd.status}${cmd.ack ? ' · ACK' : ''}${cmd.error ? ' · ' + cmd.error : ''}` : '暂无指令');
  $('last-command').title = cmd?.error || '发送成功或 ACK 不代表已到达目标角度，请同时查看实际反馈。';
  const target = d?.target;
  setText('target-summary', target ? `当前命令：A ${number(target.yaw_deg)}° · E ${number(target.pitch_deg)}° · 倍率 ${number(target.zoom, 2)}×${target.reason ? ' · ' + target.reason : ''}` : '目标命令与实际反馈独立显示。');
  $('target-summary').title = target ? JSON.stringify(target, null, 2) : '';
  renderParameters(cfg);
  renderButtons();
}

function renderTelemetry() {
  const devices = state.snapshot?.devices || [];
  $('telemetry-body').innerHTML = devices.length ? devices.map(d => {
    const f = d.feedback, target = d.target, g = sceneDevice(d.id), cfg = state.snapshot.config.devices.find(c => c.id === d.id);
    const online = d.connected && f;
    const zoomKnown = online && (f.source === 'simulation' || f.raw?.zoom_known === true);
    return `<tr data-device="${escape(d.id)}"><td><span class="table-device"><i class="legend-dot" style="background:${color(d.id)}"></i>${escape(d.id)}</span><span class="table-sub">${escape(d.ip)}</span></td><td><span class="small-badge ${online ? 'success' : ''}">${online ? '在线' : '离线'}</span><span class="table-sub">${d.manual_override ? '手动接管' : activeSession() ? '算法 / 模式控制' : '待机'}</span></td><td>${online ? `${number(f.yaw_deg)}° / ${number(f.pitch_deg)}°` : '—'}</td><td>${number(target?.yaw_deg)}° / ${number(target?.pitch_deg)}°</td><td>${zoomKnown ? number(f.zoom, 2) + '×' : '未确认'}</td><td>${(d.position_m || cfg?.position_m || []).map(v => number(v)).join(', ')}</td><td>${g?.valid ? `${number(g.frustum?.hfov_deg)}° × ${number(g.frustum?.vfov_deg)}°` : `<span title="${escape(g?.reason)}">${escape(reasonLabels[g?.reason] || '不可用')}</span>`}</td><td>${escape(sourceLabels[f?.source] || (f?.source ? '设备反馈' : '无反馈'))}</td><td title="${escape(d.command?.error)}">${escape(d.command?.status || '—')}</td></tr>`;
  }).join('') : '<tr><td class="empty-row" colspan="9">等待配置设备</td></tr>';
}

function renderTracks() {
  const tracks = state.snapshot?.tracks || [];
  setText('track-count', tracks.length);
  $('tracks-body').innerHTML = tracks.length ? tracks.map(t => {
    const p = t.position_m || t.position || [], v = t.velocity_mps || t.velocity || [];
    const speed = v.length === 3 ? Math.hypot(...v) : null;
    const labels = {tentative: '待确认', confirmed: '已确认', coasting: '短时预测'};
    return `<tr><td><strong>${escape(t.track_id)}</strong></td><td>${escape(labels[t.status] || t.status)}</td><td><span class="small-badge ${t.measured ? 'success' : 'warning'}">${t.measured ? '测量更新' : '仅预测'}</span></td>${p.slice(0, 3).map(n => `<td>${number(n, 2)}</td>`).join('')}<td>${number(speed, 2)}</td><td>${escape((t.device_ids || []).join(' · ') || '—')}</td></tr>`;
  }).join('') : '<tr><td class="empty-row" colspan="8">尚未形成定位轨迹 · 需要至少两台设备对同一目标形成有效观测</td></tr>';
  const names = {roi_instant_coverage: '瞬时覆盖', roi_multiview_fraction: '双站共同覆盖', measured_track_fraction: '测量更新比例', localization_count: '本周期定位数', detected_targets: '检测目标数', position_rmse_m: '仿真位置 RMSE / m'};
  const m = state.snapshot?.metrics || {};
  $('metrics-extra').innerHTML = Object.entries(names).filter(([k]) => Number.isFinite(m[k]) && (k !== 'position_rmse_m' || state.snapshot.environment === 'sim')).map(([k, label]) => `<div class="metric-pill">${label}<strong>${k.includes('fraction') || k.includes('coverage') ? number(m[k] * 100) + '%' : number(m[k], 2)}</strong></div>`).join('');
}

function renderEvents() {
  const events = state.snapshot?.events || [];
  setText('event-count', events.length);
  const filter = $('event-filter').value;
  const visible = events.filter(e => filter === 'all' || (filter === 'error' ? /error|reject|fail|timeout|stale|lost|emergency|estop/i.test(e.kind) : /manual|control|mode|start|stop|pause|resume|init|connect|config|policy/i.test(e.kind))).slice(-150).reverse();
  $('events-list').innerHTML = visible.length ? visible.map(e => {
    const t = e.utc || e.time_utc || e.timestamp;
    const elapsedEvent = state.snapshot.environment === 'hardware' && Number.isFinite(e.t) && Number.isFinite(state.snapshot.t) ? e.t - state.snapshot.t + state.snapshot.elapsed_s : e.t;
    const timeText = typeof t === 'string' ? new Date(t).toLocaleTimeString('zh-CN', {hour12: false}) : typeof elapsedEvent === 'number' ? `${number(elapsedEvent, 2)} s` : '—';
    const details = e.payload && Object.keys(e.payload).length ? `<details><summary>查看详情</summary><pre>${escape(JSON.stringify(e.payload, null, 2))}</pre></details>` : '';
    return `<div class="event-row ${/error|reject|fail|estop/i.test(e.kind) ? 'error' : ''}"><span class="event-time">${escape(timeText)}</span><span class="event-kind">${escape(e.kind)}</span><div class="event-message">${escape(e.message || e.payload?.error || e.kind)}${details}</div></div>`;
  }).join('') : '<div class="empty-row">暂无对应事件</div>';
}

function renderSnapshot(snapshot) {
  const first = !state.snapshot;
  state.snapshot = snapshot;
  setText('status-text', statusLabels[snapshot.status] || snapshot.status);
  $('status-dot').className = `status-dot ${snapshot.status}`;
  setText('source-badge', snapshot.environment === 'hardware' ? '真实设备' : '仿真实验');
  $('source-badge').classList.toggle('hardware', snapshot.environment === 'hardware');
  renderModes(snapshot);
  renderDeviceStructure(snapshot.devices || []);
  renderDeviceSelection();
  state.sceneControls?.update(snapshot);
  const enabled = (snapshot.devices || []).filter(d => d.enabled !== false);
  const connected = enabled.filter(d => d.connected);
  setText('metric-devices', connected.length);
  setText('metric-device-total', `/ ${enabled.length} 台`);
  setText('metric-devices-note', connected.length === enabled.length && enabled.length ? snapshot.environment === 'sim' ? '所有仿真智能体反馈在线' : '所有设备姿态反馈在线' : `${enabled.length - connected.length} 台尚无有效反馈`);
  const tracks = snapshot.tracks || [];
  setText('metric-tracks', tracks.length);
  setText('metric-tracks-note', `${tracks.filter(t => t.measured).length} 个测量更新 · ${tracks.filter(t => !t.measured).length} 个预测`);
  setText('metric-coverage', Number.isFinite(snapshot.metrics?.roi_cumulative_coverage) ? number(snapshot.metrics.roi_cumulative_coverage * 100) : '—');
  setText('metric-time', formatTime(snapshot.elapsed_s));
  setText('metric-duration', snapshot.duration_s === 0 ? '/ 持续运行' : '/ ' + formatTime(snapshot.duration_s));
  setText('metric-session', snapshot.session_path ? String(snapshot.session_path).split(/[\\/]/).pop() : '尚未开始记录');
  $('metric-session').title = snapshot.session_path || '';
  setText('recording-path', snapshot.session_path || '数据记录将在开始后启用');
  $('recording-path').title = snapshot.session_path || '';
  $('video-enabled').checked = !!snapshot.video_enabled;
  setText('video-status', snapshot.video_enabled ? '预览已开启' : '预览已关闭');
  $('video-status').classList.toggle('success', !!snapshot.video_enabled);
  setText('last-updated', `刷新于 ${new Date().toLocaleTimeString('zh-CN', {hour12: false})}`);
  if (first) {
    $('duration').value = snapshot.duration_s ?? snapshot.config?.system?.duration_s ?? 60;
    $('frustum-range').value = snapshot.config?.control_center?.frustum_range_m || 200;
    $('armed').checked = snapshot.armed === true;
  }
  if (snapshot.session_path !== state.lastSession) {
    state.sceneView?.clearTrails();
    state.lastSession = snapshot.session_path;
  }
  const configSignature = JSON.stringify(snapshot.config);
  if (state.observedConfigSignature && state.observedConfigSignature !== configSignature) {
    // 坐标/ROI/标定等配置提交后属于新的空间定义，不续接旧坐标系轨迹。
    state.sceneView?.clearTrails();
    state.scene = null;
  }
  state.observedConfigSignature = configSignature;
  if (configSignature !== state.configSignature && (!state.configDirty || first)) loadConfig(snapshot.config);
  renderSelected(); renderTelemetry(); renderTracks(); renderBanner(); renderVideoLabels();
  // 事件详情展开后不因 4 Hz 状态刷新而收起；仅在事件实际改变时更新。
  const eventSignature = JSON.stringify((snapshot.events || []).map(e => [e.id, e.kind, e.message]));
  if (eventSignature !== state.eventSignature) {state.eventSignature = eventSignature; renderEvents();}
}

function renderVideoLabels() {
  for (const [id, video] of state.videos) {
    const device = state.snapshot?.devices?.find(d => d.id === id);
    const feedback = device?.feedback;
    const enabled = state.snapshot?.video_enabled && !state.hiddenVideos.has(id);
    video.card.querySelector('.video-overlay-label').textContent = `${id} · ${state.snapshot?.environment === 'sim' ? '仿真图像' : '设备视频'}`;
    video.card.querySelector('.video-overlay-info').textContent = device?.connected && feedback ? `A ${number(feedback.yaw_deg)}°   E ${number(feedback.pitch_deg)}°` : '';
    if (!enabled) {
      video.image.hidden = true;
      video.card.querySelector('.video-empty').hidden = false;
      video.card.querySelector('.video-empty-text').textContent = '视频预览已关闭';
      if (video.url) {URL.revokeObjectURL(video.url); video.url = null; video.image.removeAttribute('src');}
    }
  }
}

async function updateFrame(id, video) {
  if (video.busy || !state.snapshot?.video_enabled || state.hiddenVideos.has(id) || document.hidden) return;
  video.busy = true;
  try {
    const response = await fetch(`/api/frame/${encodeURIComponent(id)}.jpg`, {headers: {'X-ZR10-Token': token}, cache: 'no-store', signal: AbortSignal.timeout(3500)});
    if (!response.ok) throw new Error(response.status === 404 ? '等待视频帧' : '视频暂不可用');
    const blob = await response.blob();
    if (!state.snapshot?.video_enabled || state.hiddenVideos.has(id)) return;
    const url = URL.createObjectURL(blob);
    const previous = video.url;
    video.url = url;
    video.image.src = url;
    video.image.hidden = false;
    video.card.querySelector('.video-empty').hidden = true;
    if (previous) URL.revokeObjectURL(previous);
  } catch (error) {
    video.image.hidden = true;
    video.card.querySelector('.video-empty').hidden = false;
    video.card.querySelector('.video-empty-text').textContent = error.message === '等待视频帧' ? '等待视频帧' : '视频暂不可用';
  } finally {video.busy = false;}
}

function loadConfig(config) {
  if (!config) return;
  state.config = clone(config);
  state.configSignature = JSON.stringify(config);
  state.configDirty = false;
  $('cfg-full').value = JSON.stringify(state.config, null, 2);
  $('cfg-policy').value = JSON.stringify(state.config.policy || {}, null, 2);
  $('cfg-center').value = JSON.stringify(state.config.control_center || {}, null, 2);
  const current = state.configDevice || state.selected;
  $('config-device').innerHTML = (config.devices || []).map(d => `<option value="${escape(d.id)}">${escape(d.id)}</option>`).join('');
  $('config-device').value = (config.devices || []).some(d => d.id === current) ? current : config.devices?.[0]?.id;
  populateDeviceConfig();
  renderActionMask();
  renderButtons();
}

function renderActionMask() {
  $('action-mask-fields').innerHTML = Object.entries(state.schema).map(([key, spec]) => `<label title="${escape(spec.description)}"><input type="checkbox" data-mask-key="${escape(key)}" ${state.config?.action_space?.enabled?.includes(key) ? 'checked' : ''} ${['unsupported', 'read_only'].includes(spec.support) ? 'disabled' : ''}>${escape(parameterLabels[key] || key)}</label>`).join('');
}

function populateDeviceConfig() {
  state.configDevice = $('config-device').value;
  const d = state.config?.devices?.find(v => v.id === state.configDevice);
  if (!d) return;
  $('cfg-enabled').checked = d.enabled !== false;
  $('cfg-calibrated').checked = d.calibration_verified === true;
  const fields = {ip: d.ip, port: d.port, rtsp: d.rtsp_url, x: d.position_m?.[0], y: d.position_m?.[1], z: d.position_m?.[2], 'mount-roll': d.mount_rpy_deg?.[0], 'mount-pitch': d.mount_rpy_deg?.[1], 'mount-yaw': d.mount_rpy_deg?.[2], 'init-yaw': d.initial_yaw_deg, 'init-pitch': d.initial_pitch_deg, 'init-zoom': d.initial_zoom, 'max-slew': d.max_slew_dps};
  for (const [key, value] of Object.entries(fields)) $('cfg-' + key).value = value ?? '';
  const jsonFields = {'yaw-limits': d.yaw_limits_deg, 'pitch-limits': d.pitch_limits_deg, 'zoom-limits': d.zoom_limits, control: d.control, camera: d.camera, capabilities: d.capabilities};
  for (const [key, value] of Object.entries(jsonFields)) $('cfg-' + key).value = JSON.stringify(value || (key.endsWith('limits') ? [] : {}), null, key.endsWith('limits') ? 0 : 2);
}

function parseJSONField(id, label, type = 'object') {
  let value;
  try {value = JSON.parse($(id).value);} catch (error) {throw new Error(`${label} JSON 格式错误：${error.message}`);}
  if (type === 'array' ? !Array.isArray(value) : value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} 必须是 ${type === 'array' ? 'JSON 数组' : 'JSON 对象'}`);
  return value;
}

function numericField(id, label) {
  const raw = $(id).value.trim(), value = Number(raw);
  if (!raw || !Number.isFinite(value)) throw new Error(`${label} 需要有限数值`);
  return value;
}

async function applyConfig(config) {
  if (activeSession()) throw new Error('请先结束实验再修改配置');
  await command('config', {config}, '配置校验通过，已应用到本次控制中心');
  state.configDirty = false;
  state.configSignature = '';
  loadConfig(config);
}

function bindEvents() {
  document.addEventListener('click', event => {
    const device = event.target.closest('[data-select-device],[data-device]');
    if (device) setSelected(device.dataset.selectDevice || device.dataset.device);
    const tab = event.target.closest('[data-tab]');
    if (tab) showTab(tab.dataset.tab);
    const configTab = event.target.closest('[data-config-tab]');
    if (configTab) {
      document.querySelectorAll('[data-config-tab]').forEach(b => b.classList.toggle('active', b === configTab));
      document.querySelectorAll('[data-config-panel]').forEach(p => p.classList.toggle('active', p.dataset.configPanel === configTab.dataset.configTab));
    }
  });
  $('environment').addEventListener('change', updateModeDescription);
  $('mode').addEventListener('change', safe(async () => {
    updateModeDescription();
    if (activeSession()) {
      const value = $('mode').value;
      try {await command('mode', {mode: value}, '任务模式已切换');} catch (error) {$('mode').value = state.snapshot.mode; throw error;}
    }
  }));
  $('start-button').addEventListener('click', safe(async () => {
    const duration = numericField('duration', '实验时长');
    if (duration < 0) throw new Error('时长不能为负数，0 表示持续运行');
    const environment = $('environment').value;
    if (environment === 'hardware' && !$('armed').checked) throw new Error('请选择“允许实机动作”后启动真实设备实验');
    await command('start', {environment, mode: $('mode').value, duration_s: duration, armed: environment === 'hardware' && $('armed').checked});
  }));
  $('pause-button').addEventListener('click', safe(async () => {await command(state.snapshot.status === 'paused' ? 'resume' : 'pause');}));
  $('stop-button').addEventListener('click', safe(async () => {await command('stop', {}, '实验已结束，过程记录保留');}));
  $('estop-button').addEventListener('click', safe(async () => {
    if (state.snapshot?.status === 'estopped') {$('reset-dialog').showModal(); return;}
    await command('estop', {}, '紧急停止已发送');
  }));
  $('reset-estop').addEventListener('click', safe(async () => {
    await command('reset_estop');
    toast('急停已解除，运动尚未恢复', false, '点击“继续”恢复暂停的实验，或结束后重新开始');
  }));
  $('reload-policy').addEventListener('click', safe(async () => {await command('reload_policy', {}, '算法模块已重新加载');}));
  $('probe-devices')?.addEventListener('click', safe(async () => {
    const result = await command('probe');
    toast('设备查询完成', false, '详情见事件日志；查询不发送运动指令。');
    showTab('events', true);
    if (result?.results) toast(JSON.stringify(result.results), false);
  }));
  $('help-button').addEventListener('click', () => showTab('help', true));
  $('device-settings').addEventListener('click', () => {showTab('configuration', true); $('config-device').value = state.selected; populateDeviceConfig(); document.querySelector('[data-config-tab="device"]').click();});
  $('copy-feedback').addEventListener('click', () => {
    const f = selectedDevice()?.feedback;
    if (!f) return;
    if (!$('target-yaw').disabled) $('target-yaw').value = number(f.yaw_deg, 2);
    if (!$('target-pitch').disabled) $('target-pitch').value = number(f.pitch_deg, 2);
    saveManualDraft();
  });
  for (const key of ['yaw', 'pitch', 'zoom']) $('target-' + key).addEventListener('input', saveManualDraft);
  $('parameter-fields').addEventListener('change', event => {
    const use = event.target.closest('[data-parameter-use]');
    if (use) use.closest('[data-parameter]').querySelector('[data-parameter-value]').disabled = !use.checked;
  });
  $('manual-form').addEventListener('submit', safe(async event => {
    event.preventDefault();
    const payload = {device_id: state.selected};
    for (const [name, id] of [['yaw_deg', 'target-yaw'], ['pitch_deg', 'target-pitch'], ['zoom', 'target-zoom']]) if (!$(id).disabled && $(id).value.trim() !== '') payload[name] = numericField(id, parameterLabels[name]);
    const parameters = {};
    for (const field of $('parameter-fields').children) {
      if (!field.querySelector('[data-parameter-use]').checked) continue;
      const key = field.dataset.parameter, spec = state.schema[key], raw = field.querySelector('[data-parameter-value]').value;
      if (!raw.trim()) throw new Error(`请填写 ${parameterLabels[key] || key}`);
      if (spec.unit === 'bool') parameters[key] = raw === 'true';
      else if (spec.unit === 'object') {try {parameters[key] = JSON.parse(raw);} catch {throw new Error(`${key} 需要有效 JSON 对象`);}}
      else if (['mm', 'deg', '-1/0/1', 'f_number', 's', 'dB'].includes(spec.unit)) {parameters[key] = Number(raw); if (!Number.isFinite(parameters[key])) throw new Error(`${key} 必须为有限数值`);}
      else parameters[key] = raw;
    }
    if (Object.keys(parameters).length) payload.parameters = parameters;
    if (Object.keys(payload).length === 1) throw new Error('请至少输入一个已开放的目标参数');
    await command('manual', payload, '目标已提交，本台进入手动控制');
    // 非幂等动作执行后清除选择，防止下一次角度控制重复触发拍照/录像切换。
    for (const field of $('parameter-fields').children) if (['photo', 'record_toggle', 'hdr_toggle', 'autofocus'].includes(field.dataset.parameter)) {field.querySelector('[data-parameter-use]').checked = false; field.querySelector('[data-parameter-value]').disabled = true;}
  }));
  $('initialize-device').addEventListener('click', safe(async () => {
    const result = await command('initialize', {device_id: state.selected}, '初始化目标已提交');
    if (result?.skipped?.length) toast('部分初始化维度保持不变', false, result.skipped.map(key => parameterLabels[key] || key).join('、') + '：未开放动作空间或尚未确认能力');
  }));
  $('connect-device').addEventListener('click', safe(async () => {await command(selectedDevice()?.connected ? 'disconnect' : 'connect', {device_id: state.selected});}));
  $('stop-device').addEventListener('click', safe(async () => {await command('stop_device', {device_id: state.selected}, '本台已停止并退出算法控制');}));
  $('release-device').addEventListener('click', safe(async () => {await command('release_manual', {device_id: state.selected}, '已交回算法控制');}));
  $('video-enabled').addEventListener('change', safe(async () => {const enabled = $('video-enabled').checked; try {await command('video', {enabled});} catch (e) {$('video-enabled').checked = !enabled; throw e;}}));
  $('video-grid').addEventListener('change', event => {
    if (!event.target.matches('[data-video-device]')) return;
    const id = event.target.dataset.videoDevice;
    event.target.checked ? state.hiddenVideos.delete(id) : state.hiddenVideos.add(id);
    renderVideoLabels();
  });
  $('device-legend').addEventListener('change', event => {if (event.target.dataset.visibleDevice) state.sceneView?.setDeviceVisible(event.target.dataset.visibleDevice, event.target.checked);});
  for (const [id, flag] of [['show-roi', 'roi'], ['show-frusta', 'frusta'], ['show-trails', 'trails']]) $(id).addEventListener('change', () => state.sceneView?.setFlag(flag, $(id).checked));
  $('scene-top').addEventListener('click', () => state.sceneView?.fit(true));
  $('scene-reset').addEventListener('click', () => state.sceneView?.fit());
  $('scene-export').addEventListener('click', () => state.sceneView?.exportImage());
  $('event-filter').addEventListener('change', renderEvents);
  $('config-device').addEventListener('change', populateDeviceConfig);
  document.querySelectorAll('.config-content input,.config-content textarea').forEach(input => input.addEventListener('input', () => {state.configDirty = true;}));
  $('config-refresh').addEventListener('click', () => {loadConfig(state.snapshot?.config); toast('已重新读取服务端配置');});
  $('config-save').addEventListener('click', safe(async () => {
    if (state.configDirty) throw new Error('当前编辑尚未应用，请先点击对应“应用”按钮再保存');
    const result = await command('save_config');
    toast('配置文件已保存', false, result?.path || result?.saved_path || '');
  }));
  $('device-config-form').addEventListener('submit', safe(async event => {
    event.preventDefault();
    const cfg = clone(state.config), d = cfg.devices.find(item => item.id === state.configDevice);
    d.enabled = $('cfg-enabled').checked;
    d.calibration_verified = $('cfg-calibrated').checked;
    d.ip = $('cfg-ip').value.trim(); d.port = numericField('cfg-port', 'UDP 端口'); d.rtsp_url = $('cfg-rtsp').value.trim();
    d.position_m = ['x', 'y', 'z'].map(k => numericField('cfg-' + k, '站点坐标 ' + k));
    d.mount_rpy_deg = ['roll', 'pitch', 'yaw'].map(k => numericField('cfg-mount-' + k, '安装姿态 ' + k));
    d.initial_yaw_deg = numericField('cfg-init-yaw', '初始方位'); d.initial_pitch_deg = numericField('cfg-init-pitch', '初始俯仰'); d.initial_zoom = numericField('cfg-init-zoom', '初始倍率'); d.max_slew_dps = numericField('cfg-max-slew', '最大转速');
    for (const [key, id] of [['yaw_limits_deg', 'yaw-limits'], ['pitch_limits_deg', 'pitch-limits'], ['zoom_limits', 'zoom-limits']]) d[key] = parseJSONField('cfg-' + id, key, 'array');
    for (const key of ['control', 'camera', 'capabilities']) d[key] = parseJSONField('cfg-' + key, key);
    await applyConfig(cfg);
  }));
  $('policy-config-form').addEventListener('submit', safe(async event => {
    event.preventDefault();
    const cfg = clone(state.config);
    cfg.policy = parseJSONField('cfg-policy', '算法配置');
    cfg.control_center = parseJSONField('cfg-center', '控制中心配置');
    cfg.action_space = {...cfg.action_space, enabled: [...document.querySelectorAll('[data-mask-key]:checked')].map(input => input.dataset.maskKey)};
    await applyConfig(cfg);
  }));
  $('full-config-form').addEventListener('submit', safe(async event => {event.preventDefault(); await applyConfig(parseJSONField('cfg-full', '完整配置'));}));
  // 输入 0 表示不设自动结束时间；占位文案与后端语义一致。
  $('duration').min = '0'; $('duration').title = '0 表示持续运行，点击“结束”后停止';
  $('frustum-range').max = '10000';
}

async function pollState() {
  if (!state.alive) return;
  try {
    const snapshot = await api('/api/state');
    const restored = state.snapshot && !state.online;
    state.online = true;
    $('server-status').classList.remove('offline');
    setText('server-status', '本机服务 · 已连接');
    renderSnapshot(snapshot);
    if (restored) toast('本机服务连接已恢复', false, '实验不会自动恢复，请确认状态后操作。');
  } catch (error) {
    state.online = false;
    $('server-status').classList.add('offline');
    setText('server-status', '本机服务 · 连接中断');
    setText('status-text', '服务连接中断');
    $('status-dot').className = 'status-dot error';
    renderButtons(); renderBanner();
    if (!state.snapshot) $('global-banner').textContent = `无法读取本机服务：${error.message}。请从 Python 控制中心输出的地址打开页面。`;
  } finally {if (state.alive) setTimeout(pollState, state.online ? 250 : 1500);}
}

async function pollScene() {
  if (!state.alive) return;
  try {
    if (state.online && !document.hidden) {
      const range = Number($('frustum-range').value);
      if (!Number.isFinite(range) || range <= 0 || range > 10000) return;
      const scene = await api('/api/scene?range_m=' + encodeURIComponent(range));
      state.scene = scene;
      state.sceneView?.update(scene);
      const valid = scene.devices?.filter(d => d.valid).length || 0;
      const preview = scene.devices?.filter(d => d.is_preview || d.frustum?.is_preview).length || 0;
      const simulated = scene.devices?.some(d => d.source === 'simulation');
      setText('scene-source-note', valid ? `${simulated ? '仿真反馈' : '实测姿态 + 标定内参'} · ${valid} 个有效视场` : preview ? '配置预览 · 非实测姿态' : '暂无有效视场 · 等待反馈 / 标定');
      const unavailable = scene.devices?.filter(d => !d.valid && !d.is_preview && d.enabled !== false) || [];
      setText('scene-warning', unavailable.map(d => `${shortId(d.id)}: ${reasonLabels[d.reason] || d.reason}`).join(' · '));
      $('scene-warning').title = $('scene-warning').textContent;
      if (state.sceneView) $('scene-loading').hidden = true;
      renderSelected(); renderTelemetry();
    }
  } catch (error) {
    setText('scene-warning', '空间图暂不可用：' + error.message);
  } finally {if (state.alive) setTimeout(pollScene, 450);}
}

async function heartbeat() {
  if (!state.alive) return;
  try {await api('/api/command', {method: 'POST', body: JSON.stringify({action: 'heartbeat'}), signal: AbortSignal.timeout(2500)});} catch { /* 状态轮询统一显示连接异常，避免心跳弹窗干扰。 */ }
  finally {if (state.alive) setTimeout(heartbeat, 900);}
}

function pollVideos() {
  if (!state.alive) return;
  const fps = Math.max(1, Math.min(10, state.snapshot?.config?.control_center?.preview_fps || 6));
  if (state.online) for (const [id, video] of state.videos) updateFrame(id, video);
  setTimeout(pollVideos, 1000 / fps);
}

async function boot() {
  bindEvents();
  renderButtons();
  try {
    const {SceneView} = await import('/scene_view.js');
    state.sceneView = new SceneView($('scene-container'), setSelected);
    const {SceneControls} = await import('/scene_controls.js');
    state.sceneControls = new SceneControls(state.sceneView, {
      snapshot: () => state.snapshot,
      notify: toast,
      applyRoi: async roi => {
        if (state.configDirty) throw new Error('实验配置中还有尚未应用的编辑，请先应用或重新读取，再修改观测区域');
        const cfg = clone(state.snapshot.config);
        cfg.policy = {...cfg.policy, roi};
        await applyConfig(cfg);
        // 用新配置的实际场景刷新，避免把旧坐标下的轨迹混入新ROI。
        state.scene = await api('/api/scene?range_m=' + encodeURIComponent(Number($('frustum-range').value) || 200));
        state.sceneView.update(state.scene);
      },
    });
    if (state.scene) state.sceneView.update(state.scene);
  } catch (error) {
    $('scene-loading').innerHTML = '<strong>三维渲染暂不可用</strong><span>设备控制和数据表仍可使用。请启用浏览器硬件加速并检查本地 Three.js 资源。</span>';
    state.sceneError = error.message;
  }
  try {const schema = await api('/api/schema'); state.schema = schema.parameters || {}; state.schemaSignature = ''; renderActionMask();} catch (error) {toast('参数能力表读取失败：' + error.message, true);}
  pollState(); pollScene(); heartbeat(); pollVideos();
}

window.addEventListener('pagehide', () => {
  // 由服务端心跳超时暂停，避免 unload 异步动作存在“执行了但无回复”的歧义。
  state.alive = false;
  for (const video of state.videos.values()) if (video.url) URL.revokeObjectURL(video.url);
  state.sceneView?.dispose();
});
window.addEventListener('pageshow', event => {if (event.persisted) location.reload();});
boot();
