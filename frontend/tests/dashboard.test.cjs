// No browser or npm dependencies: exercise application state with a minimal DOM
// adapter and controlled API responses. Visual/menu behavior is checked in browser.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.value = ''; this.hidden = false; this.dataset = {}; this.style = {}; this.attributes = {}; this._text = ''; this.classes = new Set(); this.classList = {add: n=>this.classes.add(n), remove: n=>this.classes.delete(n), toggle: (n,on)=>on ? this.classes.add(n) : this.classes.delete(n)}; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(n=>n.textContent).join(' '); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ''; this.children = nodes; }
  get options() { return this.children; }
  get selectedOptions() { return this.children.filter(n=>n.value === this.value); }
  setAttribute(name,value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  querySelector() { return new Element('button'); }
  focus() {}
  select() {}
  scrollIntoView() {}
  dispatchEvent(event) { this['on'+event.type]?.(event); }
}
const towers = [{id:17,area:'X',lat:51.128,lon:71.431,current_load_pct:96}, {id:23,area:'Y',lat:51.145,lon:71.455,current_load_pct:91}];
const incidents = [{id:'INC-1042',tower_id:17,priority:'critical',status:'open'}, {id:'INC-1045',tower_id:23,priority:'high',status:'open'}];
const options = [
  {solution_type:'upgrade_existing',cost_kzt:12000000,available:true,installation_days:7,expected_load_pct:71},
  {solution_type:'additional_equipment',cost_kzt:18000000,available:true,installation_days:14,expected_load_pct:64},
  {solution_type:'new_tower',cost_kzt:40000000,available:true,installation_days:60,expected_load_pct:56}
];
function harness({saved = {}, url = 'http://localhost:5173/', storageBlocked = false, responder} = {}) {
  const nodes = new Map(), storage = new Map(Object.entries(saved)), calls = [];
  const html = readFileSync(join(__dirname,'../index.html'),'utf8');
  for (const match of html.matchAll(/id="([^"]+)"/g)) nodes.set(match[1],new Element());
  nodes.get('budget').value = '20000000'; nodes.get('work-order').hidden = true;
  const location = {href:url};
  const context = vm.createContext({console, URL, URLSearchParams, AbortController, TypeError, Intl, Date,
    document:{getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),querySelectorAll:()=>[],addEventListener(){}},
    location, history:{replaceState:(_,__,next)=>location.href=String(next)}, navigator:{},
    localStorage:{getItem:key=>{ if(storageBlocked) throw Error('disabled'); return storage.get(key) ?? null; },setItem:(key,value)=>{ if(storageBlocked) throw Error('disabled'); storage.set(key,value); }},
    setInterval:()=>0, setTimeout:()=>0, clearTimeout(){},
    fetch: async (url,init) => {
      const path = new URL(url).pathname, payload = init.body && JSON.parse(init.body);
      calls.push({path,payload});
      if(responder) { const response = await responder(path,payload); if(response) return response; }
      const data = path === '/work-orders' ? {items:[]} : path === '/towers' ? {items:towers} : path === '/incidents' ? {items:incidents} : path.startsWith('/incidents/') ? {incident:incidents.find(i=>i.id===path.split('/').pop())} : path === '/simulate' ? {tower_id:payload.tower_id,budget_kzt:payload.budget_kzt,options} : {};
      return {ok:true,json:async()=>data};
    }
  });
  vm.runInContext(readFileSync(join(__dirname,'../app.js'),'utf8'),context);
  const evaluate = code=>vm.runInContext(code,context);
  const ready = async()=>{ for(let i=0;i<50 && evaluate('state.busy');i++) await new Promise(resolve=>setImmediate(resolve)); assert.equal(evaluate('state.busy'),false); assert.equal(nodes.get('error').hidden,true,nodes.get('error').textContent); };
  return {nodes,storage,calls,evaluate,ready,location};
}

