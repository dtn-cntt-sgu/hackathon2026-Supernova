#!/usr/bin/env bash
set -euo pipefail
base_url="${OSRM_HOST_URL:-http://localhost:5000}"
python3 - "$base_url" <<'PY'
import json, math, sys, urllib.request
base = sys.argv[1].rstrip('/')
# Five separate HCMC origin/destination pairs, west/east/north/south and river crossing.
pairs = [
    ((106.6980, 10.7725), (106.7115, 10.8012)),
    ((106.6588, 10.8185), (106.6980, 10.7725)),
    ((106.7218, 10.7950), (106.7560, 10.8020)),
    ((106.7009, 10.7769), (106.7290, 10.7290)),
    ((106.6900, 10.7600), (106.8100, 10.8400)),
]
for start, end in pairs:
    url = (f'{base}/route/v1/driving/{start[0]},{start[1]};{end[0]},{end[1]}'
           '?overview=full&geometries=geojson&steps=true')
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)
    assert data.get('code') == 'Ok' and data.get('routes'), (url, data.get('code'))
    route = data['routes'][0]
    geometry = route.get('geometry', {})
    coords = geometry.get('coordinates', [])
    assert geometry.get('type') == 'LineString' and len(coords) >= 10, url
    assert route['distance'] > 0 and route['duration'] > 0, url
    assert all(len(p) >= 2 and all(math.isfinite(v) for v in p[:2]) for p in coords), url
    print(f'OK {start} -> {end}: {len(coords)} vertices, {route["distance"]:.0f} m, {route["duration"]:.0f} s')
PY
