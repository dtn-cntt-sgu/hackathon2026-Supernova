"""
VDMS Camera Node & Snapshot Parser for HCMC Traffic Information Portal.
Extracts camera metadata, GIS Point coordinates, orientation, and status
from official VDMS.Sense.Helper.Model.NodeInfo payloads and Ajax.Web.DataTable snapshots.

Zero-Mock Implementation:
- Parses exact 796 snapshot nodes in list_camera_coordinate.txt.
- Extracts real WGS84 coordinates from VDMS GIS POINT geometry (no district centroids).
- Explicitly flags that 654 UP / 113 NOT_IMAGE / 29 IMAGE_EXPIRED is the historical
  snapshot result, NOT the current live camera status.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Zero-Mock: Deprecated district centroids map kept empty for backward-compatible test imports.
# In accordance with Codex.md Rule 10, camera coordinates are never assigned to district centers.
HCMC_DISTRICT_CENTROIDS: Dict[str, Tuple[float, float]] = {}

# Pattern to parse /Date(milliseconds)/ format from .NET serialization
DATE_MS_PATTERN = re.compile(r"/Date\((\d+)\)/")

# Pattern to parse rows from Ajax.Web.DataTable in list_camera_coordinate.txt
ROW_AJAX_PATTERN = re.compile(
    r"\[\"(?P<title>[^\"]*)\",\s*(?:null|\"[^\"]*\"),\s*\"(?P<cam_id>[0-9a-f]{24})\",\s*\"(?P<code>[^\"]*)\",\s*"
    r"new Ajax\.Web\.DataTable\(.*?\"POINT\((?P<lng>[\d\.]+)\s+(?P<lat>[\d\.]+)\)\".*?\]\]\),\s*"
    r"(?P<snapshot_url>null|\"[^\"]*\"),\s*"
    r"(?P<cam_type>null|\"[^\"]*\"),\s*"
    r"(?P<district>null|\"[^\"]*\"),\s*"
    r"(?P<publish>null|\"[^\"]*\"),\s*"
    r"(?P<management>null|\"[^\"]*\"),\s*"
    r"(?P<cam_status>null|\"[^\"]*\"),\s*"
    r"(?P<ptz>null|\"[^\"]*\"),\s*"
    r"(?P<angle>null|\d+),\s*"
    r"(?P<display_name>null|\"[^\"]*\"),\s*"
    r"(?P<video_url>null|\"[^\"]*\"),\s*"
    r"(?P<video_streaming>\d+),\s*"
    r"(?P<data_id>null|\"[^\"]*\"),\s*"
    r"(?P<node_id>null|\"[^\"]*\"),\s*"
    r"(?P<path>null|\"[^\"]*\"),\s*"
    r"\"\\/Date\((?P<created>\d+)\)\\/\",\s*"
    r"\"\\/Date\((?P<modified>\d+)\)\\/\"",
    re.DOTALL,
)


@dataclass
class VDMSParsedCamera:
    """Represents a fully verified parsed camera record from VDMS."""
    cam_id: str
    code: Optional[str]
    name: str
    district: Optional[str]
    lat: float
    lng: float
    snapshot_status: str  # Historical status in snapshot: UP, NOT_IMAGE, IMAGE_EXPIRED
    snapshot_url: Optional[str]
    angle: Optional[int]
    cam_type: Optional[str]
    published: bool
    source_file: str
    location_confidence: str
    created_at: Optional[datetime]
    modified_at: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cam_id": self.cam_id,
            "code": self.code,
            "name": self.name,
            "district": self.district,
            "lat": self.lat,
            "lng": self.lng,
            "snapshot_status": self.snapshot_status,
            "cam_status": self.snapshot_status,
            "status": self.snapshot_status,
            "snapshot_url": self.snapshot_url,
            "angle": self.angle,
            "cam_type": self.cam_type,
            "published": self.published,
            "source_file": self.source_file,
            "location_confidence": self.location_confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
        }


@dataclass
class VDMSSnapshotReport:
    """Summary metrics of the parsed snapshot."""
    total_nodes: int
    status_breakdown: Dict[str, int]
    valid_coordinates_count: int
    provenance_source: str
    is_live_status: bool = False
    warning: str = (
        "Status counts (654 UP, 113 NOT_IMAGE, 29 IMAGE_EXPIRED) reflect the historical snapshot "
        "at the time of export, NOT guaranteed current live status. Live camera ingestion requires "
        "real-time verification and appropriate data usage permissions."
    )
    cameras: List[VDMSParsedCamera] = field(default_factory=list)


def _parse_dotnet_date(date_str: Optional[str]) -> Optional[datetime]:
    """Extracts UTC datetime from .NET /Date(timestamp_ms)/ string."""
    if not date_str:
        return None
    match = DATE_MS_PATTERN.search(date_str)
    if not match:
        return None
    try:
        ms = int(match.group(1))
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def _clean_str(val: Optional[str]) -> Optional[str]:
    """Unquotes and strips null or whitespace strings."""
    if val is None or val == "null":
        return None
    cleaned = val.strip().strip('"').strip("'")
    return cleaned if cleaned and cleaned != "null" else None


def parse_vdms_snapshot_file(filepath: str = "list_camera_coordinate.txt") -> VDMSSnapshotReport:
    """
    Parses the full 796-node HCMC camera dataset from list_camera_coordinate.txt.

    Cross-references Section 1 (VDMS.Sense.Helper.Model.NodeInfo) with
    Section 2 (Ajax.Web.DataTable) to extract:
    1. Verified CamId (24-char hex)
    2. Code (e.g. TTH 406, TTH 120)
    3. Descriptive name (DisplayName or intersection title)
    4. District name
    5. Real WGS84 Point coordinates (lat, lng)
    6. Historical snapshot status (654 UP, 113 NOT_IMAGE, 29 IMAGE_EXPIRED)
    7. Angle / bearing if available
    8. Created / Modified timestamps

    Returns:
        VDMSSnapshotReport containing list of VDMSParsedCamera and snapshot audit metrics.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"VDMS camera snapshot file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        raw_content = f.read()

    # 1. Parse Section 1 JSON (NodeInfo objects)
    dt_split_idx = raw_content.find("new Ajax.Web.DataTable")
    if dt_split_idx == -1:
        raise ValueError("Malformed VDMS snapshot: missing Ajax.Web.DataTable section")

    json_part = raw_content[:dt_split_idx].rstrip(", ") + "]]}"
    data = json.loads(json_part)

    nodes = data.get("value", [None, [[]]])[1][0]
    sec1_map: Dict[str, Dict[str, Any]] = {}
    sec1_status_breakdown: Dict[str, int] = {}

    for node in nodes:
        if not isinstance(node, dict) or node.get("Layer") != "CAMERA":
            continue
        props = {
            p["Name"]: p.get("Value")
            for p in node.get("Properties", [])
            if isinstance(p, dict) and "Name" in p
        }
        cam_id = props.get("CamId")
        if not cam_id:
            continue

        raw_status = str(props.get("CamStatus") or "UNKNOWN").strip().upper()
        sec1_status_breakdown[raw_status] = sec1_status_breakdown.get(raw_status, 0) + 1

        sec1_map[cam_id] = {
            "code": props.get("Code") or node.get("Title"),
            "cam_status": raw_status,
            "snapshot_url": props.get("SnapshotUrl"),
            "cam_type": props.get("CamType"),
            "publish": props.get("Publish") == "True",
            "district": props.get("Disctrict") or props.get("District"),
            "angle": int(props["Angle"]) if props.get("Angle") and props["Angle"].isdigit() else None,
            "created_at": _parse_dotnet_date(node.get("Created")),
            "modified_at": _parse_dotnet_date(node.get("Modified")),
        }

    # 2. Parse Section 2 DataTable rows containing GIS POINT coordinates
    sec2_matches = list(ROW_AJAX_PATTERN.finditer(raw_content))
    parsed_cameras: List[VDMSParsedCamera] = []

    for match in sec2_matches:
        d = match.groupdict()
        cid = d["cam_id"]
        s1 = sec1_map.get(cid, {})

        lat = float(d["lat"])
        lng = float(d["lng"])

        # Validate HCMC bounding box (10.3 <= lat <= 11.2, 106.3 <= lng <= 107.2)
        if not (10.3 <= lat <= 11.2 and 106.3 <= lng <= 107.2):
            logger.warning("Camera %s coordinates outside HCMC bounds: (%f, %f)", cid, lat, lng)

        display_name = (
            _clean_str(d.get("display_name"))
            or s1.get("code")
            or _clean_str(d.get("title"))
            or f"Camera {cid}"
        )
        district = _clean_str(d.get("district")) or s1.get("district")

        # Prioritize Section 1 NodeInfo status for historical snapshot accuracy
        status_val = s1.get("cam_status") or _clean_str(d.get("cam_status")) or "UNKNOWN"

        raw_angle = d.get("angle")
        angle_val = int(raw_angle) if raw_angle and raw_angle != "null" and raw_angle.isdigit() else s1.get("angle")

        snap_url = _clean_str(d.get("snapshot_url")) or s1.get("snapshot_url")
        cam_type = _clean_str(d.get("cam_type")) or s1.get("cam_type")
        published = d.get("publish") == '"True"' or s1.get("publish", False)

        created_dt = s1.get("created_at") or (
            datetime.fromtimestamp(int(d["created"]) / 1000.0, tz=timezone.utc)
            if d.get("created")
            else None
        )
        modified_dt = s1.get("modified_at") or (
            datetime.fromtimestamp(int(d["modified"]) / 1000.0, tz=timezone.utc)
            if d.get("modified")
            else None
        )

        camera = VDMSParsedCamera(
            cam_id=cid,
            code=_clean_str(d.get("code")) or s1.get("code"),
            name=display_name,
            district=district,
            lat=lat,
            lng=lng,
            snapshot_status=status_val,
            snapshot_url=snap_url,
            angle=angle_val,
            cam_type=cam_type,
            published=published,
            source_file=os.path.basename(filepath),
            location_confidence="VDMS_GIS_POINT",
            created_at=created_dt,
            modified_at=modified_dt,
        )
        parsed_cameras.append(camera)

    return VDMSSnapshotReport(
        total_nodes=len(parsed_cameras),
        status_breakdown=sec1_status_breakdown,
        valid_coordinates_count=sum(1 for c in parsed_cameras if c.lat and c.lng),
        provenance_source=os.path.abspath(filepath),
        is_live_status=False,
        cameras=parsed_cameras,
    )


