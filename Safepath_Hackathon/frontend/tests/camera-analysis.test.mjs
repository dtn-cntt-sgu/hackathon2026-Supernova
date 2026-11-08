// Unit-only HTTP responses. Production analysis always calls the real backend/model.
import test from 'node:test';
import assert from 'node:assert/strict';
import { prepareCameraAnalysis, cameraAnalysisImageUrl } from '../src/services/api.ts';

const camera='5deb576d1dc17d7c5515ad1a';
test('analysis binds the displayed snapshot and retries a changed source only once', async t => {
  const previous=global.fetch;t.after(()=>{global.fetch=previous;});
  const hashes=[];
  global.fetch=async (url,options)=>{
    assert.match(url,new RegExp(`/cameras/${camera}/analysis$`));
    assert.equal(options.method,'POST');
    hashes.push(JSON.parse(options.body).snapshot_id);
    return new Response(JSON.stringify(hashes.length===1?{status:'FRAME_CHANGED',content_sha256:'new-frame'}:{status:'READY',snapshot_id:'immutable-frame',image_url:'/api/v1/cameras/x/image?snapshot_id=immutable-frame',overlay_url:'/api/v1/cameras/x/image?type=analyzed&snapshot_id=immutable-frame'}),{status:200});
  };
  const result=await prepareCameraAnalysis(camera,undefined,'displayed-frame');
  assert.deepEqual(hashes,['displayed-frame','new-frame']);
  assert.equal(result.status,'READY');
  assert.match(cameraAnalysisImageUrl(result.overlay_url),/snapshot_id=immutable-frame/);
});

test('analysis rejects invalid identifiers without network work and exposes actual failure', async t=>{
  const previous=global.fetch;t.after(()=>{global.fetch=previous;});
  let calls=0;global.fetch=async()=>{calls++;return new Response(JSON.stringify({detail:{message:'Model unavailable'}}),{status:503});};
  await assert.rejects(()=>prepareCameraAnalysis('../private'),/không hợp lệ/);
  assert.equal(calls,0);
  await assert.rejects(()=>prepareCameraAnalysis(camera),/Model unavailable/);
  assert.equal(calls,1);
});

test('one source label follows the actual provider',async()=>{
  const {cameraSourceLabel}=await import('../src/components/CameraProxySnapshot.tsx');
  assert.equal(cameraSourceLabel('vietmap'),'Vietmap CDN');
  assert.equal(cameraSourceLabel('hcmc'),'Cổng Giao thông TP.HCM');
  assert.equal(cameraSourceLabel(null),'Đang xác định');
});
