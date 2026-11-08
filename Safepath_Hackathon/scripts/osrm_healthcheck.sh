#!/usr/bin/env bash
set -euo pipefail
exec 3<>/dev/tcp/127.0.0.1/5000
printf 'GET /route/v1/driving/106.698,10.7725;106.7115,10.8012?overview=full&geometries=geojson HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3
timeout 5 grep -Eq '"code"[[:space:]]*:[[:space:]]*"Ok"' <&3
