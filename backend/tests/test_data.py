from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from app.services import data_service, agent_tools, incident_service, simulation_service


def test_team_data_is_linked_and_simulation_is_bounded():
    towers=data_service.get_towers()
    complaints=data_service.read_json('complaints.json')
    assert len(towers)==35 and len(complaints)==4200
    assert len(data_service.get_population())==12
    ids={t['id'] for t in towers}
    assert len(ids)==35
    assert len({c['id'] for c in complaints})==4200
    assert all(c['tower_id'] in ids for c in complaints)
    areas={t['id']:t['area'] for t in towers}
    assert all(c['area']==areas[c['tower_id']] for c in complaints)
    summary=agent_tools.get_complaints()
    assert summary['total']==464
    assert summary['window_basis']=='synthetic_relative_age'
    assert summary['clusters'][0]['tower_id']==17
    assert summary['clusters'][0]['complaints_count']==347
    assert agent_tools.get_complaints('missing')['total']==0
    assert len(data_service.get_complaints(tower_id=17))>=347
    assert data_service.get_population('Astana District X')['population']==18000
    assert data_service.find_nearest_tower(51.128,71.431)['id']==17
    for tower_id in ids:
        for option in simulation_service.simulate(tower_id, 20000000)['options']:
            assert 0 <= option['affected_users_improved'] <= data_service.get_tower(tower_id)['affected_users']
            assert option['expected_load_pct'] >= 0
    assert simulation_service.simulate(17,20000000)['options'][0]['affected_users_improved']==600


def test_future_and_old_complaints_are_excluded(tmp_path,monkeypatch):
    now=datetime.now(timezone.utc)
    rows=[{'tower_id':17,'timestamp':(now+timedelta(days=1)).isoformat()},
          {'tower_id':17,'timestamp':(now-timedelta(days=1)).isoformat()},
          {'tower_id':17,'timestamp':(now-timedelta(minutes=1)).isoformat()}]
    (tmp_path/'complaints.json').write_text(json.dumps(rows))
    monkeypatch.setattr(data_service,'DATA_DIR',tmp_path)
    assert agent_tools.get_complaints()['total']==1


def test_concurrent_cluster_creation_has_one_incident(tmp_path,monkeypatch):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:incident_service.create_incident(8),range(12)))
    assert sum(r['created'] for r in results)==1
    assert len({r['incident']['id'] for r in results})==1


def test_relative_age_requires_synthetic_source(tmp_path,monkeypatch):
    old=(datetime.now(timezone.utc)-timedelta(days=100)).isoformat()
    rows=[{'tower_id':17,'timestamp':old,'demo_age_minutes':10,'data_source':'synthetic'},
          {'tower_id':17,'timestamp':old,'demo_age_minutes':10},
          {'tower_id':17,'timestamp':old,'demo_age_minutes':True,'data_source':'synthetic'},
          {'tower_id':17,'timestamp':old,'demo_age_minutes':-1,'data_source':'synthetic'}]
    (tmp_path/'complaints.json').write_text(json.dumps(rows))
    monkeypatch.setattr(data_service,'DATA_DIR',tmp_path)
    assert agent_tools.get_complaints()['total']==1