test('restores preferences, URL takes precedence, and a previous choice is never restored',async()=>{
  const h = harness({url:'http://localhost:5173/?incident=INC-1045',saved:{'network-dashboard:v1:http://localhost:8000':JSON.stringify({budget:50000000,incidentId:'INC-1042',filters:{search:'1045','priority-filter':'high'}})}});
  await h.ready();
  assert.equal(h.evaluate('state.incident.id'),'INC-1045');
  assert.equal(h.evaluate('budget()'),50000000);
  assert.equal(h.nodes.get('priority-filter').value,'high');
  assert.equal(h.nodes.get('search').value,'1045');
  assert.equal(h.evaluate('state.choice'),null);
  assert.equal(h.calls.filter(c=>c.path==='/action').length,0);
});
test('invalid or blocked storage and obsolete filters do not break loading',async()=>{
  for(const config of [{storageBlocked:true},{saved:{'network-dashboard:v1:http://localhost:8000':'{broken'}},{saved:{'network-dashboard:v1:http://localhost:8000':JSON.stringify({budget:-1,filters:{'priority-filter':'removed'}})}}]) {
    const h=harness(config); await h.ready(); assert.equal(h.evaluate('budget()'),20000000); assert.equal(h.nodes.get('priority-filter').value,'');
  }
});
test('missing explicit incident stays unselected rather than opening another incident',async()=>{
  const h=harness({url:'http://localhost:5173/?incident=INC-MISSING'}); await h.ready();
  assert.equal(h.evaluate('state.incident'),null); assert.match(h.nodes.get('notice').textContent,/не найден/); assert.equal(h.calls.some(c=>c.path==='/simulate'),false);
});
test('budget change clears confirmation and ignores an older simulation response',async()=>{
  const h=harness(); await h.ready();
  h.evaluate('chooseOption(state.options[0])'); assert.equal(h.nodes.get('confirmation').hidden,false);
  h.evaluate("api = () => new Promise(resolve => { globalThis.finishSimulation = resolve; })");
  const pending=h.evaluate('simulate()');
  h.nodes.get('budget').value='10000000'; h.nodes.get('budget').oninput();
  h.evaluate('finishSimulation({tower_id:17,budget_kzt:20000000,options:[{solution_type:"old"}]})'); await pending;
  assert.equal(h.evaluate('state.simulation'),null); assert.equal(h.evaluate('state.choice'),null); assert.equal(h.evaluate('state.options.length'),0); assert.equal(h.nodes.get('confirmation').hidden,true);
  assert.equal(h.nodes.get('decision-hint').hidden,true); assert.equal(h.nodes.get('comparison').hidden,true);
});
test('comparison uses only affordable options, includes tied winners, and handles missing metrics',async()=>{
  const h=harness(); await h.ready();
  const summary=h.nodes.get('decision-hint').textContent;
  assert.match(summary,/Модернизация вышки/); assert.match(summary,/Доп. оборудование/); assert.doesNotMatch(summary,/Новая вышка/);
  h.evaluate('renderDecisionSummary([{name:"A",cost_kzt:12},{name:"B",cost_kzt:12}])');
  assert.match(h.nodes.get('decision-hint').textContent,/A \/ B/); assert.doesNotMatch(h.nodes.get('decision-hint').textContent,/undefined|NaN/);
});
test('failed action is sent once; concurrent click does not create another request',async()=>{
  const h=harness(); await h.ready(); h.evaluate('chooseOption(state.options[0])');
  h.evaluate('api = () => { globalThis.actionCalls = (globalThis.actionCalls || 0) + 1; return new Promise((resolve,reject)=>globalThis.failAction=reject); }');
  const request=h.nodes.get('create-order').onclick();
  await h.nodes.get('create-order').onclick();
  h.evaluate('failAction(new Error("Uncertain action result"))'); await request;
  assert.equal(h.evaluate('actionCalls'),1); assert.equal(h.nodes.get('error').hidden,false);
});
test('map keeps API coordinates, blocks invalid coordinates and does not change incident on tower inspection',async()=>{
  const h=harness(); await h.ready();
  assert.equal(h.evaluate('hasCoordinates({lat:91,lon:71})'),false);
  assert.equal(h.evaluate('hasCoordinates({lat:null,lon:71})'),false);
  h.nodes.get('tower-picker').value='23'; h.nodes.get('tower-picker').onchange();
  assert.equal(h.evaluate('state.incident.id'),'INC-1042'); assert.equal(h.evaluate('state.towerId'),23);
  assert.match(h.nodes.get('tower-details').textContent,/INC-1045/);
  const src = h.nodes.get('map-external').href;
  assert.equal(new URL(src).searchParams.get('mlat'),'51.145');
  assert.equal(new URL(src).searchParams.get('mlon'),'71.455');
});
test('freshness represents last full network load and becomes stale after five minutes',async()=>{
  const h=harness(); await h.ready();
  h.evaluate('state.lastUpdatedAt = Date.now()-6*60000; renderFreshness()');
  assert.match(h.nodes.get('data-freshness').textContent,/обновите данные/);
  h.evaluate('state.lastUpdatedAt = null; renderFreshness()'); assert.equal(h.nodes.get('data-freshness').classes.has('stale'),false);
});
test('settings are scoped by API; connection errors cannot be masked by a successful sibling request',async()=>{
  const h=harness({responder:async path=>{if(path==='/towers') throw new TypeError('network');}});
  for(let i=0;i<25 && h.evaluate('state.busy');i++) await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.nodes.get('api-indicator').textContent,'Нет связи с API');
  const good=harness(); await good.ready(); good.evaluate("savePreferences(); state.base='http://localhost:8001'");
  assert.equal(good.evaluate('readPreferences().budget'),undefined);
  assert.throws(()=>good.evaluate("validateBase('https://user:secret@example.com')"));
});


