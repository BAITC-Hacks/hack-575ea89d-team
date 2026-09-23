from concurrent.futures import ThreadPoolExecutor
import sqlite3
from fastapi.testclient import TestClient
from app.main import app
from app.services import action_service

client = TestClient(app)
PAYLOAD = dict(incident_id='INC-1042', tower_id=17, solution_type='upgrade_existing', budget_kzt=20000000)


def test_dashboard_and_api_share_one_origin():
    root = client.get('/')
    assert root.status_code == 200 and 'Центр управления сетью' in root.text
    assert client.get('/app.js').status_code == 200
    assert client.get('/styles.css').status_code == 200
    assert client.get('/docs').status_code == 200
    for path in ['/backend/.env', '/.env', '/data/state.sqlite3', '/AGENTS.md', '/frontend/../backend/.env']:
        assert client.get(path).status_code == 404
    assert client.get('/health').json() == {'status': 'ok'}


def test_full_demo_and_idempotent_action():
    analysis = client.post('/analyze', json={'area':'Astana District X', 'incident_id':'INC-1042'}).json()
    assert analysis['agent_mode'] == 'demo'
    assert len(analysis['agent_steps']) == 6
    assert analysis['incident']['id'] == 'INC-1042'
    simulated = client.post('/simulate', json={'tower_id':17, 'budget_kzt':20000000}).json()
    assert [o['available'] for o in simulated['options']] == [True, True, False]
    assert simulated['options'][0]['expected_load_pct'] == 71
    first = client.post('/action', json=PAYLOAD).json()
    second = client.post('/action', json=PAYLOAD).json()
    assert first['created'] is True and second['created'] is False
    assert first['work_order'] == second['work_order']
    order_id = first['work_order']['id']
    with TestClient(app) as restarted_client:
        assert restarted_client.get('/work-orders/'+order_id).json()['work_order'] == first['work_order']
    assert len(client.get('/work-orders?incident_id=INC-1042').json()['items']) == 1
    assert client.get('/work-orders?incident_id=INC-1045').json()['items'] == []


def test_concurrent_identical_orders_create_once():
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: action_service.create_work_order(PAYLOAD), range(16)))
    assert len({r['work_order']['id'] for r in results}) == 1
    assert sum(r['created'] for r in results) == 1


def test_existing_duplicates_are_preserved_and_reused():
    first = action_service.create_work_order(PAYLOAD)['work_order']
    with sqlite3.connect(action_service.DB_PATH) as db:
        db.execute('INSERT INTO work_orders (incident_id,tower_id,solution_type,team,task,budget_kzt,priority,status,created_at) SELECT incident_id,tower_id,solution_type,team,task,budget_kzt,priority,status,created_at FROM work_orders')
    result = action_service.create_work_order(PAYLOAD)
    assert result['created'] is False and result['work_order']['id'] == first['id']
    assert len(action_service.list_work_orders()) == 2


def test_action_validation_still_applies_on_retry():
    client.post('/action', json=PAYLOAD)
    for change in [dict(budget_kzt=1), dict(tower_id=23), dict(incident_id='missing'), dict(solution_type='new_tower')]:
        assert client.post('/action', json=PAYLOAD | change).status_code == 400
    assert client.post('/action', json=PAYLOAD | {'budget_kzt':-1}).status_code == 422
    assert client.get('/work-orders/WO-0').status_code == 404
    assert client.get('/work-orders?limit=0').status_code == 422


def test_selected_incident_and_area_validation():
    response = client.post('/analyze', json={'incident_id':'INC-1045'})
    assert response.json()['incident']['id'] == 'INC-1045'
    for data in [{'incident_id':'missing'}, {'incident_id':'INC-1042','area':'Astana District Y'}]:
        assert client.post('/analyze', json=data).status_code == 400
    assert client.post('/analyze', json={'area':'missing'}).json()['incident'] is None
    assert client.post('/analyze', json={'time_window_minutes':0}).status_code == 422
    assert client.post('/simulate', json={'tower_id':999,'budget_kzt':0}).status_code == 404


def test_local_cors():
    response = client.options('/action', headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST'})
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
