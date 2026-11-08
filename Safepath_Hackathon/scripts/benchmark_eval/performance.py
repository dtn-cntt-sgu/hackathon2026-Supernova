"""Reproducible real-frame ONNX timing, isolated from production settings/storage."""
import hashlib
import json
import os
import platform
import statistics
import time
from pathlib import Path

import cv2
import numpy as np


def distribution(values):
    if not values:
        return None
    return {"samples": len(values), "mean_ms": statistics.mean(values), "stddev_ms": statistics.pstdev(values),
            **{f"p{p}_ms": float(np.percentile(values, p)) for p in (50, 95, 99)},
            "serial_calls_per_second": 1000 / statistics.mean(values) if statistics.mean(values) > 0 else None}


def source_frames(limit=3):
    from backend.app.services.image_validator import validate_camera_image_bytes
    candidates = sorted(Path('storage/cams').glob('*.jpg'))
    good = []
    for path in candidates:
        if len(path.stem) != 24 or not all(c in '0123456789abcdef' for c in path.stem.lower()):
            continue
        raw = path.read_bytes()
        if validate_camera_image_bytes(raw).is_valid:
            good.append(path)
        if len(good) == limit:
            break
    return good


def benchmark_performance(output, *, full=False, provider='CPUExecutionProvider', frames=None):
    import onnxruntime as ort
    from backend.app.services import vision
    output = Path(output)
    paths = list(frames or source_frames())
    if not paths:
        return {"status": "BLOCKED", "reason": "No valid real local camera image; no synthetic tensors substituted."}
    # Immutable local copies avoid changing source snapshots during the run; never publish images.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='safepath-benchmark-') as private:
        copies = []
        sources = []
        for i, path in enumerate(paths):
            raw = path.read_bytes()
            copied = Path(private)/f'frame-{i}.jpg'
            copied.write_bytes(raw)
            copies.append(copied)
            sources.append({"id": f'frame-{i}', "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                            "provenance": "Existing local camera snapshot; capture time/redistribution permission not verified", "published": False})
        preps = [vision.preprocess_camera_image(str(p)) for p in copies]
        iterations, repeats, warmup = (100, 3, 5) if full else (10, 1, 2)
        if provider not in ort.get_available_providers():
            return {"status": "BLOCKED", "reason": f'Requested provider unavailable: {provider}'}
        original_factory = vision.create_accelerated_inference_session
        def factory(path, runtime):
            options = runtime.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.enable_profiling = True
            options.profile_file_prefix = str(Path(private)/'ort-profile')
            return runtime.InferenceSession(path, sess_options=options, providers=[provider, 'CPUExecutionProvider'] if provider != 'CPUExecutionProvider' else [provider])
        models = {}
        vision.create_accelerated_inference_session = factory
        try:
            for key, cls, method, input_frame, side in [
                ('vehicle_detector',vision.VehicleDetector,'detect_vehicles','original_image',300),
                ('flood_segmenter',vision.FloodSegmenter,'segment_flood_water','roi_image',256),
            ]:
                runs = []
                model_hash = None
                for repeat in range(repeats):
                    started = time.perf_counter()
                    model = cls(fallback_to_heuristic=False)
                    load_ms = (time.perf_counter()-started)*1000
                    if model.session is None or model.model_status != 'VERIFIED_ONNX_INFERENCE':
                        raise RuntimeError('Verified deployment model unavailable: '+key)
                    model_hash = model.model_sha256
                    session = model.session
                    feed_name = session.get_inputs()[0].name
                    def tensor(prep):
                        image = getattr(prep,input_frame)
                        if key == 'vehicle_detector':
                            from backend.app.services.vgg16_ssd import preprocess_vgg16_ssd_frame
                            return preprocess_vgg16_ssd_frame(image)
                        value=cv2.resize(image,(side,side),interpolation=cv2.INTER_LINEAR)[:,:,::-1].transpose(2,0,1)
                        return np.ascontiguousarray(value,dtype=np.float32)[None,...]/255.0
                    tensors = [tensor(prep) for prep in preps]
                    started=time.perf_counter(); session.run(None,{feed_name:tensors[0]}); cold_ms=(time.perf_counter()-started)*1000
                    fn=getattr(model,method)
                    started=time.perf_counter(); cold_result=fn(preps[0]); cold_pipeline_ms=(time.perf_counter()-started)*1000
                    if not cold_result.is_available:
                        raise RuntimeError('Pipeline did not perform inference')
                    for i in range(warmup):
                        session.run(None,{feed_name:tensors[i%len(tensors)]});fn(preps[i%len(preps)])
                    times={name:[] for name in ('model_only','pipeline_memory','pipeline_file','tensor_preprocessing','postprocessing_single_forward')}
                    predictions=[]
                    for i in range(iterations):
                        index=i%len(preps);prep=preps[index]
                        started=time.perf_counter(); value=tensor(prep); times['tensor_preprocessing'].append((time.perf_counter()-started)*1000)
                        started=time.perf_counter(); raw=session.run(None,{feed_name:value})[0];times['model_only'].append((time.perf_counter()-started)*1000)
                        if not np.isfinite(raw).all():raise RuntimeError('Non-finite model outputs')
                        started=time.perf_counter()
                        if key=='vehicle_detector':
                            from backend.app.services.vgg16_ssd import decode_vgg16_ssd_output
                            boxes,scores,classes,_=decode_vgg16_ssd_output(raw,conf_threshold=.20)
                            candidates=[]
                            for box,score,category in zip(boxes,scores,classes):
                                if int(category) not in vision.COCO_VEHICLE_CLASSES:continue
                                x1,y1,x2,y2=box
                                x1=max(0,min(prep.width-1,int(round(float(x1)*prep.width))))
                                y1=max(0,min(prep.height-1,int(round(float(y1)*prep.height))))
                                x2=int(round(float(x2)*prep.width));y2=int(round(float(y2)*prep.height))
                                candidates.append(([x1,y1,max(1,min(prep.width-x1,x2-x1)),max(1,min(prep.height-y1,y2-y1))],float(score),int(category)))
                            model._apply_class_aware_nms(candidates,.25,.45,.20,frame_shape=(prep.height,prep.width))
                        else:
                            probability=1/(1+np.exp(-raw.squeeze()))
                            binary=(probability>=.5).astype(np.uint8)*255
                            mask=cv2.resize(binary,(prep.width,prep.height),interpolation=cv2.INTER_NEAREST)
                            cv2.bitwise_and(mask,prep.roi_mask)
                        times['postprocessing_single_forward'].append((time.perf_counter()-started)*1000)
                        # Full mode samples costly production pipelines every fifth model call (20/run).
                        # Keep counts explicit; 100 model-only calls/run are always measured.
                        if full and i % 5 != 0:
                            continue
                        started=time.perf_counter();result=fn(prep);times['pipeline_memory'].append((time.perf_counter()-started)*1000)
                        if not result.is_available:raise RuntimeError('Pipeline returned unavailable result')
                        started=time.perf_counter();decoded=vision.preprocess_camera_image(str(copies[index]));result=fn(decoded);times['pipeline_file'].append((time.perf_counter()-started)*1000)
                        if not result.is_available:raise RuntimeError('Pipeline returned unavailable result')
                        if i<len(preps): predictions.append({"frame_id":sources[index]['id'],"vehicle_count":getattr(result,'vehicle_count',None),"water_pixel_ratio":getattr(result,'flood_ratio',None)})
                    profile_path=session.end_profiling()
                    events=json.loads(Path(profile_path).read_text())
                    executed=sorted({event.get('args',{}).get('provider') for event in events if event.get('args',{}).get('provider')})
                    if not executed: raise RuntimeError('No executed provider nodes recorded')
                    runs.append({"run":repeat+1,"loading_ms":load_ms,"cold_model_ms":cold_ms,"first_pipeline_after_model_warm_ms":cold_pipeline_ms,
                                 "configured_providers":session.get_providers(),"executed_node_providers":executed,
                                 "iterations":iterations,"warmup":warmup,"timings":{k:distribution(v) for k,v in times.items()},
                                 "raw_samples_ms":times,"prediction_counts":predictions})
                    del session,model
                    print(f'  {key}: run {repeat+1}/{repeats} complete, model={iterations}, pipeline={len(times["pipeline_file"])} samples', flush=True)
                models[key]={"model_sha256":model_hash,
                             "status":"VERIFIED","runs":runs,"pipeline_p95_ms":max(r['timings']['pipeline_file']['p95_ms'] for r in runs)}
        finally:
            vision.create_accelerated_inference_session=original_factory
    try:
        import resource
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if platform.system()=='Darwin' else 1024)
    except ImportError:rss=None
    return {"status":"LIMITED","reason":"Real-frame latency only; NOT AN ACCURACY BENCHMARK. Single host, serial calls, camera sample not representative.",
            "scope":"model_only excludes image read/tensor prep/decode; pipeline_memory includes production multiscale+NMS on predecoded frame; pipeline_file includes read/validator/ROI/quality+model but excludes HTTP/queue/overlay write",
            "stage_scope":"Diagnostic single-forward vehicle postprocessing uses confidence .25/motorcycle .20/NMS .45; production pipeline uses detect_vehicles defaults .20/.20/.45. Pre/post stages refer to one forward pass; production vehicle pipeline may run multiple forwards. Do not sum their percentiles or infer end-to-end FPS from model-only FPS.",
            "cold_scope":"Each repeat constructs a new session in the same process; OS page cache may be warm. First pipeline follows cold model call, not a completely cold application.",
            "threads":2,"ort_profiling_enabled":True,"profiling_note":"ORT profiling is enabled during timing; tracing adds overhead and results are not profiling-disabled latency.","available_providers":ort.get_available_providers(),"provider":provider,"peak_process_rss_mib":rss,"sources":sources,"models":models}
