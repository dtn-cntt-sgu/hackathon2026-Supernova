"""Runner safety/metric checks; fixture results are not field benchmark evidence."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from scripts.benchmark_eval.performance import distribution
from scripts.benchmark_eval.operational import local_origin,k6_load
from scripts.run_hackathon_benchmark import chart,flatten,write_json


def test_percentiles_and_fps_are_measured_in_own_scope():
    stats=distribution([10,20,30])
    assert stats['samples']==3 and stats['mean_ms']==20
    assert stats['p50_ms']==20 and stats['p95_ms']==pytest.approx(29)
    assert stats['serial_calls_per_second']==50
    assert distribution([]) is None


@pytest.mark.parametrize('url',['https://example.org','http://localhost.evil.org','http://user:secret@localhost:8000','file:///tmp/x','http://127.0.0.1:8000/x','http://localhost:8000/?key=secret','http://0.0.0.0:8000'])
def test_load_target_cannot_be_remote_or_credential_url(url):
    with pytest.raises(ValueError):local_origin(url)


def test_export_handles_real_missing_metrics_without_inventing_zero(tmp_path):
    write_json(tmp_path/'metric.json',{'status':'NOT EVALUATED','iou':None})
    assert json.loads((tmp_path/'metric.json').read_text())['iou'] is None
    chart(tmp_path/'empty.png','No measured latency',[])
    assert (tmp_path/'empty.png').is_file()
    assert list(flatten({'metric':{'a':3,'missing':None}})) == [('metric.a',3)]


def test_k6_stops_after_failing_scenario_and_keeps_exit_code(tmp_path,monkeypatch):
    monkeypatch.setattr('shutil.which',lambda _: '/test/k6')
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        report=Path(command[command.index('--summary-export')+1])
        report.write_text(json.dumps({'metrics':{'http_reqs':{'count':1,'rate':1},'http_req_failed':{'value':1},'route_search_error_rate':{'value':1}}}))
        return Mock(returncode=99,stdout='failure',stderr='')
    monkeypatch.setattr('subprocess.run',run)
    result=k6_load(tmp_path,'http://127.0.0.1:8012',full=True)
    assert result['status']=='FAILED' and len(calls)==1
    assert result['levels'][0]['exit_code']==99


def test_qa_context_validates_actual_database_and_all_service_targets(tmp_path):
    from scripts.benchmark_eval.operational import validated_context
    context={'database_name':'safepath_qa_sample','DATABASE_URL':'postgresql+asyncpg://user:secret@127.0.0.1:5432/safepath_qa_sample',
             'REDIS_URL':'redis://127.0.0.1:6379/15','OSRM_BASE_URL':'http://127.0.0.1:5001'}
    path=tmp_path/'context.json';path.write_text(json.dumps(context))
    assert validated_context(path)['database_name']=='safepath_qa_sample'
    for overrides in ({'DATABASE_URL':'postgresql://u:p@127.0.0.1/safepath_db'},
                      {'REDIS_URL':'redis://127.0.0.1:6379/0'}, {'OSRM_BASE_URL':'https://router.project-osrm.org'},
                      {'DATABASE_URL':'postgresql://u:p@db.example/safepath_qa_sample'}):
        path.write_text(json.dumps(context|overrides))
        with pytest.raises(ValueError):validated_context(path)


def test_csv_keeps_nested_run_and_load_measurements_and_public_redaction():
    from scripts.run_hackathon_benchmark import sanitize_public
    assert list(flatten({'runs':[{'p95_ms':4.2}]}))==[('runs[0].p95_ms',4.2)]
    value={'source':'https://user:password@example.org/a?key=private','reason':'missing /Users/owner/private/image.jpg token=abcdef'}
    public=json.dumps(sanitize_public(value))
    for secret in ('user:password','key=private','/Users/owner','token=abcdef'):assert secret not in public


def test_offline_scenarios_do_not_start_network_or_database(tmp_path,monkeypatch):
    from scripts.benchmark_eval.operational import route_scenarios
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        report=Path(next(arg.split('=',1)[1] for arg in command if arg.startswith('--junitxml=')))
        report.write_text('<testsuites><testsuite><testcase classname="fixture" name="offline" time="0.1"/></testsuite></testsuites>')
        return Mock(stdout='unit fixture only',stderr='',returncode=0)
    monkeypatch.setattr('subprocess.run',run)
    result=route_scenarios(tmp_path,None)
    assert result['passed']==1 and len(calls)==1
    assert 'test_exact_route_matching.py' not in ' '.join(calls[0])


def test_isolated_server_socket_guard_blocks_external_dns_and_connect(monkeypatch):
    import socket
    from scripts.benchmark_eval.local_server import restrict_network,is_loopback
    assert is_loopback(b'127.0.0.1') and is_loopback('127.0.0.1') and is_loopback('::1') and not is_loopback('localhost.example.org')
    monkeypatch.setattr(socket.socket,'connect',socket.socket.connect)
    monkeypatch.setattr(socket.socket,'connect_ex',socket.socket.connect_ex)
    monkeypatch.setattr(socket,'getaddrinfo',socket.getaddrinfo)
    restrict_network()
    with pytest.raises(OSError,match='External DNS'):socket.getaddrinfo('example.org',443)
    with socket.socket() as sock:
        with pytest.raises(OSError,match='External network'):sock.connect(('8.8.8.8',443))
        assert sock.connect_ex(('8.8.8.8',443)) == 101
