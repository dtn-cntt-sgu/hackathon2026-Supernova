#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'Docker is required' >&2; exit 1; }
command -v curl >/dev/null || { echo 'curl is required' >&2; exit 1; }
mkdir -p data/osrm
source_url='https://download.geofabrik.de/asia/vietnam-latest.osm.pbf'
pbf='data/osrm/vietnam-latest.osm.pbf'
# Use the whole Vietnam extract to preserve cross-boundary roads and turn restrictions.
curl --fail --location --retry 3 --output "$pbf.md5" "${source_url}.md5"
expected="$(awk '{print $1}' "$pbf.md5" | tr '[:upper:]' '[:lower:]')"
checksum() {
  if command -v md5sum >/dev/null; then md5sum "$1" | awk '{print $1}';
  elif command -v md5 >/dev/null; then md5 -q "$1";
  else echo 'md5sum or md5 is required' >&2; exit 1; fi
}
[[ "$expected" =~ ^[a-f0-9]{32}$ ]] || { echo 'Invalid Geofabrik checksum file' >&2; exit 1; }
if [[ -s "$pbf" && "$(checksum "$pbf")" == "$expected" ]]; then
  echo 'Existing PBF matches Geofabrik checksum.'
else
  curl --fail --location --retry 3 --output "$pbf.part" "$source_url"
  test -s "$pbf.part"
  [[ "$(checksum "$pbf.part")" == "$expected" ]] || { echo 'Geofabrik checksum mismatch' >&2; exit 1; }
  mv "$pbf.part" "$pbf"
fi
# Keep the same image/profile as the serving container to avoid file format mismatches.
threads="${OSRM_THREADS:-2}"
image='osrm/osrm-backend@sha256:af5d4a83fb90086a43b1ae2ca22872e6768766ad5fcbb07a29ff90ec644ee409'
docker run --rm -v "$(pwd)/data/osrm:/data" "$image" osrm-extract --threads "$threads" -p /opt/car.lua /data/vietnam-latest.osm.pbf
docker run --rm -v "$(pwd)/data/osrm:/data" "$image" osrm-partition --threads "$threads" /data/vietnam-latest.osrm
docker run --rm -v "$(pwd)/data/osrm:/data" "$image" osrm-customize --threads "$threads" /data/vietnam-latest.osrm
for suffix in osrm osrm.geometry osrm.names osrm.properties osrm.partition osrm.mldgr osrm.cells; do
  test -s "data/osrm/vietnam-latest.$suffix" || { echo "Missing/empty output: vietnam-latest.$suffix" >&2; exit 1; }
done
printf 'OSRM MLD files ready. Run: docker compose up -d osrm && scripts/check_osrm.sh\n'
# Emit only after every build stage succeeds; never manufacture proof for old graphs.
python3 - "$pbf" "$source_url" "$image" <<'PY'
import hashlib, json, pathlib, sys
pbf = pathlib.Path(sys.argv[1])
files = {}
for path in sorted(pbf.parent.glob('vietnam-latest.osrm*')):
    if path.is_file():
        with path.open('rb') as source:
            files[path.name] = hashlib.file_digest(source, 'sha256').hexdigest()
with pbf.open('rb') as source:
    pbf_md5 = hashlib.file_digest(source, 'md5').hexdigest()
payload = {'schema': 1, 'source_url': sys.argv[2], 'pbf_md5': pbf_md5,
           'osrm_image': sys.argv[3], 'profile': 'car.lua', 'files': files}
target = pbf.parent / 'graph-manifest.json'
target.with_suffix('.tmp').write_text(json.dumps(payload, sort_keys=True, indent=2) + '\n')
target.with_suffix('.tmp').replace(target)
PY