test('unified server uses the page origin instead of localhost on a teammate computer',async()=>{
  const h=harness({url:'http://demo-server:8123/?incident=INC-1042'}); await h.ready();
  assert.equal(h.evaluate('state.base'),'http://demo-server:8123');
});
test('analysis explicitly targets the selected incident',async()=>{
  const h=harness({responder:async(path,payload)=>path==='/analyze' ? {ok:true,json:async()=>({incident:incidents[0],agent_steps:[],agent_mode:'demo'})} : null});
  await h.ready(); h.nodes.get('window').value='60';
  h.nodes.get('analysis-form').onsubmit({preventDefault(){}}); await h.ready();
  assert.equal(h.calls.find(c=>c.path==='/analyze').payload.incident_id,'INC-1042');
});
test('studio prioritizes affordable load reduction but allows inspection of an unaffordable option',async()=>{
  const h=harness(); await h.ready();
  h.evaluate("state.labPriority='expected_load_pct'; state.labFocus=null; renderDecisionLab()");
  assert.equal(h.evaluate('state.labFocus'),'additional_equipment');
  assert.equal(h.evaluate('state.choice'),null);
  h.evaluate("state.labFocus='new_tower'; renderDecisionLab()");
  const cta=h.nodes.get('lab-focus').children.at(-1);
  assert.equal(cta.disabled,true);
  assert.match(cta.textContent,/20.*000.*000/);
  assert.equal(h.calls.filter(c=>c.path==='/action').length,0);
});
test('studio comparison uses percentage points and clears with stale simulation',async()=>{
  const h=harness(); await h.ready();
  assert.match(h.nodes.get('lab-difference').textContent,/6.*000.*000.*дешевле/);
  assert.match(h.nodes.get('lab-difference').textContent,/7 п.п. выше/);
  h.evaluate('invalidate()');
  assert.equal(h.nodes.get('decision-lab').hidden,true);
  assert.equal(h.evaluate('state.labFocus'),null);
});

 test('missing map library falls back to the local scheme',async()=>{
  const h=harness(); await h.ready();
  h.nodes.get('network-panel').open=true;
  h.evaluate('renderStreetMap()');
  assert.equal(h.nodes.get('street-map').hidden,true);
  assert.equal(h.nodes.get('map').hidden,false);
  assert.equal(h.nodes.get('fit-network').disabled,true);
  assert.match(h.nodes.get('street-status').textContent,/Библиотека карты не загрузилась/);
});
