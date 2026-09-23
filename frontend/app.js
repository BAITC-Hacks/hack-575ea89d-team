'use strict';
const $ = id => document.getElementById(id);
const state = { base: 'http://localhost:8000', towers: [], incidents: [], incident: null, towerId: null, options: [], simulation: null, choice: null, busy: false, version: 0, timer: null, lastUpdatedAt: null, connection: 'waiting', labPriority: 'cost_kzt', labFocus: null, labVersus: null, streetMode: true };
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

const filterIds = ['priority-filter','status-filter','area-filter','cause-filter'];
function preferenceKey() { return `network-dashboard:v1:${state.base}`; }
function validateBase(value) {
  const url = new URL(value);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Введите HTTP(S) адрес API без пароля, параметров и фрагмента.');
  return url.href.replace(/\/$/,'');
}
function restoreBase() {
  try { const saved = localStorage.getItem('network-dashboard:api:v1'); if (saved) state.base = validateBase(saved); } catch { /* Use the default API if storage is unavailable or invalid. */ }
  $('api-url').value = state.base;
}
function readPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem(preferenceKey()) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}
function savePreferences() {
  const previous = readPreferences();
  const value = {budget: budget() ?? previous.budget, incidentId: state.incident?.id ?? null, filters: {}};
  for (const id of ['search',...filterIds]) value.filters[id] = $(id).value;
  try { localStorage.setItem(preferenceKey(),JSON.stringify(value)); } catch { /* Storage can be disabled; the dashboard still works. */ }
}
function restorePreferences(value) {
  $('budget').value = fmt(Number.isSafeInteger(value.budget) && value.budget >= 0 ? value.budget : 20000000);
  const filters = value.filters && typeof value.filters === 'object' ? value.filters : {};
  for (const id of ['search',...filterIds]) {
    const saved = typeof filters[id] === 'string' ? filters[id] : '';
    $(id).value = id === 'search' ? saved.slice(0,200) : ([...$(id).options].some(o=>o.value === saved) ? saved : '');
  }
}
function requestedIncident() { return new URL(location.href).searchParams.get('incident'); }
function updateIncidentLink(updateAddress = true) {
  const url = new URL(location.href);
  if (state.incident) url.searchParams.set('incident',state.incident.id); else url.searchParams.delete('incident');
  if (updateAddress) history.replaceState(null,'',url);
  url.hash = 'workspace';
  $('incident-link').value = state.incident ? url.href : '';
  $('share-incident').hidden = !state.incident;
  $('copy-link-status').textContent = '';
}
function renderFreshness() {
  const status = {waiting:'Ожидание API',loading:'Загружаем сеть',online:'API доступен',offline:'Нет связи с API',invalid:'Ошибка ответа API'};
  $('api-indicator').textContent = status[state.connection];
  $('api-indicator').dataset.status = state.connection;
  $('connection-status').textContent = status[state.connection];
  if (!state.lastUpdatedAt) { $('data-freshness').textContent = 'Сеть ещё не загружена'; $('data-freshness').classList.remove('stale'); return; }
  const minutes = Math.max(0,Math.floor((Date.now()-state.lastUpdatedAt)/60000));
  const time = new Date(state.lastUpdatedAt).toLocaleTimeString('ru-RU');
  $('data-freshness').textContent = `Последняя загрузка сети: ${time} · ${minutes ? `${minutes} мин назад` : 'только что'}${minutes >= 5 ? ' · обновите данные' : ''}`;
  $('data-freshness').classList.toggle('stale',minutes >= 5);
}
function hasCoordinates(tower) {
  return Number.isFinite(tower?.lat) && Math.abs(tower.lat) <= 85 && Number.isFinite(tower?.lon) && Math.abs(tower.lon) <= 180;
}
function updateMapLink() {
  const tower = state.towers.find(t=>t.id === state.towerId);
  const link = $('map-external'); link.hidden = !hasCoordinates(tower);
  if (!hasCoordinates(tower)) { link.removeAttribute('href'); return; }
  link.href = `https://www.openstreetmap.org/?mlat=${tower.lat}&mlon=${tower.lon}#map=14/${tower.lat}/${tower.lon}`;
  link.textContent = `Вышка #${tower.id} на OpenStreetMap ↗`;
}
function renderDecisionSummary(feasible) {
  const root = $('decision-hint'); root.replaceChildren(); root.hidden = !feasible.length;
  if (!feasible.length) return;
  root.append(el('strong','Что важнее для этого решения?'));
  const list = el('ul');
  for (const [field,label,format] of [
    ['cost_kzt','Сэкономить бюджет',money],
    ['installation_days','Установить быстрее',v=>`${fmt(v)} дней`],
    ['expected_load_pct','Получить меньшую нагрузку',v=>`${fmt(v)}% после установки`]
  ]) {
    const candidates = feasible.filter(o=>Number.isFinite(o[field]) && o[field] >= 0);
    if (!candidates.length) continue;
    const best = Math.min(...candidates.map(o=>o[field]));
    const winners = candidates.filter(o=>o[field] === best).map(optionName).join(' / ');
    list.append(el('li',`${label}: ${winners} — ${format(best)}.`));
  }
  root.append(list,el('p','Сравниваем только доступные варианты в вашем бюджете. Значения и прогнозы получены от API; выбор остаётся за вами.','muted'));
}

