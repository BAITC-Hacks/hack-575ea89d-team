'use strict';
const $ = id => document.getElementById(id);
const state = { base: 'http://localhost:8000', towers: [], incidents: [], incident: null, towerId: null, options: [], simulation: null, choice: null, busy: false, version: 0, timer: null };
const labels = { critical:'Критический', high:'Высокий', medium:'Средний', investigating:'Диагностика', open:'Открыт', pending:'Ожидает выполнения', network_congestion:'Перегрузка сети', weak_coverage:'Слабое покрытие', normal:'Норма', degraded:'Ухудшение связи', coverage_issue:'Проблема покрытия', completed:'Выполнено', closed:'Закрыт', resolved:'Решён', low:'Низкий', upgrade_existing:'Модернизация вышки', additional_equipment:'Доп. оборудование', new_tower:'Новая вышка' };
const tr = value => labels[value] || value || '—';
const fmt = value => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('ru-RU').format(value) : '—';
const money = value => `${fmt(value)} ₸`;
function el(tag, text, className) { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (className) item.className = className; return item; }
function say(text) { $('notice').textContent = text; }
function fail(error) { $('error').textContent = error.message || String(error); $('error').hidden = false; }
function clearError() { $('error').hidden = true; }
function budget() {
  const raw = $('budget').value.replace(/\s/g,'');
  if (!/^\d+$/.test(raw)) return null;
  const value = Number(raw); return Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function metric(label, value) { const card = el('div',undefined,'metric'); card.append(el('span',label),el('strong',value)); return card; }
function areaOf(item) { return state.towers.find(t=>t.id === item.tower_id)?.area || 'Район не указан'; }
function optionName(option) { return labels[option.solution_type] || option.name || option.solution_type; }
function available(option) { return option.available === true && Number.isFinite(option.cost_kzt) && option.cost_kzt >= 0 && budget() !== null && option.cost_kzt <= budget(); }
function clearExtras() {
  $('comparison').replaceChildren(); $('comparison').hidden = true;
  $('compare-toggle').setAttribute('aria-expanded','false'); $('compare-toggle').textContent = 'Сравнить варианты';
  $('budget-gap').hidden = true; $('decision-hint').hidden = true; $('forecast').replaceChildren();
  $('order-empty').hidden = !$('work-order').hidden;
}
function renderFilters() {
  for (const [id,values] of [['priority-filter',state.incidents.map(i=>i.priority)],['status-filter',state.incidents.map(i=>i.status)],['area-filter',state.incidents.map(areaOf)],['cause-filter',state.incidents.map(i=>i.probable_cause)]]) {
    const select = $(id), previous = select.value; select.replaceChildren();
    const all = el('option','Все'); all.value = ''; select.append(all);
    for (const value of [...new Set(values)].filter(Boolean)) { const option = el('option',tr(value)); option.value = value; select.append(option); }
    if ([...select.options].some(o=>o.value === previous)) select.value = previous;
  }
}
function syncControls() {
  ['refresh','analyze','load-order'].forEach(id => $(id).disabled = state.busy);
  $('simulate').disabled = state.busy || !state.incident || budget() === null;
  $('create-order').disabled = state.busy || !state.choice || !state.simulation || state.simulation.budget !== budget();
  document.querySelectorAll('.incident,.marker,.option button').forEach(button => button.disabled = state.busy || button.dataset.unavailable === 'true');
  $('connection-form').querySelector('button').disabled = state.busy;
  $('compare-toggle').disabled = state.busy || !state.simulation || !state.options.length;
  $('analyze').textContent = state.busy ? 'Ожидайте…' : 'Проверить причину';
  document.querySelectorAll('[data-budget]').forEach(button => button.setAttribute('aria-pressed',String(Number(button.dataset.budget) === budget())));
  $('order-empty').hidden = !!state.choice || !$('work-order').hidden;

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
  $('options').replaceChildren(); $('confirmation').hidden = true; clearExtras();
  $('simulation-status').textContent = state.incident ? 'Бюджет или инцидент изменён. Нужен новый расчёт.' : 'Выберите инцидент для расчёта.';
  syncControls();
}
function renderIncidents() {
  const active = state.incidents.filter(i=>!['closed','resolved','completed'].includes(i.status));
  $('overview').replaceChildren(metric('Активных инцидентов',fmt(active.length)),metric('Критических',fmt(active.filter(i=>i.priority === 'critical').length)),metric('Вышек в сети',fmt(state.towers.length)));
  const query = $('search').value.trim().toLowerCase();
  const items = state.incidents.filter(i =>
    (!$('priority-filter').value || i.priority === $('priority-filter').value) &&
    (!$('status-filter').value || i.status === $('status-filter').value) &&
    (!$('area-filter').value || areaOf(i) === $('area-filter').value) &&
    (!$('cause-filter').value || i.probable_cause === $('cause-filter').value) &&
    `${i.id} ${i.tower_id} ${areaOf(i)} ${tr(i.probable_cause)}`.toLowerCase().includes(query)
  );
  $('incident-count').textContent = `${items.length} / ${state.incidents.length}`;
  $('incidents').replaceChildren();
  if (!items.length) $('incidents').append(el('p',state.incidents.length ? 'Ничего не найдено. Измените или сбросьте фильтры.' : 'Инцидентов пока нет. Запустите анализ.','empty'));
  for (const incident of items) {
    const button = el('button',undefined,`incident${incident.id === state.incident?.id ? ' selected' : ''}`);
    button.setAttribute('aria-pressed',String(incident.id === state.incident?.id));
    const row = el('span',undefined,'row'); row.append(el('strong',incident.id),el('span',tr(incident.priority),`priority-${incident.priority}`));
    button.append(row,el('span',tr(incident.probable_cause)),el('small',`${areaOf(incident)} · #${incident.tower_id}`),el('small',`${fmt(incident.complaints_count)} жалоб · ${tr(incident.status)}`));
    button.onclick = () => run(() => selectIncident(incident.id)); $('incidents').append(button);
  }
  syncControls();
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
  if (!item) { root.append(el('p','Выберите инцидент из списка.','empty')); return; }
  const tower = state.towers.find(t=>t.id === item.tower_id);
  root.append(el('strong',tr(item.probable_cause),'cause'),el('p',`${areaOf(item)} · Вышка #${item.tower_id} · ${tr(item.status)}`,'context-line'));
  root.append(el('p',`Приоритет: ${tr(item.priority)}`,`priority-${item.priority}`));
  const metrics = el('div',undefined,'metrics'); metrics.append(metric('Жалоб',fmt(item.complaints_count)),metric('Пользователей затронуто',fmt(item.affected_users)),metric('Нагрузка вышки',`${fmt(tower?.current_load_pct)}%`)); root.append(metrics);
  root.append(el('p',item.reason || 'Проверьте причину, чтобы получить объяснение.','reason'),el('p',`Ответственная команда: ${item.assigned_team || 'не назначена'}`,'context-line'));
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
    state.towers = towers.items; state.incidents = incidents.items; renderFilters(); renderIncidents(); renderMap();
    $('connection-status').textContent = 'подключено'; say('Данные сети обновлены.');
    if (state.incidents.length) await selectIncident(state.incidents[0].id);
  } catch(error) { $('connection-status').textContent = 'ошибка загрузки'; say(''); throw error; }
}
async function simulate() {
  const item = state.incident, amount = budget(); if (!item || amount === null) return;
  const version = ++state.version; state.simulation = null; state.choice = null; $('confirmation').hidden = true; $('options').replaceChildren(); clearExtras();
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
  if (!state.options.length) { root.append(el('p','API не вернул вариантов решения.','empty')); return; }
  const tower = state.towers.find(t=>t.id === state.incident?.tower_id);
  const priced = state.options.filter(o=>Number.isFinite(o.cost_kzt) && o.cost_kzt >= 0);
  const cheapest = [...priced].sort((a,b)=>a.cost_kzt-b.cost_kzt)[0];
  const feasible = state.options.filter(available);
  const bestLoad = [...feasible].filter(o=>Number.isFinite(o.expected_load_pct)).sort((a,b)=>a.expected_load_pct-b.expected_load_pct)[0];
  const gap = cheapest ? cheapest.cost_kzt - budget() : 0;
  $('budget-gap').hidden = gap <= 0;
  $('budget-gap').textContent = `Для самого дешёвого решения не хватает ${money(gap)}.`;
  $('decision-hint').hidden = !bestLoad;
  if (bestLoad) $('decision-hint').textContent = `Минимальная нагрузка в бюджете: «${optionName(bestLoad)}» — ${fmt(bestLoad.expected_load_pct)}%. Прогноз модели; решение принимаете вы.`;
  for (const option of state.options) {
    const canSelect = available(option), chosen = state.choice?.solution_type === option.solution_type;
    const card = el('article',undefined,`option${canSelect ? '' : ' unavailable'}${chosen ? ' chosen' : ''}`);
    const tags = []; if (cheapest && option.cost_kzt === cheapest.cost_kzt) tags.push('Минимальная стоимость'); if (bestLoad && canSelect && option.expected_load_pct === bestLoad.expected_load_pct) tags.push('Минимум нагрузки в бюджете');
    card.append(el('span',tags.join(' · '),'tag'),el('h3',optionName(option)),el('div',money(option.cost_kzt),'cost'));
    const change = el('div'); change.append(el('div',`${fmt(tower?.current_load_pct)}% → ${fmt(option.expected_load_pct)}%`,'load-change'),el('small','нагрузка: сейчас → прогноз')); card.append(change);
    card.append(el('p',`${fmt(option.installation_days)} дней · улучшение для ${fmt(option.affected_users_improved)} пользователей`));
    card.append(el('p',canSelect ? 'Доступно в вашем бюджете' : (option.cost_kzt > budget() ? `Не хватает ${money(option.cost_kzt-budget())}` : 'Недоступно по данным API'),'availability'));
    const button = el('button',chosen ? 'Выбрано' : (canSelect ? 'Выбрать' : 'Недоступно'),chosen ? '' : 'secondary');
    button.setAttribute('aria-label',`${chosen ? 'Выбрано' : 'Выбрать'}: ${optionName(option)}`); button.setAttribute('aria-pressed',String(chosen)); button.dataset.unavailable = String(!canSelect); button.disabled = !canSelect || state.busy;
    button.onclick = () => chooseOption(option); card.append(button); root.append(card);
  }
  renderComparison();
}
function renderComparison() {
  const table = el('table'); table.append(el('caption','Сравнение прогнозов для выбранной вышки'));
  const head = el('thead'), header = el('tr'); header.append(el('th','Показатель'));
  state.options.forEach(o=>header.append(el('th',optionName(o)))); [...header.children].forEach(th=>th.scope='col'); head.append(header); table.append(head);
  const body = el('tbody');
  for (const [label,format] of [['Стоимость',o=>money(o.cost_kzt)],['Нагрузка после',o=>`${fmt(o.expected_load_pct)}%`],['Прирост покрытия',o=>`${fmt(o.coverage_increase_pct)}%`],['Прирост ёмкости',o=>`${fmt(o.capacity_increase_pct)}%`],['Установка',o=>`${fmt(o.installation_days)} дней`],['Поможет пользователям',o=>fmt(o.affected_users_improved)],['Доступность',o=>available(o) ? 'В бюджете' : 'Недоступно']]) {
    const row = el('tr'), heading = el('th',label); heading.scope = 'row'; row.append(heading); state.options.forEach(o=>row.append(el('td',format(o)))); body.append(row);
  }
  table.append(body); $('comparison').replaceChildren(table);
}
function chooseOption(option) {
  if (state.busy || !available(option) || !state.simulation) return;
  state.choice = option;
  const tower = state.towers.find(t=>t.id === state.incident.tower_id);
  $('confirmation-text').textContent = `${state.incident.id} · вышка #${state.incident.tower_id} · ${optionName(option)}. Стоимость ${money(option.cost_kzt)}; остаток бюджета ${money(budget()-option.cost_kzt)}. Команда: ${state.incident.assigned_team || 'будет определена сервером'}.`;
  $('forecast').replaceChildren(metric('Нагрузка: сейчас → прогноз',`${fmt(tower?.current_load_pct)}% → ${fmt(option.expected_load_pct)}%`),metric('Прирост покрытия',`${fmt(option.coverage_increase_pct)}%`),metric('Срок установки',`${fmt(option.installation_days)} дней`));
  $('confirmation').hidden = false; renderOptions(); syncControls(); $('create-order').focus();
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
    renderFilters(); setIncident(data.incident); renderAnalysis(data);
    say(`Анализ завершён: ${data.incident.id}.${data.recurring === true ? ' Повторяющийся инцидент.' : ''}`); await simulate();
  } catch(error) { say('Анализ или последующий расчёт не завершён.'); throw error; }
}); };
$('budget-form').onsubmit = event => { event.preventDefault(); clearTimeout(state.timer); run(simulate); };
$('budget').oninput = () => { clearTimeout(state.timer); invalidate(); if (budget() === null) { $('simulation-status').textContent = 'Введите целый неотрицательный бюджет.'; return; }
  const schedule = () => { if (state.busy) { state.timer = setTimeout(schedule,250); return; } run(simulate); }; state.timer = setTimeout(schedule,450);
};
$('cancel-order').onclick = () => { state.choice = null; $('confirmation').hidden = true; renderOptions(); syncControls(); };
$('create-order').onclick = () => run(async () => {
  const choice = state.choice, sim = state.simulation, item = state.incident;
  if (!choice || !available(choice) || !sim || sim.budget !== budget() || sim.incidentId !== item?.id || choice.available !== true) throw new Error('Сначала повторите расчёт и выберите решение.');
  const data = await api('/action',{incident_id:item.id,tower_id:item.tower_id,solution_type:choice.solution_type,budget_kzt:sim.budget});
  if (!data.work_order) throw new Error('API не вернул work_order. Проверьте заказ на сервере перед повтором.');
  const order = data.work_order; state.choice = null; $('confirmation').hidden = true;
  renderOrder($('work-order'),order); $('order-id').value = order.id; say('Заказ создан и сохранён на сервере.'); renderOptions();
});
$('order-form').onsubmit = event => { event.preventDefault(); run(async () => { $('saved-order').hidden = true; const data = await api(`/work-orders/${encodeURIComponent($('order-id').value.trim())}`); if (!data.work_order) throw new Error('API не вернул work_order.'); renderOrder($('saved-order'),data.work_order); say('Заказ прочитан из backend.'); }); };

for (const id of ['priority-filter','status-filter','area-filter','cause-filter']) $(id).onchange = renderIncidents;
$('search').oninput = renderIncidents;
$('reset-filters').onclick = () => { for (const id of ['search','priority-filter','status-filter','area-filter','cause-filter']) $(id).value = ''; renderIncidents(); };
$('compare-toggle').onclick = () => { const open = $('comparison').hidden; $('comparison').hidden = !open; $('compare-toggle').setAttribute('aria-expanded',String(open)); $('compare-toggle').textContent = open ? 'Скрыть сравнение' : 'Сравнить варианты'; };
$('budget').onblur = () => { const amount = budget(); if (amount !== null) $('budget').value = fmt(amount); };
document.querySelectorAll('[data-budget]').forEach(button => button.onclick = () => { $('budget').value = fmt(Number(button.dataset.budget)); $('budget').dispatchEvent(new Event('input')); });
run(load);
