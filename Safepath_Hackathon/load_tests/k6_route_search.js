/**
 * SafePathAI High-Concurrency Load Testing Script using Grafana k6.
 * Live OSRM/PostGIS route benchmark. Results are observations, not guaranteed targets.
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

const routeSearchDuration = new Trend('route_search_duration_ms', true);
const errorRate = new Rate('route_search_error_rate');
const timeoutRate = new Rate('route_search_timeout_rate');
const successfulSearches = new Counter('route_search_success_count');
const failedSearches = new Counter('route_search_failure_count');
const VUS = Number(__ENV.K6_VUS || 10);
const ISOLATED = __ENV.BENCHMARK_ISOLATED === '1';
if (!Number.isInteger(VUS) || VUS < 1 || VUS > 50) throw new Error('K6_VUS must be 1..50');

export const options = {
  ...(ISOLATED ? {scenarios:{bounded:{executor:'per-vu-iterations',vus:VUS,iterations:1,maxDuration:'20s'}}} : {vus:VUS,duration:__ENV.K6_DURATION || '10s'}),
  summaryTrendStats: ['avg','min','med','max','p(95)','p(99)'],
  thresholds: {
    route_search_error_rate: [{threshold:'rate<0.2',abortOnFail:true,delayAbortEval:'2s'}],
    ...(__ENV.K6_P95_LIMIT_MS ? {route_search_duration_ms:[`p(95)<${Number(__ENV.K6_P95_LIMIT_MS)}`]} : {}),
  },
};

const BASE_URL = __ENV.API_BASE_URL || 'http://localhost:8000';
if (!/^http:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?$/.test(BASE_URL) || !ISOLATED) {
  throw new Error('Only localhost isolated QA target accepted; set BENCHMARK_ISOLATED=1 after disabling external workers/providers.');
}

// Popular coordinates across Ho Chi Minh City
const HCM_COORDINATE_PAIRS = [
  {
    origin: { lat: 10.7725, lng: 106.6980 }, // Chợ Bến Thành
    destination: { lat: 10.8012, lng: 106.7115 }, // Ngã tư Hàng Xanh
  },
  {
    origin: { lat: 10.7950, lng: 106.7218 }, // Landmark 81
    destination: { lat: 10.8185, lng: 106.6588 }, // Sân bay Tân Sơn Nhất
  },
  {
    origin: { lat: 10.7798, lng: 106.6990 }, // Nhà thờ Đức Bà
    destination: { lat: 10.7981, lng: 106.7186 }, // Nguyễn Hữu Cảnh
  },
  {
    origin: { lat: 10.7300, lng: 106.7050 }, // Phú Mỹ Hưng
    destination: { lat: 10.7725, lng: 106.6980 }, // Chợ Bến Thành
  },
];

export default function () {
  // Repeatable mix across VUs and iterations for before/after comparison.
  const pair = HCM_COORDINATE_PAIRS[(__VU + __ITER - 1) % HCM_COORDINATE_PAIRS.length];

  const payload = JSON.stringify({
    origin: pair.origin,
    destination: pair.destination,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    timeout: __ENV.K6_TIMEOUT || '5s',
  };

  const response = http.post(`${BASE_URL}/api/v1/routes/search`, payload, params);
  routeSearchDuration.add(response.timings.duration);
  timeoutRate.add(response.error_code === 1050 || response.error_code === 1211);

  // Validate response contract
  let body = null;
  if (response.status === 200 && response.body) {
    try { body = JSON.parse(response.body); } catch (_) { body = null; }
  }
  const isOk = check(response, {
    'valid live route response': () => response.status === 200 && Boolean(body) &&
      typeof body.route_id === 'string' && body.total_distance_km > 0 &&
      typeof body.ai_explanation === 'string' && body.ai_explanation.length > 0,
  });

  if (isOk) {
    successfulSearches.add(1);
    errorRate.add(0);
  } else {
    errorRate.add(1);
    failedSearches.add(1, { status: String(response.status || 0), reason: response.error_code ? String(response.error_code) : 'invalid_response' });
  }

  // Small pacing delay between requests (50ms - 150ms)
  sleep(0.05 + Math.random() * 0.1);
}