function metric(label, value) { const card = el('div',undefined,'metric'); card.append(el('span',label),el('strong',value)); return card; }
function areaOf(item) { return state.towers.find(t=>t.id === item.tower_id)?.area || 'Район не указан'; }
function optionName(option) { return labels[option.solution_type] || option.name || option.solution_type; }
function available(option) { return option.available === true && Number.isFinite(option.cost_kzt) && option.cost_kzt >= 0 && budget() !== null && option.cost_kzt <= budget(); }
function clearExtras() {
  $('decision-lab').hidden = true; state.labFocus = null; state.labVersus = null;
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
  document.querySelectorAll('.incident,.marker,.tower-incident,.option button,.lab-select').forEach(button => button.disabled = state.busy || button.dataset.unavailable === 'true');
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
    state.connection = 'online'; renderFreshness();
    const data = await response.json().catch(() => { state.connection = 'invalid'; renderFreshness(); throw new Error('API вернул ответ, который не является JSON.'); });
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Ошибка API ${response.status}: ${JSON.stringify(data.detail || data)}`);
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) { state.connection = 'offline'; renderFreshness(); }
    if (error.name === 'AbortError') throw Object.assign(new Error('API не ответил за 45 секунд. При создании work order проверьте результат на сервере перед повтором.'),{connection:'offline'});
    if (error instanceof TypeError) throw Object.assign(new Error('Нет соединения с API. Проверьте адрес, запуск backend и порт frontend 5173.'),{connection:'offline'});
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
  syncFilterMenus();
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

let streetMap = null, streetMarkers = null, streetDataset = '', streetTileLayer = null;
function fitStreetNetwork() {
  const towers = state.towers.filter(hasCoordinates);
  if (!streetMap) return;
  streetMap.invalidateSize();
  if (towers.length) streetMap.fitBounds(towers.map(t=>[t.lat,t.lon]),{padding:[35,35],maxZoom:14});
  else streetMap.setView([51.128,71.431],13);
}
function renderStreetMap() {
  if (!$('network-panel').open) return;
  const supported = typeof L !== 'undefined';
  const show = state.streetMode && supported;
  $('street-map').hidden = !show; $('map').hidden = show;
  $('show-streets').setAttribute('aria-pressed',String(show));
  $('show-scheme').setAttribute('aria-pressed',String(!show));
  $('fit-network').disabled = !show;
  if (!supported) { $('street-status').textContent = 'Библиотека карты не загрузилась. Доступна схема; проверьте интернет и обновите страницу.'; return; }
  if (!show) { $('street-status').textContent = 'Схема по координатам API, без географической подложки.'; return; }
  $('street-status').textContent = 'Улицы OpenStreetMap · маркеры из API. Для приближения используйте +.';
  if (!streetMap) {
    streetMap = L.map('street-map',{scrollWheelZoom:false}).setView([51.128,71.431],13);
    streetTileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
      maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    });
    streetTileLayer.on('loading',()=>{ $('street-status').textContent='Загружаем улицы Астаны…'; });
    streetTileLayer.on('tileerror',()=>{ $('street-status').textContent='Часть карты не загрузилась. Проверьте интернет или используйте схему.'; });
    streetTileLayer.on('load',()=>{
      const loaded = $('street-map').querySelectorAll('.leaflet-tile-loaded');
      $('street-status').textContent=loaded.length ? 'Улицы OpenStreetMap · маркеры из API. Для приближения используйте +.' : 'Подложка недоступна. Переключитесь на схему или проверьте интернет.';
    });
    streetTileLayer.addTo(streetMap);
    streetMarkers = L.layerGroup().addTo(streetMap);
    L.control.scale({imperial:false}).addTo(streetMap);
  }
  streetMap.invalidateSize(); streetMarkers.clearLayers();
  const towers=state.towers.filter(hasCoordinates);
  for (const tower of towers) {
    const dot=el('span',`#${tower.id}`,`street-pin${tower.id === state.towerId ? ' selected' : ''}${tower.status === 'normal' ? '' : ' warning'}`);
    const count=state.incidents.filter(i=>i.tower_id === tower.id).length;
    const marker=L.marker([tower.lat,tower.lon],{icon:L.divIcon({html:dot,className:'street-marker',iconSize:[42,30],iconAnchor:[21,15]}),title:`Вышка #${tower.id} · ${tower.area} · инцидентов: ${count}`,keyboard:true}).addTo(streetMarkers);
    marker.on('click',()=>{ if(state.busy) return; state.towerId=tower.id; renderMap(); renderTower(); syncControls(); });
  }
  const key=state.base+'|'+towers.map(t=>`${t.id}:${t.lat}:${t.lon}`).join('|');
  if(key !== streetDataset) { streetDataset=key; fitStreetNetwork(); }
}

