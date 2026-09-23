import json
from types import SimpleNamespace as NS
import pytest
from app.services import analysis_service as service

REQUEST = {'area':'Astana District X','time_window_minutes':60}
DECISION = {'incident_id':'INC-1042','reason':'Высокая нагрузка связана с ухудшением связи.'}


def response(calls=(), text=None):
    return NS(output=[NS(type='function_call', name=name, arguments=args if isinstance(args,str) else json.dumps(args), call_id=str(i)) for i,(name,args) in enumerate(calls)], output_text=json.dumps(DECISION) if text is None else text)


def evidence():
    return [('get_complaints',REQUEST), ('get_incidents',{'area':REQUEST['area']}),
            ('get_network_data',{'tower_id':17}), ('calculate_solution',{'tower_id':17}),
            ('assign_team',{'incident_id':'INC-1042','team':'Network Team A'}),
            ('update_priority',{'incident_id':'INC-1042','priority':'critical'})]


def install_client(monkeypatch, outputs):
    import openai
    stream = iter(outputs)
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        result = next(stream)
        if isinstance(result,Exception):
            raise result
        return result
    class Fake:
        responses = NS(create=create)
        def __enter__(self): return self
        def __exit__(self,*args): pass
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:Fake())
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    monkeypatch.setenv('OPENAI_MODEL','test-only')
    return calls


def test_successful_tools_are_required_and_numbers_are_canonical(monkeypatch):
    calls = install_client(monkeypatch,[response(evidence()),response()])
    result = service.analyze(REQUEST)
    assert result['agent_mode'] == 'openai'
    assert result['incident']['complaints_count'] == 347
    assert result['incident']['reason'] == DECISION['reason']
    assert len(result['agent_steps']) == 6
    assert all(0 < call['timeout'] <= 8 for call in calls)


@pytest.mark.parametrize('text', ['not json','[]','null','1', '{}',
    json.dumps(DECISION | {'incident_id':'MISSING'}),
    json.dumps(DECISION | {'incident_id':'INC-1045'}),
    json.dumps(DECISION | {'incident_id':['INC-1042']}),
    json.dumps(DECISION | {'incident_id':None}),
    json.dumps(DECISION | {'reason':42}),
    json.dumps(DECISION | {'reason':'Нагрузка 99%'}),
    json.dumps(DECISION | {'reason':''}),
    json.dumps(DECISION | {'reason':'a'*301}),
    json.dumps(DECISION | {'complaints_count':9999})])
def test_bad_decision_falls_back_truthfully(monkeypatch,text):
    install_client(monkeypatch,[response(evidence()),response(text=text)])
    result = service.analyze(REQUEST)
    assert result['agent_mode'] == 'demo_fallback'
    assert result['incident']['id'] == 'INC-1042'
    assert any(step['status']=='error' for step in result['agent_steps'])


@pytest.mark.parametrize('missing', ['get_complaints','get_incidents','get_network_data','calculate_solution','assign_team','update_priority'])
def test_missing_confirmation_cannot_pass(monkeypatch,missing):
    install_client(monkeypatch,[response([c for c in evidence() if c[0] != missing]),response()])
    assert service.analyze(REQUEST)['agent_mode'] == 'demo_fallback'


def test_invalid_tool_calls_can_be_corrected(monkeypatch):
    bad = [('unknown',{}),('get_incidents','{bad'),('get_incidents',[]),
           ('get_network_data',{'tower_id':True}),('assign_team',{'incident_id':'INC-1045','team':'Network Team A'}),
           ('get_complaints',REQUEST | {'area':None}),('get_complaints',REQUEST | {'time_window_minutes':0})]
    install_client(monkeypatch,[response(bad),response(evidence()),response()])
    result=service.analyze(REQUEST)
    assert result['agent_mode']=='openai'
    assert sum(s['status']=='error' for s in result['agent_steps']) == len(bad)


def test_failed_assignment_does_not_count(monkeypatch):
    calls = [(n, a | {'team':'wrong'}) if n=='assign_team' else (n,a) for n,a in evidence()]
    install_client(monkeypatch,[response(calls),response()])
    assert service.analyze(REQUEST)['agent_mode']=='demo_fallback'


@pytest.mark.parametrize('error',[TimeoutError('secret must not be reflected'),RuntimeError('secret must not be reflected')])
def test_provider_failure_is_bounded_and_secret_free(monkeypatch,error):
    calls=install_client(monkeypatch,[error])
    result=service.analyze(REQUEST)
    assert result['agent_mode']=='demo_fallback' and len(calls)==1
    assert 'secret must not' not in json.dumps(result)


def test_total_deadline_is_checked_after_response(monkeypatch):
    install_client(monkeypatch,[response(evidence())])
    clock=iter([0,0,36])
    monkeypatch.setattr(service,'monotonic',lambda:next(clock))
    result=service.analyze(REQUEST)
    assert result['agent_mode']=='demo_fallback'
    assert result['agent_steps'][0]['message'].endswith('TimeoutError')


def test_no_incident_is_valid_only_when_no_evidence_exists(monkeypatch):
    request=REQUEST | {'area':'missing'}
    install_client(monkeypatch,[response([('get_complaints',request),('get_incidents',{'area':'missing'})]),response(text='{"incident_id":null,"reason":""}')])
    result=service.analyze(request)
    assert result['agent_mode']=='openai' and result['incident'] is None


def test_tool_limit_falls_back(monkeypatch):
    install_client(monkeypatch,[response([('get_incidents',{'area':REQUEST['area']})])]*12)
    assert service.analyze(REQUEST)['agent_mode']=='demo_fallback'
