const $ = (id) => document.getElementById(id);
const number = (value, digits = 0) => Number(value).toLocaleString('ru-RU', { maximumFractionDigits: digits });
const money = (value) => `${number(value)} у.е.`;
const escapeHtml = (value) => String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

function setRows(id, rows, emptyText, render) {
  $(id).innerHTML = rows.length ? rows.map(render).join('') : `<tr><td colspan="5" class="empty">${escapeHtml(emptyText)}</td></tr>`;
}

function render(report) {
  if (report?.schema_version !== 1 || report?.mode !== 'mock' || !report.metrics || !Array.isArray(report.final_campaigns) || !Array.isArray(report.pilot_history)) {
    throw new Error('Ожидался report.json версии 1 в режиме mock.');
  }
  const m = report.metrics;
  $('net').textContent = `${m.net_arpu_gain >= 0 ? '+' : ''}${money(m.net_arpu_gain)}`;
  $('cost').textContent = money(m.total_cost);
  $('contacts').textContent = `${number(m.total_contacts)} / 15 000`;
  $('pilots').textContent = `${number(m.n_pilots)} / 20`;
  $('campaign-count').textContent = `${report.final_campaigns.length} / 10`;
  $('report-meta').textContent = `Режим mock · seed ${report.seed} · baseline ${money(m.baseline_total_arpu)}`;
  $('notice').classList.remove('visible');

  setRows('pilot-rows', report.pilot_history, 'Нет пилотов в отчёте', (p) => {
    const ratio = Number(p.observed_lift_ratio);
    const cls = ratio >= 0 ? 'positive' : 'negative';
    return `<tr><td>${escapeHtml(p.pilot)}</td><td><span class="pill">${escapeHtml(p.target_tariff)}</span></td><td>${escapeHtml(p.channel)}</td><td>${number(p.n_customers)}</td><td class="${cls}">${ratio >= 0 ? '+' : ''}${number(ratio * 100, 1)}% <span class="muted">(${money(p.observed_lift_total)})</span></td></tr>`;
  });

  setRows('campaign-rows', report.final_campaigns, 'Нет финальных кампаний', (c) => {
    const filters = [c.filter_current_tariff, c.filter_arpu_segment, c.filter_data_segment, c.filter_call_segment].filter(Boolean).join(' · ') || 'весь сегмент';
    const count = m.campaigns_detail?.find((detail) => detail.name === c.campaign_name)?.n_contacts;
    return `<tr><td>${escapeHtml(c.campaign_name)}</td><td>${escapeHtml(filters)}</td><td><span class="pill">${escapeHtml(c.target_tariff)}</span></td><td>${escapeHtml(c.channel)}</td><td>${count == null ? '—' : number(count)}</td></tr>`;
  });
}

async function loadDefault() {
  try {
    const response = await fetch('../artifacts/report.json');
    if (!response.ok) throw new Error('Файл не найден');
    render(await response.json());
  } catch (_) {
    $('notice').classList.add('visible');
    $('report-meta').textContent = 'Отчёт пока не загружен';
  }
}

$('report-file').addEventListener('change', async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    render(JSON.parse(await file.text()));
  } catch (error) {
    $('notice').textContent = `Не удалось открыть отчёт: ${error.message}`;
    $('notice').classList.add('visible');
  }
});

loadDefault();
