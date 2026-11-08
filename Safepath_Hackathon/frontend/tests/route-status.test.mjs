import test from 'node:test';
import assert from 'node:assert/strict';
import { recommendationLabel } from '../src/lib/route-status.ts';

test('unknown and unsafe routes never receive a safety label', () => {
  const route = { route_status: 'ROUTE_FOUND_RISK_UNKNOWN', overall_risk: 'UNKNOWN', unknown_segments_count: 1, critical_segments_count: 0, segments: [] };
  assert.equal(recommendationLabel(route), 'Tuyến đề xuất');
  assert.match(recommendationLabel({...route, route_status:'NO_SAFE_ROUTE'}), /cần tránh/);
  assert.match(recommendationLabel({...route, overall_risk:'CRITICAL', critical_segments_count:1}), /cần tránh/);
  assert.equal(recommendationLabel({...route, overall_risk:'SAFE', unknown_segments_count:0}), 'Tuyến đề xuất');
});
