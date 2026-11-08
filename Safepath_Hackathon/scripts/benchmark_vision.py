"""Measured single-frame inference; run with python -m scripts.benchmark_vision."""
import hashlib,json,os,platform,resource,time
from pathlib import Path
import cv2,numpy as np,onnxruntime as ort
from backend.app.services import vision
from backend.app.services.image_validator import validate_camera_image_bytes

import argparse
parser = argparse.ArgumentParser(description="Benchmark actual verified ONNX pipelines on one source image, without writing derivatives. No accuracy/SLA claim.")
parser.add_argument("--image", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--iterations", type=int, default=10)
args = parser.parse_args()
if not 1 <= args.iterations <= 1000:
    parser.error("iterations must be in [1,1000]")
root=Path(__file__).resolve().parents[1]; image=args.image.resolve()
raw=image.read_bytes(); validation=validate_camera_image_bytes(raw)
assert validation.is_valid, validation.status
assert b'TEST FRAME' not in raw
manifest=json.loads((root/'data/models/model_manifest.json').read_text())
def cpu_session(path, runtime):
    options=runtime.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    return runtime.InferenceSession(path,sess_options=options,providers=['CPUExecutionProvider'])
vision.create_accelerated_inference_session=cpu_session
result={'timestamp_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
'hardware':{'system':platform.system(),'machine':platform.machine(),'logical_cpus':os.cpu_count()},
'runtime':{'onnxruntime':ort.__version__,'available_providers':ort.get_available_providers(),'benchmark_provider':'CPUExecutionProvider','intra_op_threads':2,'inter_op_threads':1},
'frame':{'path':image.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'validation':str(validation.status),'scope':'Single caller-supplied source frame; visual provenance must be checked independently'},'models':{}}
prep=vision.preprocess_camera_image(str(image));result['frame']['dimensions']=[prep.width,prep.height]
for name,cls,method in [('vehicle_detector',vision.VehicleDetector,'detect_vehicles'),('flood_segmenter',vision.FloodSegmenter,'segment_flood_water')]:
    start=time.perf_counter();detector=cls(fallback_to_heuristic=False);init_ms=(time.perf_counter()-start)*1000
    assert detector.model_status=='VERIFIED_ONNX_INFERENCE',detector.model_status
    entry=manifest['models'][name];session=detector.session
    def meta(values):return [{'name':v.name,'shape':v.shape,'type':v.type} for v in values]
    assert session.get_inputs()[0].shape==entry['expected_input']['shape']
    assert session.get_outputs()[0].shape==entry['expected_output']['shape']
    frame=prep.original_image if name=='vehicle_detector' else prep.roi_image
    side=300 if name=='vehicle_detector' else 256
    tensor=cv2.resize(frame,(side,side))[:,:,::-1].astype(np.float32)
    tensor=tensor-np.array([123.,117.,104.],dtype=np.float32) if name=='vehicle_detector' else tensor/255.0
    tensor=np.ascontiguousarray(tensor.transpose(2,0,1)[None,...])
    raw_outputs=session.run(None,{session.get_inputs()[0].name:tensor})
    assert tensor.shape==tuple(entry['expected_input']['shape']) and tensor.dtype==np.float32
    assert raw_outputs[0].shape==tuple(entry['expected_output']['shape']) and np.isfinite(raw_outputs[0]).all()
    timings=[]; cpu=time.process_time()
    fn=getattr(detector,method)
    fn(prep) # one explicit warmup; never writes derivatives
    for _ in range(args.iterations):
        start=time.perf_counter();output=fn(prep);timings.append((time.perf_counter()-start)*1000)
    info={'model_status':detector.model_status,'model_sha256':detector.model_sha256,'init_ms':round(init_ms,3),'inputs':meta(session.get_inputs()),'outputs':meta(session.get_outputs()),'actual_input_shape':list(tensor.shape),'actual_output_shape':list(raw_outputs[0].shape),'actual_output_finite':bool(np.isfinite(raw_outputs[0]).all()),'warmup':1,'iterations':args.iterations,'timings_ms':[round(t,3) for t in timings],'p50_ms':round(float(np.percentile(timings,50)),3),'p95_ms':round(float(np.percentile(timings,95)),3),'p99_ms':round(float(np.percentile(timings,99)),3),'cpu_seconds_including_warmup':round(time.process_time()-cpu,3)}
    if name=='vehicle_detector':info['observed_vehicles']=output.vehicle_count
    else:info.update({'suspected_water_ratio':output.flood_ratio,'interpretation':'segmentation signal only; no depth, road flooding or accuracy claim'})
    result['models'][name]=info
    del detector
result['peak_process_rss_mib']=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if platform.system()=='Darwin' else 1024),2)
assert hashlib.sha256(image.read_bytes()).hexdigest()==result['frame']['sha256']
args.output.write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
