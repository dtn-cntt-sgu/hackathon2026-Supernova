"""
Audits 15 live HCMC cameras from list_camera_coordinate.txt against port 8007.
Validates HTTP response codes, byte payloads, magic bytes, and placeholders.
Redacts all secrets and cookies from output logs.
"""

from datetime import datetime, timezone
import os
import sys
import time
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.core.config import settings
from backend.app.services.image_validator import validate_camera_image_bytes
from backend.app.services.vdms_parser import parse_vdms_snapshot_file


def run_audit(limit: int = 15):
    report = parse_vdms_snapshot_file("list_camera_coordinate.txt")
    up_cams = [c for c in report.cameras if c.snapshot_status == "UP"][:limit]

    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": settings.HCMC_CAMERA_REFERER,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        ),
    }
    if settings.HCMC_CAMERA_COOKIE:
        headers["Cookie"] = settings.HCMC_CAMERA_COOKIE

    now_str = datetime.now(timezone.utc).isoformat()
    print(f"Auditing {len(up_cams)} cameras against port 8007 at {now_str} (UTC)...")
    print("=" * 95)

    results = []
    with httpx.Client(verify=True, timeout=6.0) as client:
        for c in up_cams:
            ts = int(time.time() * 1000)
            url = f"{settings.HCMC_CAMERA_BASE_URL}?id={c.cam_id}&bg=black&w=300&h=230&t={ts}"
            try:
                resp = client.get(url, headers=headers)
                val = validate_camera_image_bytes(resp.content)
                results.append({
                    "cam_id": c.cam_id,
                    "code": c.code or "N/A",
                    "http_status": str(resp.status_code),
                    "bytes": len(resp.content),
                    "status": val.status.value,
                    "is_valid": val.is_valid,
                    "format": val.format or "NONE",
                })
            except Exception as exc:
                results.append({
                    "cam_id": c.cam_id,
                    "code": c.code or "N/A",
                    "http_status": "TIMEOUT",
                    "bytes": 0,
                    "status": "CONNECTION_TIMEOUT",
                    "is_valid": False,
                    "format": "NONE",
                })

    header_fmt = "{:<26} | {:<10} | {:<7} | {:<7} | {:<25} | {:<6}"
    print(header_fmt.format("CAM_ID", "CODE", "HTTP", "BYTES", "VALIDATION_STATUS", "VALID"))
    print("-" * 95)
    for r in results:
        print(header_fmt.format(r["cam_id"], r["code"], r["http_status"], str(r["bytes"]), r["status"], str(r["is_valid"])))

    valid_cnt = sum(1 for r in results if r["is_valid"])
    placeholder_cnt = sum(1 for r in results if r["status"] == "PLACEHOLDER_ERROR_FRAME")
    timeout_cnt = sum(1 for r in results if r["status"] == "CONNECTION_TIMEOUT")
    other_cnt = len(results) - (valid_cnt + placeholder_cnt + timeout_cnt)

    print("=" * 95)
    print(
        f"Audit Summary: Total Tested={len(results)}, "
        f"Valid Frames={valid_cnt}, "
        f"Server Placeholders (HTTP 200 Error)={placeholder_cnt}, "
        f"Timeouts={timeout_cnt}, "
        f"Other={other_cnt}"
    )


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    run_audit(count)

