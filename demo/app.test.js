const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');

class Element {
  constructor() {
    this.textContent = '';
    this.innerHTML = '';
    this.handlers = {};
    const classes = new Set();
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    };
  }

  addEventListener(name, handler) {
    this.handlers[name] = handler;
  }
}

const validReport = () => ({
  schema_version: 1,
  mode: 'mock',
  seed: 42,
  metrics: {
    net_arpu_gain: 120.5,
    total_cost: 4,
    total_contacts: 3,
    n_pilots: 1,
    baseline_total_arpu: 1000,
    campaigns_detail: [{ name: 'final_1', n_contacts: 2 }],
  },
  final_campaigns: [{
    campaign_name: 'final_1', filter_current_tariff: 'tariff_1',
    target_tariff: 'tariff_2', channel: 'sms',
  }],
  pilot_history: [{
    pilot: 'pilot_1', target_tariff: 'tariff_2', channel: 'sms',
    n_customers: 1, observed_lift_ratio: 0.125, observed_lift_total: 12.5,
  }],
});

async function makePage(fetchImpl) {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
  };
  vm.runInNewContext(source, { document, fetch: fetchImpl });
  await new Promise((resolve) => setImmediate(resolve));
  const fileInput = document.getElementById('report-file');
  return {
    elements,
    async upload(text) {
      return fileInput.handlers.change({ target: { files: [{ text: async () => text }] } });
    },
  };
}

const okFetch = (report) => async () => ({ ok: true, json: async () => report });

test('renders a valid mock report and keeps pilot/final tables separate', async () => {
  const page = await makePage(okFetch(validReport()));
  assert.match(page.elements.get('net').textContent, /^\+/);
  assert.match(page.elements.get('pilot-rows').innerHTML, /\+12,5%/);
  assert.match(page.elements.get('campaign-rows').innerHTML, /final_1/);
  assert.match(page.elements.get('report-meta').textContent, /seed 42/);
});

test('renders null net and pilot observations as missing, not zero', async () => {
  const report = validReport();
  report.metrics.net_arpu_gain = null;
  report.pilot_history[0].observed_lift_ratio = null;
  report.pilot_history[0].observed_lift_total = null;
  const page = await makePage(okFetch(report));
  assert.equal(page.elements.get('net').textContent, '—');
  assert.match(page.elements.get('pilot-rows').innerHTML, />— <span class="muted">\(—\)/);
  assert.doesNotMatch(page.elements.get('pilot-rows').innerHTML, /\+0(?:,0)?%/);
});

test('invalid schema clears previous report rather than retaining old metrics', async () => {
  const page = await makePage(okFetch(validReport()));
  assert.notEqual(page.elements.get('net').textContent, '—');
  await page.upload(JSON.stringify({ ...validReport(), schema_version: 2 }));
  assert.equal(page.elements.get('net').textContent, '—');
  assert.match(page.elements.get('report-meta').textContent, /не загружен/);
  assert.match(page.elements.get('notice').textContent, /версии 1/);
});

test('damaged JSON clears previous report and reports the parse error', async () => {
  const page = await makePage(okFetch(validReport()));
  await page.upload('{ broken json');
  assert.equal(page.elements.get('net').textContent, '—');
  assert.equal(page.elements.get('pilot-rows').innerHTML.includes('pilot_1'), false);
  assert.match(page.elements.get('notice').textContent, /Не удалось открыть отчёт/);
});

test('failed automatic report fetch leaves placeholders, not stale results', async () => {
  const page = await makePage(async () => { throw new Error('network blocked'); });
  assert.equal(page.elements.get('net').textContent, '—');
  assert.equal(page.elements.get('cost').textContent, '—');
  assert.equal(page.elements.get('report-meta').textContent, 'Отчёт не загружен');
  assert.match(page.elements.get('notice').textContent, /network blocked/);
});
