#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PBF="$ROOT/data/osrm/vietnam-latest.osm.pbf"
MD5_FILE="$PBF.md5"
[[ -s "$PBF" && -s "$MD5_FILE" ]] || { echo 'Missing Geofabrik PBF or checksum; run scripts/setup_osrm_hcm.sh' >&2; exit 1; }
if command -v md5sum >/dev/null; then
    (cd "$ROOT/data/osrm" && md5sum -c vietnam-latest.osm.pbf.md5)
else
    expected="$(awk '{print $1}' "$MD5_FILE")"
    actual="$(md5 -q "$PBF")"
    [[ "$expected" == "$actual" ]] || { echo 'PBF MD5 mismatch' >&2; exit 1; }
fi

# OSM PBF HeaderBlock field 32 is the replication/extract timestamp.
extract_timestamp="$(python3 - "$PBF" <<'PY'
import datetime, struct, sys, zlib
def fields(buf):
    pos = 0
    def varint():
        nonlocal pos
        value = shift = 0
        while True:
            byte = buf[pos]; pos += 1
            value |= (byte & 127) << shift
            if byte < 128: return value
            shift += 7
    while pos < len(buf):
        key = varint(); number, wire = key >> 3, key & 7
        if wire == 0: data = varint()
        elif wire == 2:
            size = varint(); data = buf[pos:pos+size]; pos += size
        else: raise ValueError('Unexpected PBF header wire type')
        yield number, data
with open(sys.argv[1], 'rb') as source:
    header_size = struct.unpack('>I', source.read(4))[0]
    blob_size = dict(fields(source.read(header_size)))[3]
    blob = dict(fields(source.read(blob_size)))
    header = zlib.decompress(blob[3]) if 3 in blob else blob[1]
    seconds = dict(fields(header))[32]
print(datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).isoformat())
PY
)"
md5_value="$(awk '{print $1}' "$MD5_FILE")"
echo "Importing OSM ways from Geofabrik extract $extract_timestamp (MD5 $md5_value)"

cd "$ROOT"
docker compose --env-file /dev/null exec -T postgis psql -v ON_ERROR_STOP=1 \
    -U safepath_user -d safepath_db -c 'DROP TABLE IF EXISTS osm_import_roads;'
docker compose --env-file /dev/null --profile tools run --rm osm-import \
    -d safepath_db -O flex -S /style.lua --slim --drop --cache 512 \
    --number-processes 2 /data/vietnam-latest.osm.pbf
docker compose --env-file /dev/null exec -T postgis psql -v ON_ERROR_STOP=1 \
    -v "extract_timestamp=$extract_timestamp" -v "pbf_md5=$md5_value" \
    -U safepath_user -d safepath_db < scripts/import_osm_roads.sql
docker compose --env-file /dev/null exec -T postgis psql -v ON_ERROR_STOP=1 \
    -U safepath_user -d safepath_db < scripts/build_osm_road_edges.sql
docker compose --env-file /dev/null exec -T postgis psql -v ON_ERROR_STOP=1 -U safepath_user -d safepath_db \
    -c 'SELECT count(*) AS osm_road_count, min(osm_extract_at) AS extract_at FROM road_segments WHERE source_url IS NOT NULL;'
