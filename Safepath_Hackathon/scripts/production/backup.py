"""Create and validate a protected PostgreSQL custom-format backup; never restores data."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", default="safepath-production")
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error("Protected environment file does not exist")
    output = args.output.resolve()
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        parser.error("Refusing to overwrite an existing backup or checksum")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = ["docker", "compose", "--env-file", str(args.env_file.resolve()), "-p", args.project,
               "-f", str(ROOT / "docker-compose.prod.yml"), "exec", "-T", "postgis"]
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            result = subprocess.run(command + ["sh", "-c", 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom'],
                                    stdout=stream, stderr=subprocess.PIPE, timeout=3600)
            stream.flush()
            os.fsync(stream.fileno())
        if result.returncode or output.stat().st_size == 0:
            raise RuntimeError("Dump failed")
        with output.open("rb") as stream:
            result = subprocess.run(command + ["pg_restore", "--list"], stdin=stream,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        if result.returncode:
            raise RuntimeError("Archive validation failed")
        with output.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        checksum = output.with_suffix(output.suffix + ".sha256")
        descriptor = os.open(checksum, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(f"{digest}  {output.name}\n")
        print("PASS: protected backup and checksum created; archive directory verified. A restore rehearsal is still required.")
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        print("FAIL: backup incomplete or validation failed; no restore/migration was attempted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
