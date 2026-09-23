'use strict';
const $ = id => document.getElementById(id);
const state = { base: 'http://localhost:8000', towers: [], incidents: [], incident: null, towerId: null, options: [], simulation: null, choice: null, busy: false, version: 0, timer: null };
const labels = { critical:'Критический', high:'Высокий', medium:'Средний', investigating:'Диагностика', open:'Открыт', pending:'Ожидает выполнения', network_congestion:'Перегрузка сети', weak_coverage:'Слабое покрытие', normal:'Норма', degraded:'Ухудшение связи', coverage_issue:'Проблема покрытия', completed:'Выполнено' };
const tr = value => labels[value] || value || '—';
const fmt = value => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('ru-RU').format(value) : '—';
const money = value => `${fmt(value)} ₸`;
function el(tag, text, className) { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (className) item.className = className; return item; }
function say(text) { $('notice').textContent = text; }
function fail(error) { $('error').textContent = error.message || String(error); $('error').hidden = false; }
function clearError() { $('error').hidden = true; }
function budget() { const value = $('budget').valueAsNumber; return Number.isSafeInteger(value) && value >= 0 ? value : null; }
function syncControls() {
  ['refresh','analyze','load-order'].forEach(id => $(id).disabled = state.busy);
  $('simulate').disabled = state.busy || !state.incident || budget() === null;
  $('create-order').disabled = state.busy || !state.choice || !state.simulation || state.simulation.budget !== budget();
  document.querySelectorAll('.incident,.marker,.option button').forEach(button => button.disabled = state.busy || button.dataset.unavailable === 'true');
  $('connection-form').querySelector('button').disabled = state.busy;
}
async function run(task) {
  if (state.busy) return;
  clearError(); state.busy = true; syncControls();
  try { await task(); } catch (error) { fail(error); }
  finally { state.busy = false; syncControls(); }
}
async function api(path, payload) {
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(state.base + path, { method:payload === undefined ? 'GET' : 'POST', headers:payload === undefined ? {} : {'Content-Type':'application/json'}, body:payload === undefined ? undefined : JSON.stringify(payload), signal:controller.signal });
    const data = await response.json().catch(() => { throw new Error('API вернул ответ, который не является JSON.'); });
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Ошибка API ${response.status}: ${JSON.stringify(data.detail || data)}`);
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('API не ответил за 45 секунд. При создании work order проверьте результат на сервере перед повтором.');
    if (error instanceof TypeError) throw new Error('Нет соединения с API. Проверьте адрес, запуск backend и порт frontend 5173.');
    throw error;
  } finally { clearTimeout(timeout); }
}
function invalidate() {
  state.version++; state.simulation = null; state.options = []; state.choice = null;
  $('options').replaceChildren(); $('confirmation').hidden = true;
  $('simulation-status').textContent = state.incident ? 'Бюджет или инцидент изменён. Нужен новый расчёт.' : 'Выберите инцидент для расчёта.';
  syncControls();
}
function renderIncidents() {
  $('incident-count').textContent = String(state.incidents.length);
  $('incidents').replaceChildren();
  if (!state.incidents.length) $('incidents').append(el('p','Инцидентов пока нет. Запустите анализ.','empty'));
  for (const incident of state.incidents) {
    const button = el('button',undefined,`incident${incident.id === state.incident?.id ? ' selected' : ''}`);
    button.setAttribute('aria-pressed',String(incident.id === state.incident?.id));
    const row = el('span',undefined,'row'); row.append(el('strong',incident.id),el('span',tr(incident.priority),`priority-${incident.priority}`));
    button.append(row,el('span',tr(incident.probable_cause)),el('small',`Вышка #${incident.tower_id} · ${fmt(incident.complaints_count)} жалоб`));
    button.onclick = () => run(() => selectIncident(incident.id)); $('incidents').append(button);
  }
}
function renderMap() {
  const container = $('map'); container.replaceChildren();
  const towers = state.towers.filter(t => Number.isFinite(t.lat) && Number.isFinite(t.lon));
  if (!towers.length) { container.append(el('p','Нет вышек с координатами.','empty')); return; }
  const lats = towers.map(t=>t.lat), lons = towers.map(t=>t.lon);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats), minLon = Math.min(...lons), maxLon = Math.max(...lons);
  for (const tower of towers) {
    const button = el('button',`#${tower.id}`,`marker ${tower.status || ''}${tower.id === state.towerId ? ' active' : ''}`);
    button.style.left = `${maxLon === minLon ? 50 : 12 + (tower.lon-minLon)/(maxLon-minLon)*76}%`;
    button.style.top = `${maxLat === minLat ? 50 : 85 - (tower.lat-minLat)/(maxLat-minLat)*70}%`;
    button.setAttribute('aria-label',`Вышка ${tower.id}, ${tower.area}, ${tr(tower.status)}`);
    button.onclick = () => { state.towerId = tower.id; renderMap(); renderTower(); syncControls(); };
    container.append(button);
  }
}
function renderTower() {
  const tower = state.towers.find(t=>t.id === state.towerId); const root = $('tower-details'); root.replaceChildren();
  if (!tower) return;
  root.append(el('strong',`Вышка #${tower.id} · ${tower.area}`),el('p',`${tower.network_type || '—'} · ${tr(tower.status)} · нагрузка ${fmt(tower.current_load_pct)}% · радиус покрытия ${fmt(tower.coverage_radius_km)} км`));
}
function renderDetail() {
  const item = state.incident; $('incident-id').textContent = item?.id || 'Не выбран'; const root = $('incident-details'); root.replaceChildren();
  if (!item) { root.append(el('p','Выберите инцидент из списка.')); return; }
  root.append(el('strong',tr(item.probable_cause)),el('p',item.reason || 'Причина не указана.'));
  const metrics = el('div',undefined,'metrics');
  for (const [label,value] of [['Жалобы',item.complaints_count],['Затронуто пользователей',item.affected_users]]) { const card = el('div',undefined,'metric'); card.append(el('span',label),el('strong',fmt(value))); metrics.append(card); }
  root.append(metrics);
  const list = el('dl'); for (const [key,value] of [['Статус',tr(item.status)],['Команда',item.assigned_team || '—'],['Вышка',`#${item.tower_id}`]]) list.append(el('dt',key),el('dd',value)); root.append(list);
}
function clearAnalysis() { $('agent-mode').textContent = 'Режим анализа ещё не определён.'; $('agent-steps').replaceChildren(el('li','Для выбранного инцидента анализ ещё не запускался.','muted')); }
function renderAnalysis(data) {
  const modes = {openai:'Анализ OpenAI с вызовом инструментов',demo:'Демо-режим: Python-инструменты без OpenAI',demo_fallback:'Резервный демо-режим: OpenAI недоступен'};
  $('agent-mode').textContent = modes[data.agent_mode] || 'Режим анализа не указан API.';
  $('agent-steps').replaceChildren();
  for (const step of data.agent_steps || []) $('agent-steps').append(el('li',`${tr(step.status)}${step.tool ? ` · ${step.tool}` : ''}: ${step.message || ''}`));
  if (!$('agent-steps').children.length) $('agent-steps').append(el('li','API не вернул журнал действий.','muted'));
}
function renderOrder(root, order) {
  root.replaceChildren(el('h3',`Заказ ${order.id}`),el('p',order.task || '—'),el('p',`${order.team || '—'} · ${money(order.budget_kzt)} · ${tr(order.status)}`)); root.hidden = false;
}
function setIncident(item) {
  state.incident = item; state.towerId = item?.tower_id ?? null; invalidate();
  $('work-order').hidden = true; clearAnalysis(); renderIncidents(); renderDetail(); renderMap(); renderTower();
  const tower = state.towers.find(t=>t.id === state.towerId); $('area').value = tower?.area || '';
}
async function selectIncident(id) {
  const data = await api(`/incidents/${encodeURIComponent(id)}`); if (!data.incident) throw new Error('API не вернул incident.');
  setIncident(data.incident); await simulate();
}
async function load() {
  clearTimeout(state.timer); say('Загружаем сеть…'); $('connection-status').textContent = 'подключение';
  state.incident = null; state.towers = []; state.incidents = []; state.towerId = null; invalidate(); renderIncidents(); renderDetail(); renderMap(); renderTower(); clearAnalysis(); $('work-order').hidden = true; $('saved-order').hidden = true;
  try {
    const [towers, incidents] = await Promise.all([api('/towers'), api('/incidents')]);
    if (!Array.isArray(towers.items) || !Array.isArray(incidents.items)) throw new Error('Ожидались массивы items в ответах API.');
    state.towers = towers.items; state.incidents = incidents.items; renderIncidents(); renderMap();
    $('connection-status').textContent = 'подключено'; say('Данные сети обновлены.');
    if (state.incidents.length) await selectIncident(state.incidents[0].id);
  } catch(error) { $('connection-status').textContent = 'ошибка загрузки'; say(''); throw error; }
}
async function simulate() {
  const item = state.incident, amount = budget(); if (!item || amount === null) return;
  const version = ++state.version; state.simulation = null; state.choice = null; $('confirmation').hidden = true; $('options').replaceChildren();
  $('simulation-status').textContent = 'Рассчитываем варианты…';
  try {
    const data = await api('/simulate',{tower_id:item.tower_id,budget_kzt:amount});
    if (version !== state.version || state.incident?.id !== item.id || budget() !== amount) return;
    if (!Array.isArray(data.options) || data.tower_id !== item.tower_id || data.budget_kzt !== amount) throw new Error('Ответ симуляции не соответствует запросу.');
    state.options = data.options; state.simulation = {budget:amount,incidentId:item.id,towerId:item.tower_id};
    $('simulation-status').textContent = `Вышка #${item.tower_id} · бюджет ${money(amount)} · синтетическая симуляция`;
    renderOptions();
  } catch(error) { if (version === state.version) $('simulation-status').textContent = 'Расчёт не выполнен. Повторите запрос.'; throw error; }
}
function renderOptions() {
  const root = $('options'); root.replaceChildren();
  if (!state.options.length) root.append(el('p','API не вернул вариантов решения.','empty'));
  for (const option of state.options) {
    const available = option.available === true && Number.isFinite(option.cost_kzt) && option.cost_kzt <= budget();
    const card = el('article',undefined,`option${available ? '' : ' unavailable'}`), title = el('div',undefined,'section-title');
    title.append(el('h3',option.name || option.solution_type),el('span',available ? 'В бюджете' : 'Недоступно','pill'));
    card.append(title,el('div',money(option.cost_kzt),'cost'));
    const list = el('dl');
    for (const [key,value] of [['Прирост ёмкости',`${fmt(option.capacity_increase_pct)}%`],['Прирост покрытия',`${fmt(option.coverage_increase_pct)}%`],['Ожидаемая нагрузка',`${fmt(option.expected_load_pct)}%`],['Срок установки',`${fmt(option.installation_days)} дн.`],['Улучшение для пользователей',fmt(option.affected_users_improved)]]) list.append(el('dt',key),el('dd',value));
    const button = el('button',available ? 'Выбрать решение' : 'Не укладывается в бюджет','secondary'); button.dataset.unavailable = String(!available); button.disabled = !available || state.busy;
    button.onclick = () => { state.choice = option; $('confirmation-text').textContent = `${state.incident.id} · вышка #${state.incident.tower_id} · ${option.name || option.solution_type} · ${money(option.cost_kzt)}. Создать заказ на выполнение?`; $('confirmation').hidden = false; syncControls(); $('create-order').focus(); };
    card.append(list,button); root.append(card);
  }
}
$('refresh').onclick = () => run(load);
$('connection-form').onsubmit = event => { event.preventDefault(); if (state.busy) return; try { const url = new URL($('api-url').value); if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Введите HTTP(S) адрес API без пароля, параметров и фрагмента.'); state.base = url.href.replace(/\/$/,''); run(load); } catch(error) { fail(error); } };
$('analysis-form').onsubmit = event => { event.preventDefault(); run(async () => {
  clearTimeout(state.timer); say('Выполняется анализ…');
  const payload = {time_window_minutes:Number($('window').value)}; if ($('area').value.trim()) payload.area = $('area').value.trim(); if ($('complaint').value.trim()) payload.complaint_text = $('complaint').value.trim();
  try { const data = await api('/analyze',payload);
    if (data.incident === null) { setIncident(null); $('area').value = payload.area || ''; renderAnalysis(data); $('incident-details').replaceChildren(el('p','В выбранном районе подходящих инцидентов не найдено.')); say('Анализ завершён. Инцидентов не найдено.'); return; }
    if (!data.incident) throw new Error('API не вернул результат анализа.');
    const index = state.incidents.findIndex(i=>i.id === data.incident.id); if (index < 0) state.incidents.unshift(data.incident); else state.incidents[index] = data.incident;
    setIncident(data.incident); renderAnalysis(data);
    say(`Анализ завершён: ${data.incident.id}.${data.recurring === true ? ' Повторяющийся инцидент.' : ''}`); await simulate();
  } catch(error) { say('Анализ или последующий расчёт не завершён.'); throw error; }
}); };
$('budget-form').onsubmit = event => { event.preventDefault(); clearTimeout(state.timer); run(simulate); };
$('budget').oninput = () => { clearTimeout(state.timer); invalidate(); if (budget() === null) { $('simulation-status').textContent = 'Введите целый неотрицательный бюджет.'; return; }
  const schedule = () => { if (state.busy) { state.timer = setTimeout(schedule,250); return; } run(simulate); }; state.timer = setTimeout(schedule,450);
};
$('cancel-order').onclick = () => { state.choice = null; $('confirmation').hidden = true; syncControls(); };
$('create-order').onclick = () => run(async () => {
  const choice = state.choice, sim = state.simulation, item = state.incident;
  if (!choice || !sim || sim.budget !== budget() || sim.incidentId !== item?.id || choice.available !== true) throw new Error('Сначала повторите расчёт и выберите решение.');
  const data = await api('/action',{incident_id:item.id,tower_id:item.tower_id,solution_type:choice.solution_type,budget_kzt:sim.budget});
  if (!data.work_order) throw new Error('API не вернул work_order. Проверьте заказ на сервере перед повтором.');
  const order = data.work_order; state.choice = null; $('confirmation').hidden = true;
  renderOrder($('work-order'),order); $('order-id').value = order.id; say('Work order создан.');
});
$('order-form').onsubmit = event => { event.preventDefault(); run(async () => { $('saved-order').hidden = true; const data = await api(`/work-orders/${encodeURIComponent($('order-id').value.trim())}`); if (!data.work_order) throw new Error('API не вернул work_order.'); renderOrder($('saved-order'),data.work_order); say('Заказ прочитан из backend.'); }); };
run(load);
