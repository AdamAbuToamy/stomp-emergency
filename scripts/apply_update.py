#!/usr/bin/env python3
"""Install this source bundle; preserve Git/data and back up replaced files."""
import argparse
import datetime
import shutil
import stat
import sqlite3
import tempfile
import os
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('target', type=Path)
args = parser.parse_args()
source = Path(__file__).resolve().parents[1]
target = args.target.expanduser().resolve()
if source == target or not (target / 'server/pom.xml').is_file():
    raise SystemExit('Choose the existing stomp-emergency project directory.')
manifest = source / 'UPDATE_FILES.txt'
files = [Path(line) for line in manifest.read_text().splitlines() if line]
for rel in files:
    if rel.is_absolute() or '..' in rel.parts or not (source / rel).is_file():
        raise SystemExit('Invalid update bundle.')
    dest = target / rel
    if not dest.resolve().is_relative_to(target) or dest.is_symlink():
        raise SystemExit('Refusing to replace a path outside the project.')
backup = target.parent / ('stomp-backup-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.zip')
with zipfile.ZipFile(backup, 'x', zipfile.ZIP_DEFLATED) as archive:
    os.chmod(backup, 0o600)
    database = target / 'data/accounts.sqlite3'
    if database.is_file():
        with tempfile.TemporaryDirectory(prefix='stomp-db-backup-') as folder:
            snapshot = Path(folder) / 'accounts.sqlite3'
            original = sqlite3.connect(str(database))
            copy = sqlite3.connect(str(snapshot))
            try:
                original.backup(copy)
            finally:
                copy.close()
                original.close()
            archive.write(snapshot, 'data/accounts.sqlite3')
    key = target / 'data/bridge.key'
    if key.is_file():
        archive.write(key, 'data/bridge.key')
    for rel in files:
        if (target / rel).is_file():
            archive.write(target / rel, str(rel))
for rel in files:
    dest = target / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = stat.S_IMODE(dest.stat().st_mode) if dest.exists() else None
    shutil.copy2(source / rel, dest)
    if previous_mode is not None:
        dest.chmod(previous_mode)
print('Updated:', target)
print('Backup of replaced files:', backup)
print('Account data and Git history were preserved. Rebuild before running.')
