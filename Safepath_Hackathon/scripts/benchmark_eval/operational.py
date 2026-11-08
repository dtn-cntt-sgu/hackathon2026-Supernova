"""Bounded local-only measurement. No public camera sweeps or production load."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
from scripts.benchmark_eval.performance import distribution


def local_origin(url):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or parsed.hostname not in ('localhost','127.0.0.1','::1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Benchmark accepts only an explicit localhost origin without credentials/query/fragment')
    if parsed.path not in ('','/'):
        raise ValueError('Use a localhost origin without a path')
    return url.rstrip('/')


def validated_context(path):
    """Check actual connection targets, not a caller-supplied display name."""
    from sqlalchemy.engine import make_url
    ctx=json.loads(Path(path).read_text())
    database=make_url(ctx['DATABASE_URL'])
    redis=urlsplit(ctx['REDIS_URL'])
    allowed={'localhost','127.0.0.1','::1'}
    if (not database.database or not database.database.startswith(('safepath_readiness_qa_','safepath_qa_'))
            or ctx.get('database_name') != database.database or database.host not in allowed
            or database.get_backend_name() != 'postgresql' or database.query
            or redis.scheme!='redis' or redis.hostname not in allowed or redis.path!='/15' or redis.query or redis.fragment):
        raise ValueError('Only actual loopback scratch PostgreSQL and Redis15 connections are allowed')
    local_origin(ctx['OSRM_BASE_URL'])
    return ctx


def route_scenarios(output, context_file=None):
    """Run explicit existing specification scenarios against disposable PostGIS when available."""
    output=Path(output);env=os.environ.copy()
    commands=[['backend/tests/test_route_ai_policy.py','backend/tests/test_eta_speed_priority.py','backend/tests/test_benchmark_route_scenarios.py']]
    if context_file and Path(context_file).is_file():
        ctx=validated_context(context_file)
        if not str(ctx.get('database_name','')).startswith(('safepath_readiness_qa_','safepath_qa_')):
            raise ValueError('Only isolated QA database context is accepted')
        env.update({k:str(v) for k,v in ctx.items() if k!='database_name'})
        commands.append(['backend/tests/test_exact_route_matching.py'])
    else:
        ctx=None
    import xml.etree.ElementTree as ET
    cases=[];logs=[]
    for index,tests in enumerate(commands):
        report=output/f'route-scenarios-{index}.xml'
        command=[sys.executable,'-m','pytest',*tests,'-q','--tb=short',f'--junitxml={report}']
        start=time.perf_counter()
        try:
            run=subprocess.run(command,env=env,capture_output=True,text=True,timeout=120)
            # Logs remain local/private. Public report contains only test identities/outcomes.
            log=output/f'route-scenarios-{index}.log';log.write_text(run.stdout+run.stderr);log.chmod(0o600)
            logs.append({'command':'python -m pytest '+' '.join(tests)+' -q','exit_code':run.returncode,'wall_seconds':time.perf_counter()-start})
            if report.exists():
                for case in ET.parse(report).iter('testcase'):
                    outcome='FAIL' if case.find('failure') is not None or case.find('error') is not None else 'SKIP' if case.find('skipped') is not None else 'PASS'
                    cases.append({'name':case.attrib['classname']+'.'+case.attrib['name'],'outcome':outcome,'seconds':float(case.attrib.get('time',0))})
                report.unlink() # XML failure traces can include local paths/credentials; never publish them.
        except subprocess.TimeoutExpired:
            logs.append({'command':'python -m pytest '+' '.join(tests),'exit_code':124,'wall_seconds':time.perf_counter()-start})
    passed=sum(c['outcome']=='PASS' for c in cases);total=sum(c['outcome']!='SKIP' for c in cases)
    return {'status':'LIMITED' if cases and passed==total and all(l['exit_code']==0 for l in logs) else 'FAILED',
            'reason':'Specification/unit scenarios, with labelled synthetic evidence; NOT field AI accuracy or road-safety guarantee.',
            'passed':passed,'total':total,'pass_ratio':passed/total if total else None,'scenarios':cases,'commands':logs,
            'postgis_integration':'EXECUTED' if ctx else 'BLOCKED: no isolated QA context',
            'scenario_wall_time_scope':'Includes pytest fixture/setup; not route-computation latency.',
            'eta_error':{'status':'NOT EVALUATED','reason':'No measured actual trip durations / paired ground truth.'}}


async def camera_snapshot(base_url, sample=3):
    """Inspect local registry/storage metadata and a few local original-image responses only."""
    base=local_origin(base_url);start=time.perf_counter()
    async with httpx.AsyncClient(timeout=12,follow_redirects=False,trust_env=False) as client:
        try:
            response=await client.get(base+'/api/v1/cameras');response.raise_for_status();payload=response.json()
            cameras=payload if isinstance(payload,list) else payload.get('cameras',[])
            summary_response=await client.get(base+'/api/v1/cameras/summary');summary_response.raise_for_status();summary=summary_response.json()
        except (httpx.HTTPError,ValueError,TypeError):
            return {'status':'BLOCKED','reason':'Local camera metadata endpoint unavailable; no camera results substituted.'}
        statuses=Counter(str(c.get('source_status','UNKNOWN')) for c in cameras)
        rows=[]
        # Only local original reads; they may cause one normal provider fetch each.
        selected=[c for c in cameras if c.get('has_image')][:sample]
        from backend.app.services.image_validator import validate_camera_image_bytes
        for camera in selected:
            then=time.perf_counter()
            try:
                image=await client.get(base+f"/api/v1/cameras/{camera['cam_id']}/image?type=original")
                valid=image.status_code==200 and validate_camera_image_bytes(image.content).is_valid
                rows.append({'sample':len(rows)+1,'http_status':image.status_code,'valid_image':bool(valid),
                             'retrieved_at':image.headers.get('x-retrieved-at'),'elapsed_ms':(time.perf_counter()-then)*1000,
                             'capture_time_verified':False})
            except httpx.HTTPError:rows.append({'sample':len(rows)+1,'http_status':None,'valid_image':False})
    # Keep arbitrary endpoint fields/user IDs out of published artifacts.
    allowed=('total_registered','valid_gps_count','checked_count','valid_images_count','stale_images_count','unavailable_count','analyzed_count','cycle_checked_count','cycle_target_sec','last_scheduler_cycle','cycle_target_met')
    import datetime
    now=datetime.datetime.now(datetime.timezone.utc);ages=[]
    for camera in cameras:
        timestamp=camera.get('captured_at')
        if not timestamp:continue
        try:
            parsed=datetime.datetime.fromisoformat(timestamp.replace('Z','+00:00'))
            if parsed.tzinfo is not None and parsed<=now:ages.append((now-parsed).total_seconds())
        except (ValueError,TypeError):pass
    return {'status':'LIMITED','reason':'Point-in-time local metadata plus at most3 source-image probes; registry != active cameras. No fleet sweep, no uptime claim.',
            'registered_count':len(cameras),'reported_status_distribution':dict(statuses),'summary':{k:summary[k] for k in allowed if k in summary},
            'sample_size':len(rows),'valid_sample_images':sum(r['valid_image'] for r in rows),'samples':rows,'wall_seconds':time.perf_counter()-start,
            'capture_age_seconds':{'count':len(ages),'p50':float(__import__('numpy').percentile(ages,50)) if ages else None,'p95':float(__import__('numpy').percentile(ages,95)) if ages else None},
            'refresh_latency':{'status':'NOT EVALUATED','reason':'No controlled source publication timestamp or multi-cycle observation.'},
            'sweep_duration':{'status':'NOT EVALUATED','reason':'Full public-camera sweep intentionally not triggered.'},
            'overlay_consistency':{'status':'NOT EVALUATED','reason':'No fresh overlay audit in this metadata-only run; no public users trigger inference.'}}


def k6_load(output, base_url, *, full=False):
    import shutil
    base=local_origin(base_url)
    executable=shutil.which('k6')
    if executable is None:
        return {'status':'BLOCKED','reason':'k6 is not installed; install Grafana k6 then rerun against isolated localhost.'}
    levels=(1,10,25) if full else (1,)
    results=[]
    for vus in levels:
        target=Path(output)/f'k6-{vus}-raw.json'
        command=[executable,'run','--quiet','--summary-export',str(target),'-e',f'API_BASE_URL={base}',
                 '-e','BENCHMARK_ISOLATED=1','-e',f'K6_VUS={vus}','load_tests/k6_route_search.js']
        start=time.perf_counter()
        try:
            run=subprocess.run(command,capture_output=True,text=True,timeout=40)
            log=Path(output)/f'k6-{vus}.log';log.write_text(run.stdout+run.stderr);log.chmod(0o600)
            metrics=json.loads(target.read_text()).get('metrics',{}) if target.exists() else {}
            def metric(name):return metrics.get(name,{})
            requests=metric('http_reqs').get('count',0)
            latency=metric('http_req_duration')
            row={'concurrent_users':vus,'requests':requests,'duration_seconds':time.perf_counter()-start,
                 'requests_per_second':metric('http_reqs').get('rate'),
                 'latency':{'mean_ms':latency.get('avg'),'p50_ms':latency.get('med'),'p95_ms':latency.get('p(95)'),'p99_ms':latency.get('p(99)')},
                 'http_error_rate':metric('http_req_failed').get('value'),
                 'contract_error_rate':metric('route_search_error_rate').get('value'),
                 'timeout_rate':metric('route_search_timeout_rate').get('value'),
                 'exit_code':run.returncode,'tool':'k6'}
            target.unlink(missing_ok=True)
        except subprocess.TimeoutExpired:row={'concurrent_users':vus,'exit_code':124,'status':'BLOCKED','reason':'Bounded k6 run exceeded40s; aborted.'}
        results.append(row)
        # Stop on errors or threshold failures; never keep raising pressure after failure.
        if row.get('exit_code') or row.get('http_error_rate') or row.get('contract_error_rate'):break
    return {'status':'LIMITED' if results and all(r.get('exit_code')==0 for r in results) else 'FAILED',
            'reason':'One iteration per VU on isolated local route server, no external providers/workers. Short bursts, not sustained production capacity.',
            'tool':'k6','levels':results,
            'timeout_rate':(sum(r.get('timeout_rate',0)*r.get('requests',0) for r in results)/sum(r.get('requests',0) for r in results)
                            if results and all(r.get('timeout_rate') is not None for r in results) and sum(r.get('requests',0) for r in results) else None),
            'deferred_levels':[{'concurrent_users':level,'status':'NOT EVALUATED','reason':'Stopped before this level after error/threshold failure.'} for level in levels if level not in {r['concurrent_users'] for r in results}],
            'level_50':{'status':'NOT EVALUATED','reason':'Local Docker VM3.825GiB and OSRM memory;25-user burst limit selected.'}}


def camera_database_audit():
    """Readonly snapshot consistency audit; never starts ingestion/inference."""
    from sqlalchemy import create_engine,text
    from backend.app.core.config import settings
    engine=create_engine(settings.sync_database_url,connect_args={'connect_timeout':3})
    try:
        with engine.connect() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            row=db.execute(text('''SELECT count(*) AS snapshots,
                count(*) FILTER (WHERE inference_completed_at IS NOT NULL) AS analyzed,
                count(*) FILTER (WHERE inference_completed_at IS NOT NULL AND inference_input_sha256=content_sha256 AND overlay_path IS NOT NULL) AS consistent,
                count(*) FILTER (WHERE inference_completed_at IS NOT NULL AND inference_input_sha256 IS DISTINCT FROM content_sha256) AS mismatched,
                count(*) FILTER (WHERE source_captured_at IS NOT NULL) AS known_capture_time,
                percentile_cont(.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM(now()-fetched_at))) AS retrieval_age_p50_seconds,
                percentile_cont(.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM(now()-fetched_at))) AS retrieval_age_p95_seconds
                FROM camera_snapshots''')).mappings().one()
            counts=dict(row)
            for key,value in list(counts.items()):
                if value is not None and not isinstance(value,(int,float)):counts[key]=float(value)
            analyzed=counts['analyzed'];counts['metadata_consistency_ratio']=counts['consistent']/analyzed if analyzed else None
            counts['status']='LIMITED' if analyzed else 'NOT EVALUATED'
            counts['reason']='Stored DB metadata only; no claim that derivative bytes or capture timestamps were independently verified. Null ratio when no analyzed snapshot.'
            return counts
    finally:engine.dispose()
