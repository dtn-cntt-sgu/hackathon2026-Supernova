"""Approved dedicated-host staging deployment; no production target or implicit execution."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]


def validate_images(env):
    repository = env.get('IMAGE_REPOSITORY', '').lower()
    if not re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', repository):
        raise ValueError('IMAGE_REPOSITORY must be owner/repository')
    if not re.fullmatch(r'[0-9a-f]{40}', env.get('EXPECTED_SHA', '')):
        raise ValueError('EXPECTED_SHA must be a full commit SHA')
    for component in ('backend', 'frontend'):
        value = env.get(component.upper() + '_IMAGE', '')
        if not re.fullmatch(re.escape(f'ghcr.io/{repository}/{component}@sha256:') + r'[0-9a-f]{64}', value):
            raise ValueError(f'{component} requires an approved repository image digest')


def run(command, **kwargs):
    return subprocess.run(command, check=True, timeout=1800, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        validate_images(os.environ)
        env_file = Path(os.environ['STAGING_ENV_FILE']).resolve()
        backup_dir = Path(os.environ['STAGING_BACKUP_DIR']).resolve()
        if not env_file.is_file() or env_file.stat().st_mode & 0o077:
            raise ValueError('Staging environment file must exist and be mode 600 or stricter')
        if not args.execute:
            print('PLAN: validate provenance/preflight, backup, migrate, deploy, smoke; rollback previous application images on failure.')
            return 0
        compose = ['docker', 'compose', '--env-file', str(env_file), '-p', 'safepath-staging',
                   '-f', str(ROOT / 'docker-compose.prod.yml'), '-f', str(ROOT / 'docker-compose.staging.yml')]
        run([sys.executable, '-m', 'scripts.production.preflight', '--env-file', str(env_file)])
        run(compose + ['pull', 'backend', 'frontend'])
        for key in ('BACKEND_IMAGE', 'FRONTEND_IMAGE'):
            revision = run(['docker', 'image', 'inspect', '--format', '{{index .Config.Labels "org.opencontainers.image.revision"}}', os.environ[key]], capture_output=True, text=True).stdout.strip()
            if revision != os.environ['EXPECTED_SHA']:
                raise ValueError('Image commit provenance does not match approved commit')
        previous = {}
        for component in ('backend', 'frontend'):
            container = run(compose + ['ps', '-q', component], capture_output=True, text=True).stdout.strip()
            if container:
                previous[component.upper() + '_IMAGE'] = run(['docker', 'inspect', '--format', '{{.Image}}', container], capture_output=True, text=True).stdout.strip()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run([sys.executable, '-m', 'scripts.production.backup', '--env-file', str(env_file), '--project', 'safepath-staging', '--output', str(backup_dir / f'{stamp}.dump')])
        try:
            run(compose + ['--profile', 'tools', 'run', '--rm', '--no-deps', 'migrate'])
            run(compose + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '240', 'backend', 'frontend', 'proxy'])
            run([sys.executable, '-m', 'scripts.production.preflight', '--env-file', str(env_file), '--check-running', '--project', 'safepath-staging'])
            # Exercise API routing, frontend HTTP and service readiness from inside networks.
            run(compose + ['exec', '-T', 'backend', 'python', '-c', 'import urllib.request; urllib.request.urlopen("http://frontend:3000/", timeout=10); urllib.request.urlopen("http://127.0.0.1:8000/api/v1/cameras", timeout=10)'])
        except (subprocess.SubprocessError, OSError):
            if len(previous) == 2:
                rollback_env = dict(os.environ, **previous)
                run(compose + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '240', 'backend', 'frontend'], env=rollback_env)
                print('Application images rolled back; schema retained. Review migration and backup before database recovery.', file=sys.stderr)
            raise
        print(json.dumps({'status': 'PASS', 'environment': 'staging', 'commit': os.environ['EXPECTED_SHA']}))
        return 0
    except (KeyError, ValueError, OSError, subprocess.SubprocessError):
        print('FAIL: staging deployment incomplete; inspect protected runner logs. No automatic database restore.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