function renderMap() {
  renderStreetMap();
  const container = $('map'); container.replaceChildren(); updateMapLink();
  const picker = $('tower-picker'); picker.replaceChildren();
  for (const tower of state.towers) { const option = el('option',`#${tower.id} · ${tower.area || 'Район не указан'}`); option.value = String(tower.id); picker.append(option); }
  if (state.towerId !== null) picker.value = String(state.towerId);
  else picker.selectedIndex = -1;
  picker.disabled = !state.towers.length;
  const towers = state.towers.filter(hasCoordinates);
  if (!towers.length) { container.append(el('p','Нет вышек с координатами.','empty')); return; }
  const lats = towers.map(t=>t.lat), lons = towers.map(t=>t.lon);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats), minLon = Math.min(...lons), maxLon = Math.max(...lons);
  for (const tower of towers) {
    const button = el('button',`#${tower.id}`,`marker ${tower.status || ''}${tower.id === state.towerId ? ' active' : ''}`);
    button.style.left = `${maxLon === minLon ? 50 : 12 + (tower.lon-minLon)/(maxLon-minLon)*76}%`;
    button.style.top = `${maxLat === minLat ? 50 : 85 - (tower.lat-minLat)/(maxLat-minLat)*70}%`;
    button.setAttribute('aria-label',`Вышка ${tower.id}, ${tower.area}, ${tr(tower.status)}`);
    button.setAttribute('aria-pressed',String(tower.id === state.towerId));
    const count = state.incidents.filter(i=>i.tower_id === tower.id).length;
    button.title = `${tower.area} · нагрузка ${fmt(tower.current_load_pct)}% · инцидентов: ${count}`;
    if (count) button.append(el('span',String(count),'marker-count'));
    button.onclick = () => { state.towerId = tower.id; renderMap(); renderTower(); syncControls(); };
    container.append(button);
  }
}
function renderTower() {
  const tower = state.towers.find(t=>t.id === state.towerId); const root = $('tower-details'); root.replaceChildren();
  if (!tower) return;
  root.append(el('strong',`Вышка #${tower.id} · ${tower.area}`),el('p',`${tower.network_type || '—'} · ${tr(tower.status)} · нагрузка ${fmt(tower.current_load_pct)}% · радиус покрытия ${fmt(tower.coverage_radius_km)} км`));
  if (hasCoordinates(tower)) root.append(el('p',`Координаты: ${tower.lat}, ${tower.lon}`,'muted'));
  const linked = state.incidents.filter(i=>i.tower_id === tower.id);
  root.append(el('p',linked.length ? 'Инциденты этой вышки — открыть диагностику:' : 'Для этой вышки в API нет инцидентов.','muted'));
  const links = el('div',undefined,'actions');
  for (const incident of linked) {
    const button = el('button',`${incident.id} · ${tr(incident.priority)} · ${tr(incident.status)}`,'secondary tower-incident');
    button.onclick = () => run(async () => { await selectIncident(incident.id); $('incident-details').scrollIntoView({block:'center'}); });
    links.append(button);
  }
  root.append(links);

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
  updateIncidentLink(); savePreferences();
}
async function selectIncident(id) {
  const data = await api(`/incidents/${encodeURIComponent(id)}`); if (!data.incident) throw new Error('API не вернул incident.');
  setIncident(data.incident); await simulate();
}
async function load() {
  const preferences = readPreferences(), requested = requestedIncident();
  const preferred = requested || state.incident?.id || (typeof preferences.incidentId === 'string' ? preferences.incidentId : null);
  clearTimeout(state.timer); say('Загружаем сеть…'); state.connection = 'loading'; renderFreshness();
  state.incident = null; state.towers = []; state.incidents = []; state.towerId = null; invalidate(); renderIncidents(); renderDetail(); renderMap(); renderTower(); clearAnalysis(); $('work-order').hidden = true; $('saved-order').hidden = true; updateIncidentLink(false);
  let towers, incidents;
  try {
    const results = await Promise.allSettled([api('/towers'), api('/incidents')]);
    const failed = results.find(result=>result.status === 'rejected');
    if (failed) { state.connection = results.some(result=>result.status === 'rejected' && result.reason.connection === 'offline') ? 'offline' : 'invalid'; throw failed.reason; }
    [towers, incidents] = results.map(result=>result.value);
    if (!Array.isArray(towers.items) || !Array.isArray(incidents.items)) { state.connection = 'invalid'; throw new Error('Ожидались массивы items в ответах API.'); }
  } catch(error) { renderFreshness(); say('Не удалось загрузить сеть. Проверьте подключение и повторите обновление.'); throw error; }
  state.towers = towers.items; state.incidents = incidents.items;
  state.lastUpdatedAt = Date.now(); state.connection = 'online'; renderFreshness();
  renderFilters(); restorePreferences(preferences); renderIncidents(); renderMap();
  say('Данные сети обновлены.');
  const selected = state.incidents.find(i=>i.id === preferred);
  if (selected) await selectIncident(selected.id);
  else if (requested) { say(`Инцидент ${requested} не найден в текущем API. Выберите его из списка или проверьте подключение.`); }
  else if (state.incidents.length) await selectIncident(state.incidents[0].id);
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
  renderDecisionSummary(feasible);
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
  renderComparison(); renderDecisionLab();
}

