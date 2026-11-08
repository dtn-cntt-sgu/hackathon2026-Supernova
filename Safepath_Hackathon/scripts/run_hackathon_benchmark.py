#!/usr/bin/env python3
"""Run measured SafePath evidence; never substitute fixture data for missing production evidence."""
import argparse
import asyncio
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def environment():
    import onnxruntime as ort
    def git(*args):
        result=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True)
        return result.stdout.strip() if result.returncode==0 else None
    manifest=json.loads((ROOT/'data/models/model_manifest.json').read_text())
    models={}
    for name,entry in manifest['models'].items():
        path=ROOT/entry['file_path']
        with path.open('rb') as data:digest=hashlib.file_digest(data,'sha256').hexdigest()
        models[name]={'version':entry['version'],'architecture':entry.get('model_type'),'sha256':digest,'manifest_sha256':entry['sha256'],
                      'hash_matches':digest==entry['sha256'],'file_bytes':path.stat().st_size,'historical_manifest_metrics':'NOT VERIFIED by this run'}
    checkpoints={}
    for path in (ROOT/'data/models').glob('*'):
        if path.suffix in ('.pt','.pth'):
            with path.open('rb') as data:digest=hashlib.file_digest(data,'sha256').hexdigest()
            checkpoints[path.name]={'sha256':digest,'bytes':path.stat().st_size,'parity_status':'NOT EVALUATED: no PyTorch execution in this ONNX benchmark'}
    cpu=platform.processor()
    if platform.system()=='Darwin':
        result=subprocess.run(['sysctl','-n','machdep.cpu.brand_string'],capture_output=True,text=True);cpu=result.stdout.strip() or cpu
    source_files={}
    for path in sorted((ROOT/'scripts').rglob('*.py')):
        if path.name=='run_hackathon_benchmark.py' or 'benchmark_eval' in path.parts:
            source_files[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    diff=subprocess.check_output(['git','diff','HEAD','--','.','!data/cameras/camera_url_manifest.json'],cwd=ROOT)
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'os':platform.platform(),'machine':platform.machine(),'cpu':cpu,
            'logical_cpus':os.cpu_count(),'python':platform.python_version(),'onnxruntime':ort.__version__,
            'available_providers':ort.get_available_providers(),'commit_sha':git('rev-parse','HEAD'),
            'branch':git('branch','--show-current'),'dirty_worktree':bool(git('status','--porcelain')),
            'tracked_diff_sha256':hashlib.sha256(diff).hexdigest(),'models':models,'checkpoint_artifacts':checkpoints,
            'working_tree_note':'Commit SHA alone does not reproduce uncommitted code; archive this source tree/diff plus dataset/model hashes.',
            'benchmark_source_sha256':source_files,'torch_available':importlib.util.find_spec('torch') is not None}


def flatten(values,prefix=''):
    if isinstance(values,dict):
        for key,value in values.items():
            yield from flatten(value,f'{prefix}.{key}' if prefix else key)
    elif isinstance(values,list):
        for index,value in enumerate(values):
            yield from flatten(value,f'{prefix}[{index}]')
    elif isinstance(values,(float,int)) and not isinstance(values,bool):
        yield prefix,values


def chart(path,title,groups):
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(1000,max(240,100+50*len(groups))),'#f5faff');draw=ImageDraw.Draw(image)
    draw.text((24,20),title,fill='#163447')
    maximum=max((v for _,v in groups),default=1) or 1
    for i,(label,value) in enumerate(groups):
        y=70+i*50;draw.text((24,y),label,fill='#163447');width=int(value/maximum*480)
        draw.rectangle((420,y,420+width,y+22),fill='#168bd2');draw.text((425+width,y),f'{value:.2f} ms',fill='#163447')
    if not groups:draw.text((24,90),'NOT EVALUATED - no measured values available',fill='#163447')
    image.save(path)


