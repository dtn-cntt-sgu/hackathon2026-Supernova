# Community incidents

`CommunityReports` on `/dashboard` persists through PostgreSQL. Migrations through `20261108_07` are required. Existing Google session or signed user bearer token is required; a client `X-User-Id` alone grants no access. Inactive accounts are rejected. Reporter IDs/emails are not returned in the report payload.

| Endpoint | Authorization | Behavior |
| --- | --- | --- |
| `POST /api/v1/user/incidents` | User | `{incident_type, description, lat, lng, observed_at}`; returns 201/PENDING |
| `GET /api/v1/user/incidents` | User | Latest 100 own reports; never another account's reports |
| `GET /api/v1/admin/incidents` | Service bearer | Latest 100 unexpired PENDING reports |
| `PATCH /api/v1/admin/incidents/{id}` | Service bearer | `{status, note, evidence_url?, osm_way_id?, edge_index?}` |
| `GET /api/v1/metrics` | Service bearer | Process-local bounded Prometheus metrics |

Types: FLOOD, ACCIDENT, BLOCKED, OTHER. Statuses: PENDING, VERIFIED, REJECTED, EXPIRED. Location is restricted to HCMC bounding box; description 10–2,000 trimmed characters. Observations require a timezone, at most six hours old and two minutes future clock tolerance. The UI explicitly submits a current observation timestamp. Response computes EXPIRED after observation+6h, even before a moderator persists that state. Risk admission is stricter: <=3h and not expired.

Limits: five submission attempts/minute per account/IP through shared Redis; ten reports/hour/account under a transaction advisory lock. Same type within roughly 55m of a recent own report is rejected with 409; no user-supplied verification/status/severity is accepted. Body and global user limits also apply. Production Redis failure denies the write instead of bypassing the limit.

Verification requires a service-authorized moderator and an independent HTTPS evidence reference; URLs are stored, never fetched. Road attribution requires an explicit nearby edge with preserved OSM node IDs and source PBF hash. Moderation captures that hash and both node IDs; risk reload requires all three still match the imported graph. Reimported/reindexed edges cannot silently inherit a previous report. Never auto-verify based on proximity. The service token is an operator capability; do not expose it to browsers or user accounts. Decisions are saved with UTC moderation time and note; authorization audit logs carry a request ID.

Only exact route-matched edges receive admitted reports. BLOCKED is CRITICAL/closed; other types are MODERATE. No report means UNKNOWN, and a flood report does not supply depth. Multiple evidence channels use the strongest hazard rather than summing the same incident repeatedly. A verified report without a road assignment is retained for moderation but does not influence routing.

No upload endpoint was added: this repository has no safe authenticated incident media storage pipeline. Do not accept arbitrary image URLs as server fetch targets. Public cross-user report publication is intentionally absent; only moderators and the original reporter see the submission API. Moderators may use protected API tooling; no public admin UI was added.

Regression: `backend/tests/test_community_incidents.py`, `backend/tests/test_exact_route_matching.py`, `frontend/e2e/community-live.spec.ts`. The browser integration uses a signed synthetic session only against isolated QA infrastructure; it is not evidence of a completed Google consent flow.
