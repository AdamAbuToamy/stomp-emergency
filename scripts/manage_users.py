#!/usr/bin/env python3
"""Local administrator promotion. No public first-user-is-admin shortcut."""
import argparse
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard'))
from auth import Store
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['promote'])
parser.add_argument('username')
args = parser.parse_args()
store = Store(os.environ.get('STOMP_DATA_DIR', str(ROOT / 'data')))
try:
    store.promote(args.username)
except ValueError as error:
    raise SystemExit(str(error))
print('Administrator access granted. Refresh the browser.')