function labCandidates() {
  return state.options.filter(o=>Number.isFinite(o.cost_kzt) && o.cost_kzt >= 0 && Number.isFinite(o.expected_load_pct) && o.expected_load_pct >= 0);
}
function preferredLabOption(options) {
  const eligible = options.filter(available).filter(o=>Number.isFinite(o[state.labPriority]) && o[state.labPriority] >= 0);
  return [...eligible].sort((a,b)=>a[state.labPriority]-b[state.labPriority] || a.cost_kzt-b.cost_kzt)[0] || options[0];
}
function renderDecisionLab() {
  const options = labCandidates();
  $('decision-lab').hidden = !state.simulation || !options.length;
  if (!state.simulation || !options.length) return;
  $('decision-hint').hidden = true;
  const focused = options.find(o=>o.solution_type === state.labFocus) || preferredLabOption(options);
  state.labFocus = focused.solution_type;
  const current = state.towers.find(t=>t.id === state.incident?.tower_id)?.current_load_pct;
  const highestCost = Math.max(...options.map(o=>o.cost_kzt),budget(),1);
  const costStep = 10 ** Math.floor(Math.log10(highestCost));
  const maxCost = Math.ceil(highestCost/costStep + .25)*costStep;
  const maxLoad = Math.ceil(Math.max(...options.map(o=>o.expected_load_pct),Number.isFinite(current) ? current : 0,1)/10)*10;
  const budgetPosition = budget()/maxCost*100;
  $('lab-budget-line').style.left = `${budgetPosition}%`;
  $('lab-affordable').style.width = `${budgetPosition}%`;
  $('lab-budget-label').textContent = `Лимит ${money(budget())}`;
  $('lab-y-max').textContent = fmt(maxLoad);
  $('lab-x-max').textContent = money(Math.ceil(maxCost));
  $('lab-context').textContent = `${state.incident.id} / Вышка #${state.incident.tower_id}`;
  const points = $('lab-points'); points.replaceChildren();
  for (const [index,option] of options.entries()) {
    const selected = option.solution_type === focused.solution_type;
    const button = el('button',String(index+1),`lab-point${selected ? ' is-focused' : ''}${available(option) ? '' : ' is-locked'}`);
    button.type = 'button'; button.style.left = `${option.cost_kzt/maxCost*100}%`; button.style.bottom = `${option.expected_load_pct/maxLoad*100}%`;
    button.setAttribute('aria-pressed',String(selected));
    button.setAttribute('aria-label',`Исследовать: ${optionName(option)}, ${money(option.cost_kzt)}, нагрузка ${fmt(option.expected_load_pct)}%`);
    button.title = `${optionName(option)} · ${money(option.cost_kzt)} · ${fmt(option.expected_load_pct)}%`;
    button.onclick = () => { state.labFocus = option.solution_type; renderDecisionLab(); };
    points.append(button);
  }
  document.querySelectorAll('[data-lab-priority]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.labPriority === state.labPriority)));
  const root = $('lab-focus'); root.replaceChildren();
  root.append(el('span',`СЦЕНАРИЙ ${String(options.indexOf(focused)+1).padStart(2,'0')}`,'lab-scenario'),el('h4',optionName(focused)));
  const number = el('div',undefined,'lab-result'); number.append(el('strong',`${fmt(focused.expected_load_pct)}%`),el('span','прогноз нагрузки')); root.append(number);
  if (Number.isFinite(current)) {
    const delta = current-focused.expected_load_pct;
    root.append(el('p',`${delta >= 0 ? '↓' : '↑'} ${fmt(Math.abs(delta))} п.п. ${delta >= 0 ? 'ниже' : 'выше'} текущих ${fmt(current)}%`,'lab-impact'));
  }
  const facts = el('div',undefined,'lab-facts'); facts.append(metric('Стоимость',money(focused.cost_kzt)),metric('Установка',`${fmt(focused.installation_days)} дней`)); root.append(facts);
  const cta = el('button',available(focused) ? 'Перейти к подтверждению ↗' : (focused.cost_kzt > budget() ? `Не хватает ${money(focused.cost_kzt-budget())}` : 'Недоступно по данным API'),'lab-select');
  cta.type='button'; cta.dataset.unavailable=String(!available(focused)); cta.disabled=state.busy || !available(focused);
  cta.onclick=()=>chooseOption(focused); root.append(cta);
  const other = options.filter(o=>o.solution_type !== focused.solution_type);
  const comparator = other.find(o=>o.solution_type === state.labVersus) || other[0];
  state.labVersus = comparator?.solution_type || null;
  const select=$('lab-versus'); select.replaceChildren(); select.disabled=!other.length;
  for(const option of other) { const node=el('option',optionName(option)); node.value=option.solution_type; select.append(node); }
  select.value=state.labVersus || '';
  if (!comparator) { $('lab-difference').textContent='Для сравнения нужен ещё один сценарий от API.'; return; }
  const cost=focused.cost_kzt-comparator.cost_kzt, load=focused.expected_load_pct-comparator.expected_load_pct;
  const parts=[cost === 0 ? 'Та же стоимость' : `На ${money(Math.abs(cost))} ${cost > 0 ? 'дороже' : 'дешевле'}`, load === 0 ? 'та же прогнозная нагрузка' : `нагрузка на ${fmt(Math.abs(load))} п.п. ${load > 0 ? 'выше' : 'ниже'}`];
  if(Number.isFinite(focused.installation_days) && Number.isFinite(comparator.installation_days)) {
    const days=focused.installation_days-comparator.installation_days;
    parts.push(days === 0 ? 'тот же срок установки' : `установка на ${fmt(Math.abs(days))} дн. ${days > 0 ? 'дольше' : 'быстрее'}`);
  }
  $('lab-difference').textContent=`${parts.join(' · ')}. Это сравнение прогнозов, не результат выполненных работ.`;
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
$('connection-form').onsubmit = event => {
  event.preventDefault(); if (state.busy) return;
  try {
    const nextBase = validateBase($('api-url').value);
    if (nextBase !== state.base) {
      savePreferences(); state.base = nextBase; state.lastUpdatedAt = null; state.incident = null;
      const page = new URL(location.href); page.searchParams.delete('incident'); history.replaceState(null,'',page);
    }
    try { localStorage.setItem('network-dashboard:api:v1',state.base); } catch { /* Optional persistence. */ }
    run(load);
  } catch(error) { fail(error); }
};
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
$('budget').oninput = () => { clearTimeout(state.timer); invalidate(); savePreferences(); if (budget() === null) { $('simulation-status').textContent = 'Введите целый неотрицательный бюджет.'; return; }
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

// Keep native selects as the filter data source; enhance their visible controls.
const filterMenus = [];
function syncFilterMenus() {
  for (const menu of filterMenus) {
    menu.close();
    menu.value.textContent = menu.select.selectedOptions[0]?.textContent || 'Все';
    menu.trigger.classList.toggle('has-selection', menu.select.value !== '');
    menu.list.replaceChildren();
    for (const option of menu.select.options) {
      const row = el('div',undefined,'filter-option');
      row.id = `${menu.select.id}-option-${menu.list.children.length}`;
      row.setAttribute('role','option');
      row.setAttribute('aria-selected',String(option.selected));
      row.dataset.value = option.value;
      const dot = el('span',undefined,'filter-dot'); dot.dataset.level = menu.select.id === 'priority-filter' ? option.value : '';
      dot.setAttribute('aria-hidden','true');
      const check = el('span',option.selected ? '✓' : '','filter-check'); check.setAttribute('aria-hidden','true');
      row.append(dot,el('span',option.textContent,'filter-option-label'),check);
      row.onmousedown = event => event.preventDefault();
      row.onclick = () => menu.choose(option.value);
      menu.list.append(row);
    }
  }
}
function initFilterMenus() {
  document.querySelectorAll('.filters select').forEach(select => {
    const label = select.parentElement, name = label.firstChild.textContent.trim();
    const wrapper = el('div',undefined,'filter-field'), caption = el('span',name,'filter-label');
    caption.id = `${select.id}-label`;
    label.replaceWith(wrapper); wrapper.append(caption,select); select.hidden = true;
    const trigger = el('button',undefined,'filter-trigger'), value = el('span','Все','filter-value');
    trigger.type = 'button'; trigger.id = `${select.id}-trigger`; value.id = `${select.id}-value`;
    trigger.setAttribute('role','combobox'); trigger.setAttribute('aria-haspopup','listbox');
    trigger.setAttribute('aria-expanded','false'); trigger.setAttribute('aria-labelledby',`${caption.id} ${value.id}`);
    const arrow = el('span',undefined,'filter-arrow'); arrow.setAttribute('aria-hidden','true'); trigger.append(value,arrow);
    const list = el('div',undefined,'filter-menu'); list.id = `${select.id}-menu`; list.hidden = true;
    list.setAttribute('role','listbox'); list.setAttribute('aria-labelledby',caption.id); trigger.setAttribute('aria-controls',list.id);
    wrapper.append(trigger,list);
    let active = 0, search = '', searchAt = 0;
    const menu = {select,trigger,value,list,
      close() { list.hidden = true; trigger.setAttribute('aria-expanded','false'); trigger.removeAttribute('aria-activedescendant'); wrapper.classList.remove('is-open'); },
      choose(next) { select.value = next; menu.close(); trigger.focus(); select.dispatchEvent(new Event('change')); }
    };
    const focusOption = index => {
      if (!list.children.length) return;
      active = Math.max(0,Math.min(index,list.children.length-1));
      [...list.children].forEach((row,i)=>row.classList.toggle('is-active',i === active));
      trigger.setAttribute('aria-activedescendant',list.children[active].id);
      list.children[active].scrollIntoView({block:'nearest'});
    };
    const open = () => { filterMenus.forEach(item=>item.close()); list.hidden = false; wrapper.classList.add('is-open'); trigger.setAttribute('aria-expanded','true'); focusOption(Math.max(0,select.selectedIndex)); };
    trigger.onclick = () => list.hidden ? open() : menu.close();
    trigger.onkeydown = event => {
      if (event.key === 'Tab') { menu.close(); return; }
      if (event.key === 'Escape') { event.preventDefault(); menu.close(); return; }
      if (['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(event.key)) {
        event.preventDefault();
        if (list.hidden) { open(); if (event.key === 'End') focusOption(list.children.length-1); return; }
        if (event.key === 'Enter' || event.key === ' ') { menu.choose(list.children[active].dataset.value); return; }
        focusOption(event.key === 'Home' ? 0 : event.key === 'End' ? list.children.length-1 : active + (event.key === 'ArrowDown' ? 1 : -1));
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault(); if (list.hidden) open();
        search = Date.now()-searchAt > 700 ? event.key : search+event.key; searchAt = Date.now();
        const index = [...select.options].findIndex(option=>option.textContent.toLowerCase().startsWith(search.toLowerCase()));
        if (index >= 0) focusOption(index);
      }
    };
    wrapper.addEventListener('focusout',event=>{ if (!wrapper.contains(event.relatedTarget)) menu.close(); });
    filterMenus.push(menu);
  });
  document.addEventListener('pointerdown',event=>filterMenus.forEach(menu=>{ if (!menu.trigger.parentElement.contains(event.target)) menu.close(); }));
  syncFilterMenus();
}
initFilterMenus();
for (const id of filterIds) $(id).onchange = () => { renderIncidents(); savePreferences(); };
$('search').oninput = () => { renderIncidents(); savePreferences(); };
$('reset-filters').onclick = () => { for (const id of ['search','priority-filter','status-filter','area-filter','cause-filter']) $(id).value = ''; renderIncidents(); savePreferences(); };
$('compare-toggle').onclick = () => { const open = $('comparison').hidden; $('comparison').hidden = !open; $('compare-toggle').setAttribute('aria-expanded',String(open)); $('compare-toggle').textContent = open ? 'Скрыть сравнение' : 'Сравнить варианты'; };
$('budget').onblur = () => { const amount = budget(); if (amount !== null) $('budget').value = fmt(amount); };
document.querySelectorAll('[data-budget]').forEach(button => button.onclick = () => { $('budget').value = fmt(Number(button.dataset.budget)); $('budget').dispatchEvent(new Event('input')); });

$('copy-incident-link').onclick = async () => {
  try { await navigator.clipboard.writeText($('incident-link').value); $('copy-link-status').textContent = 'Ссылка скопирована.'; }
  catch { $('incident-link').focus(); $('incident-link').select(); $('copy-link-status').textContent = 'Скопируйте выделенную ссылку вручную.'; }
};
$('tower-picker').onchange = () => { state.towerId = state.towers.find(t=>String(t.id) === $('tower-picker').value)?.id ?? null; renderMap(); renderTower(); syncControls(); };
document.querySelectorAll('[data-lab-priority]').forEach(button=>button.onclick=()=>{ state.labPriority=button.dataset.labPriority; state.labFocus=null; renderDecisionLab(); });
$('lab-versus').onchange=()=>{ state.labVersus=$('lab-versus').value; renderDecisionLab(); };
$('network-panel').ontoggle=()=>{ renderStreetMap(); };
$('show-streets').onclick=()=>{ state.streetMode=true; renderStreetMap(); };
$('show-scheme').onclick=()=>{ state.streetMode=false; renderStreetMap(); };
$('fit-network').onclick=fitStreetNetwork;
setInterval(renderFreshness,30000);
restoreBase();
renderFreshness();
run(load);
