from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from scripts.generate_demo import generate
from app.services import data_service, agent_tools, incident_service, simulation_service


def test_generated_data_is_linked_repeatable_and_isolated(tmp_path,monkeypatch):
    now=datetime.now(timezone.utc)
    first=tmp_path/'first'; second=tmp_path/'second'
    manifest=generate(first, now)
    generate(second, now)
    assert manifest['counts']=={'towers':40,'incidents':3,'solutions':3,'complaints':4000,'population':40}
    assert (first/'complaints.json').read_bytes()==(second/'complaints.json').read_bytes()
    monkeypatch.setattr(data_service,'DATA_DIR',first)
    ids={t['id'] for t in data_service.get_towers()}
    assert all(c['tower_id'] in ids for c in data_service.read_json('complaints.json'))
    summary=agent_tools.get_complaints()
    assert summary['total']==4000
    assert summary['clusters'][0]['tower_id']==17
    assert summary['clusters'][0]['complaints_count']==347
    assert agent_tools.get_complaints('missing')['total']==0
    assert (first/'manifest.json').exists()
    for tower_id in ids:
        for option in simulation_service.simulate(tower_id, 20000000)['options']:
            assert 0 <= option['affected_users_improved'] <= data_service.get_tower(tower_id)['affected_users']
            assert option['expected_load_pct'] >= 0


def test_future_and_old_complaints_are_excluded(tmp_path,monkeypatch):
    now=datetime.now(timezone.utc)
    rows=[{'tower_id':17,'timestamp':(now+timedelta(days=1)).isoformat()},
          {'tower_id':17,'timestamp':(now-timedelta(days=1)).isoformat()},
          {'tower_id':17,'timestamp':(now-timedelta(minutes=1)).isoformat()}]
    (tmp_path/'complaints.json').write_text(json.dumps(rows))
    monkeypatch.setattr(data_service,'DATA_DIR',tmp_path)
    assert agent_tools.get_complaints()['total']==1


def test_concurrent_cluster_creation_has_one_incident(tmp_path,monkeypatch):
    directory=tmp_path/'data'; generate(directory)
    monkeypatch.setattr(data_service,'DATA_DIR',directory)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:incident_service.create_incident(8),range(12)))
    assert sum(r['created'] for r in results)==1
    assert len({r['incident']['id'] for r in results})==1