def isolated_load(output, context, full):
    from scripts.benchmark_eval.operational import k6_load
    if not context or not Path(context).is_file():
        return {'status':'BLOCKED','reason':'No isolated QA database context; refusing load against normal app or external sources.'}
    from scripts.benchmark_eval.operational import validated_context
    ctx=validated_context(context)
    if not str(ctx.get('database_name','')).startswith(('safepath_readiness_qa_','safepath_qa_')):
        return {'status':'BLOCKED','reason':'Only an isolated scratch QA DB is accepted.'}
    import secrets,socket,httpx
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=os.environ.copy();env.update({k:str(v) for k,v in ctx.items() if k!='database_name'})
    env.update(ENABLE_BACKGROUND_WORKERS='false',CAMERA_INGESTION_PERMITTED='false',CAMERA_ROUTING_EVIDENCE_PERMITTED='false',
               CAMERA_VIEW_AI_ENABLED='false',TOMTOM_API_KEY='',HERE_API_KEY='',TRAFFIC_PROVIDER='none',
               AUTH_SECRET=secrets.token_urlsafe(40),SERVICE_AUTH_TOKEN=secrets.token_urlsafe(40),RATE_LIMIT_ROUTES_PER_MINUTE='60',APP_ENV='development',TESTING='true')
    log=(Path(output)/'isolated-backend.log').open('w');os.chmod(log.name,0o600)
    env['SAFEPATH_BENCHMARK_PORT']=str(port)
    process=subprocess.Popen([sys.executable,'-m','scripts.benchmark_eval.local_server'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(40):
            try:
                ready=httpx.get(base+'/api/v1/ready',timeout=2,trust_env=False)
                if ready.status_code==200:
                    if not ready.json().get('routing_ready'):return {'status':'BLOCKED','reason':'Local OSRM is unavailable; no fake route used.'}
                    break
            except httpx.HTTPError:pass
            if process.poll() is not None:return {'status':'BLOCKED','reason':'Isolated QA server failed startup; see private local log.'}
            time.sleep(.5)
        else:return {'status':'BLOCKED','reason':'Isolated server readiness timeout.'}
        # Clear only this run's limiter scope in isolated Redis15 to avoid unrelated previous test counts.
        from redis import Redis
        redis=Redis.from_url(ctx['REDIS_URL'])
        if not ctx['REDIS_URL'].rstrip('/').endswith('/15'):
            return {'status':'BLOCKED','reason':'Isolated load requires Redis database15.'}
        for key in redis.scan_iter(match='rate:routes_search:*'):redis.delete(key)
        redis.close()
        import threading
        samples=[];finished=threading.Event()
        def monitor():
            if platform.system()=='Windows':return
            while not finished.is_set():
                reading=subprocess.run(['ps','-p',str(process.pid),'-o','%cpu=,rss='],capture_output=True,text=True)
                try:
                    cpu,rss=map(float,reading.stdout.split());samples.append({'cpu_percent_lifetime_average':cpu,'rss_mib':rss/1024})
                except ValueError:pass
                finished.wait(.25)
        observer=threading.Thread(target=monitor,daemon=True);observer.start()
        try:result=k6_load(output,base,full=full)
        finally:finished.set();observer.join(timeout=2)
        result['backend_resource_samples']={'samples':len(samples),'peak_rss_mib':max((r['rss_mib'] for r in samples),default=None),
            'maximum_lifetime_average_cpu_percent':max((r['cpu_percent_lifetime_average'] for r in samples),default=None),
            'scope':'ps CPU is process lifetime average (100%=one core), not instantaneous utilization. RSS is isolated native backend process, excludes OSRM/PostGIS/Redis/load generator. Windows collection unavailable.'}

        result['isolated_external_sources']='Disabled: camera inference/ingestion, weather/news workers, TomTom/HERE. Only local OSRM/PostGIS/Redis used.'
        return result
    finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()


def sanitize_text(value):
    """Public reports contain no credential URLs, absolute local paths or token assignments."""
    import re
    if value.startswith(('file://','/Users/','/home/','/tmp/','/mnt/','/private/','/var/')):return '[private-path]'
    value=re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@',r'\1[redacted]@',value)
    value=re.sub(r'(https?://[^\s?#]+)[?#][^\s]*',r'\1?[redacted]',value)
    value=re.sub(r'(?i)((?:secret|password|token|api_key|apikey)\s*[=:]\s*)[^\s,;]+',r'\1[redacted]',value)
    value=re.sub(r'(?:/Users/|/home/|/tmp/|[A-Za-z]:\\)[^\s\"\']+', '[private-path]',value)
    return value


def sanitize_public(value):
    if isinstance(value,dict):return {k:sanitize_public(v) for k,v in value.items()}
    if isinstance(value,list):return [sanitize_public(v) for v in value]
    return sanitize_text(value) if isinstance(value,str) else value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--quick',action='store_true');mode.add_argument('--full',action='store_true')
    parser.add_argument('--offline',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'reports/hackathon-benchmark')
    parser.add_argument('--flood-dataset',type=Path);parser.add_argument('--vehicle-dataset',type=Path)
    parser.add_argument('--compare-baseline',action='store_true',help='Evaluate single-frame vs production VGG16-SSD on the same labelled vehicle dataset.')
    parser.add_argument('--provider',default='CPUExecutionProvider',choices=['CPUExecutionProvider','CoreMLExecutionProvider','CUDAExecutionProvider'])
    parser.add_argument('--local-api',default='http://127.0.0.1:8000')
    parser.add_argument('--qa-context',type=Path,default=Path(os.environ['SAFEPATH_BENCHMARK_QA_CONTEXT']) if os.getenv('SAFEPATH_BENCHMARK_QA_CONTEXT') else None)
    parser.add_argument('--publish',action='store_true',help='Publish allowlisted sanitized data only to frontend/public/benchmark; no images/logs/private paths.')
    args=parser.parse_args();os.chdir(ROOT);output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    from scripts.benchmark_eval.operational import local_origin
    local_origin(args.local_api)
    env=environment();write_json(output/'environment.json',env)
    sections={};commands=[]
    def execute(name,fn):
        started=time.perf_counter();print('Running '+name+'...',flush=True)
        try:
            result=fn();exit_code=0 if result.get('status')!='FAILED' else 1
        except Exception as error:
            # Exceptions may contain credential URLs/SQL; keep only type in public output.
            result={'status':'FAILED','reason':'Measurement failed: '+type(error).__name__+'; inspect local command log.'};exit_code=1
        result.setdefault('measured_at',datetime.now(timezone.utc).isoformat())
        sections[name]=result;commands.append({'section':name,'exit_code':exit_code,'elapsed_seconds':time.perf_counter()-started})
        write_json(output/({'flood':'flood_metrics','vehicle':'vehicle_metrics','inference':'inference_metrics','routing':'routing_metrics','camera':'camera_metrics','load':'load_test_metrics'}[name]+'.json'),result)
        print(f"{name}: {result.get('status')} ({commands[-1]['elapsed_seconds']:.1f}s)",flush=True)
    from scripts.benchmark_eval.evaluation import evaluate_flood,evaluate_vehicle
    from scripts.benchmark_eval.performance import benchmark_performance
    from scripts.benchmark_eval.operational import route_scenarios,camera_snapshot
    execute('flood',lambda:evaluate_flood(output,args.flood_dataset))
    execute('vehicle',lambda:evaluate_vehicle(output,args.vehicle_dataset,compare_baseline=args.compare_baseline))
    execute('inference',lambda:benchmark_performance(output,full=args.full,provider=args.provider))
    execute('routing',lambda:route_scenarios(output,None if args.offline else args.qa_context))
    def camera_measurement():
        if args.offline:return {'status':'BLOCKED','reason':'Offline mode: no local API/network camera inspection performed.'}
        result=asyncio.run(camera_snapshot(args.local_api))
        from scripts.benchmark_eval.operational import camera_database_audit
        try:result['snapshot_database_audit']=camera_database_audit()
        except Exception as error:result['snapshot_database_audit']={'status':'BLOCKED','reason':'Readonly local DB audit unavailable: '+type(error).__name__}
        return result
    execute('camera',camera_measurement)
    execute('load',lambda:{'status':'NOT EVALUATED','reason':'Offline mode: local service load test not executed.'} if args.offline else isolated_load(output,args.qa_context,args.full))
    finalize_bundle(output,env,sections,commands,full=args.full,offline=args.offline,publish=args.publish)
    return 1 if any(v.get('status')=='FAILED' for v in sections.values()) else 0


def finalize_bundle(output,env,sections,commands,*,full=False,offline=False,publish=False):
    """Export existing measured sections without pretending to rerun inference."""
    chart(output/'inference_latency.png','Measured production pipeline p95 (file read included)',[(name,m['pipeline_p95_ms']) for name,m in sections['inference'].get('models',{}).items()])
    csv_path=output/'benchmark_results.csv'
    with csv_path.open('w',newline='',encoding='utf-8') as file:
        writer=csv.writer(file);writer.writerow(['section','metric','value','status'])
        for name,value in sections.items():
            for metric,number in flatten(value):writer.writerow([name,metric,number,value.get('status')])
    limitations='''# Limitations\n\nNo ground truth means no flood/vehicle accuracy claim. Model hash validation is not accuracy. Synthetic scenario pass rate is not field safety. Provider names are not proof GPU/NeuralEngine executed: use recorded ORT node providers. Serial FPS is not concurrent API throughput. Capture time may be unknown despite recent retrieval. Camera metadata is not uptime/sweep acceptance. Load bursts on scratch local infrastructure are not production capacity. PyTorch parity is blocked without torch/checkpoint evaluation data. No production config, weights, camera permissions or routes are changed.\n'''
    methodology='''# Methodology\n\nRun with Python from repository root; --quick=10 iterations/1 repeat, --full=100 iterations/3 independently constructed sessions, both use separate warmup; full mode measures100 model-only samples and20 production pipeline samples per repeat. ORT profiling is enabled during measurements and may add overhead. --offline performs no HTTP/DB operations. CPU2 threads is the benchmark configuration, not a production setting. Input images are private immutable copies of existing validated local source snapshots, not synthetic tensors. No input images are published. Model-only excludes tensor/image preprocessing; pipeline-file includes disk decode/validator/quality/ROI and deployment inference/postprocessing but excludes network/queue/overlay encoding. Pre/post statistics are single-forward diagnostics; production vehicle multiscale may execute multiple calls. Do not sum percentiles.\n\nFlood IoU=TP/(TP+FP+FN); Dice=2TP/(2TP+FP+FN), precision=TP/(TP+FP), recall=TP/(TP+FN); global counts and per-image means are separate. Undefined zero-denominator results must not become perfect scores. Vehicle AP uses explicit IoU matching and score ordering; deployment confidence thresholds limit PR recall. Refer to dataset documentation for human annotation/provenance/split requirements. Missing labels produce NOT EVALUATED, not zero/perfect accuracy.\n\nRoute scenarios are independently stated tests, labelled fixtures and optional disposable real PostGIS. Latencies of tests include setup; route-service latency is measured separately in isolated k6 bursts (one iteration per VU at1/10/25), with external providers/workers disabled.50VU deferred on constrained host. Stop on errors/threshold breaches.\n'''
    (output/'limitations.md').write_text(limitations,encoding='utf-8');(output/'methodology.md').write_text(methodology,encoding='utf-8')
    report='# SafePath measured benchmark\n\n'+f"Run: {env['generated_at']} · Commit: `{env['commit_sha']}` · Dirty: {env['dirty_worktree']}\n\n"
    for name,result in sections.items():report+=f"## {name}\n\n**{result.get('status')}** — {result.get('reason','')}\n\n"
    report+='## Commands and exit codes\n\n```json\n'+json.dumps(commands,indent=2)+'\n```\n\nSee JSON/CSV for measured values, methodology.md and limitations.md.\n'
    report+='## Measured pipeline values\n\n'
    for name,model in sections.get('inference',{}).get('models',{}).items():
        runs=model.get('runs',[])
        if runs:
            model_p95=[r['timings']['model_only']['p95_ms'] for r in runs]
            pipeline_p95=[r['timings']['pipeline_file']['p95_ms'] for r in runs]
            report+=f"- {name}: model-only p95 {min(model_p95):.2f}–{max(model_p95):.2f}ms; pipeline-file p95 {min(pipeline_p95):.2f}–{max(pipeline_p95):.2f}ms.\n"
    report+='\nThese are measured local values with declared sample counts/provider/trace overhead; not AI accuracy or production throughput.\n'
    (output/'benchmark_report.md').write_text(report,encoding='utf-8')
    write_json(output/'commands.json',{'command_argv':sys.argv,'sections':commands,'exit_code':1 if any(v.get('status')=='FAILED' for v in sections.values()) else 0})
    names=['summary.json','commands.json','environment.json','flood_metrics.json','vehicle_metrics.json','inference_metrics.json','routing_metrics.json','camera_metrics.json','load_test_metrics.json','benchmark_results.csv','benchmark_report.md','methodology.md','limitations.md','inference_latency.png']
    for task in ('flood','vehicle'):
        for filename in (f'{task}_predictions.csv',f'{task}_confusion_matrix.png'):
            if (output/filename).is_file():names.append(filename)
        examples=f'{task}_examples.png'
        if sections[task].get('dataset',{}).get('public_examples_authorized') is True and (output/examples).is_file():
            names.append(examples)
    summary={'schema_version':1,'run_id':str(uuid4()),'generated_at':env['generated_at'],'commit_sha':env['commit_sha'],'dirty_worktree':env['dirty_worktree'],
             'mode':'full' if full else 'quick','offline':offline,'sections':sections,'models':env['models'],
             'artifacts':[{'name':name,'href':'/benchmark/'+name} for name in names],
             'commands':commands,'disclaimer':'Measured local evidence only. NOT an AI accuracy or road-safety certification. Missing ground truth remains NOT EVALUATED.'}
    write_json(output/'summary.json',summary)
    if publish:
        public=ROOT/'frontend/public/benchmark';public.mkdir(parents=True,exist_ok=True)
        # Publish only known report files generated by this run. Never recursively copy logs/source images.
        optional={'flood_examples.png','vehicle_examples.png','flood_confusion_matrix.png','vehicle_confusion_matrix.png','flood_predictions.csv','vehicle_predictions.csv'}
        for stale in optional-set(names):(public/stale).unlink(missing_ok=True)
        for name in [n for n in names if n!='summary.json']+['summary.json']:
            path=output/name
            if path.suffix=='.json':write_json(public/name,sanitize_public(json.loads(path.read_text())))
            elif path.suffix in ('.md','.csv'): (public/name).write_text(sanitize_text(path.read_text()),encoding='utf-8')
            else:shutil.copyfile(path,public/name)

if __name__=='__main__':raise SystemExit(main())