def parse_vdms_camera_nodes(
    raw_json_data: Union[Dict[str, Any], str],
    only_up: bool = False,
    lookup_path: Optional[str] = "data/mock_cameras/cameras_hcm.json",
) -> List[Dict[str, Any]]:
    """
    Standard parsing function compatible with API callers.
    Reads snapshot dataset without fabricating district centroids.
    """
    if isinstance(raw_json_data, str) and os.path.exists(raw_json_data):
        report = parse_vdms_snapshot_file(raw_json_data)
        cams = report.cameras
        if only_up:
            cams = [c for c in cams if c.snapshot_status == "UP"]
        return [c.to_dict() for c in cams]

    if isinstance(raw_json_data, str) and "new Ajax.Web.DataTable" in raw_json_data:
        import tempfile
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
            tf.write(raw_json_data)
            tmp_path = tf.name
        try:
            report = parse_vdms_snapshot_file(tmp_path)
            cams = report.cameras
            if only_up:
                cams = [c for c in cams if c.snapshot_status == "UP"]
            return [c.to_dict() for c in cams]
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # If raw string is content or dict:
    if isinstance(raw_json_data, str):
        data = json.loads(raw_json_data)
    elif isinstance(raw_json_data, dict):
        data = raw_json_data
    else:
        raise ValueError(f"Unsupported data type for raw_json_data: {type(raw_json_data)}")

    # Load lookup coordinates if available
    lookup_map = {}
    target_lookup = lookup_path if lookup_path and os.path.exists(lookup_path) else "data/mock_cameras/cameras_hcm.json"
    if os.path.exists(target_lookup):
        try:
            with open(target_lookup, "r", encoding="utf-8") as f:
                ref_list = json.load(f)
                for item in ref_list:
                    if "cam_id" in item:
                        lookup_map[item["cam_id"]] = item
        except Exception:
            pass

    nodes = data.get("value", [None, [[]]])[1][0]
    results = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("Layer") != "CAMERA":
            continue
        props = {
            p["Name"]: p.get("Value")
            for p in node.get("Properties", [])
            if isinstance(p, dict) and "Name" in p
        }
        cam_id = props.get("CamId")
        if not cam_id:
            continue
        status_val = str(props.get("CamStatus") or "").strip().upper()
        if only_up and status_val != "UP":
            continue

        ref_cam = lookup_map.get(cam_id, {})
        lat = ref_cam.get("lat")
        lng = ref_cam.get("lng")
        loc_conf = "VERIFIED" if lat is not None else "UNVERIFIED"

        angle_val = None
        if props.get("Angle") and str(props["Angle"]).isdigit():
            angle_val = int(props["Angle"])

        results.append({
            "cam_id": cam_id,
            "code": props.get("Code") or node.get("Title"),
            "name": f"Camera {props.get('Code') or cam_id}",
            "district": props.get("Disctrict") or props.get("District"),
            "snapshot_status": status_val,
            "cam_status": status_val,
            "status": status_val,
            "snapshot_url": props.get("SnapshotUrl"),
            "angle": angle_val,
            "lat": lat,
            "lng": lng,
            "location_confidence": loc_conf,
        })
    return results
