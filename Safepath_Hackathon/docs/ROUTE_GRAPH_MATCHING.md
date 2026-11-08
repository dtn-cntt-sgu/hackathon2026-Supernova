# OSRM / OSM graph attribution

Proximity never establishes route identity. The router requests OSRM `annotations=nodes`, which contains original OSM node IDs for each leg. The road importer preserves the original way node array and its consecutive endpoint pairs. A route step becomes `OSRM_NODE_PAIRS_VERIFIED` only when all these conditions hold:

- A build-produced graph manifest validates the SHA-256 of the mounted OSRM artifacts. Its PBF MD5 must equal each selected PostGIS way's import provenance.
- Annotation node pairs resolve uniquely to an imported way/edge; explicit OSM direction/access restrictions agree.
- Selected pairs form one consecutive portion of the annotation sequence and cover the entire step geometry within 0.75 m. Parallel roads, bridges, duplicate-way ambiguity, disconnected fragments, and missing node IDs fail closed.
- A camera still needs independent GPS/view/line-of-sight proof, exact edge identity, routing permission, current model identity and fresh verified capture time. Matching a road never grants camera permission.

OSRM excludes user supplied endpoint coordinates from node annotations. Consequently short endpoint steps may remain unverified when their phantom edge cannot be established. This is intentional; the next complete steps can still be verified.

Each verified edge is scored independently. The step retains the strongest physical hazard and closure, sums per-edge traffic delays, and reports partial observation coverage honestly. An exact multi-edge step does not expose a fabricated single way ID. Independent verified community reports require fresh, unexpired, exact-edge evidence whose source PBF hash and node pair still match the current import; FLOOD/ACCIDENT/OTHER are moderate, BLOCKED is critical and closed. Daily tide bulletins never imply road flooding.

Critical/closed routes rank behind alternatives without established critical/closure hazards. Ranking still uses the existing ETA + delay + 7,200 seconds/closure + 3,600 seconds/critical + 180 seconds/moderate policy. If all alternatives are critical/closed, every result is `NO_SAFE_ROUTE` and none is recommended. UNKNOWN never means SAFE. Mixed SAFE/UNKNOWN or a failed edge scoring call preserves UNKNOWN unless an established MODERATE/CRITICAL hazard is present. Traffic observation length remains separate from risk coverage.

## Deployment

Apply Alembic migration `20261108_04` (and later revisions), then explicitly rebuild/import graph data in an approved maintenance window. `scripts/setup_osrm_hcm.sh` emits `data/osrm/graph-manifest.json` only after a successful extract/partition/customize build. `scripts/import_osm_roads_hcm.sh` must read the identical PBF. Mount the same complete graph directory read-only into both OSRM and API; set `OSRM_GRAPH_MANIFEST_PATH=/app/data/osrm/graph-manifest.json`. The configured OSRM endpoint must serve this mounted graph, not an unrelated remote deployment. Manifest generation and graph installation are privileged deployment operations, not client inputs.

Graph hashing runs outside the API event loop and is cached by file stat signature. A cold proof check reads all graph files; warm it at startup when installing a graph. Any modified artifact invalidates proof. Algorithm version and manifest identity participate in the raw OSRM cache key. Cached spatial flags are always reset; exact matching and current evidence are re-evaluated on every route request. Moderation never waits for raw-route cache expiry.

Existing graph artifacts without a build manifest and existing imported rows without node IDs remain blocked. Do not invent a manifest for an old graph. Edge rebuild invalidates camera edge references through the existing foreign key; reverify views after a changed graph import.

No existing local graph, road data or camera permissions were modified by this implementation.

## Verification and primary references

`backend/tests/test_exact_route_matching.py` uses clearly synthetic OSM/OSRM records in disposable real PostGIS databases. It covers multi-edge scoring and real route assembly/ranking, parallel/stacked/junction geometry, one-way rejection, incomplete topology/coverage, duplicate-way ambiguity, provenance mismatch, graph mutation, independent incident gates and all-hazardous recommendation suppression. Migration tests cover fresh and adopted databases.

- [OSRM annotation node contract](https://project-osrm.org/docs/v5.22.0/api/)
- [osm2pgsql flex way node arrays](https://osm2pgsql.org/doc/manual-v1.html)
