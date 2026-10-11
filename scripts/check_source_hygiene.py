#!/usr/bin/env python3
"""Small tracked-file hygiene gate; not a comprehensive secret scanner."""
from pathlib import Path
import re
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
blocked=[]
for name in filter(None,files):
    path=Path(name)
    if (path.parts[0] in {'data','logs'} or path.name=='.env' or
        (path.name.startswith('.env.') and path.name!='.env.example') or
        path.suffix.lower() in {'.sqlite','.sqlite3','.db','.pem','.key','.p12','.zip'}):
        blocked.append(name)
        continue
    file=root/path
    if file.is_file():
        content=file.read_bytes()
        patterns=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', rb'gh[pousr]_[A-Za-z0-9]{30,}',rb'AKIA[0-9A-Z]{16}']
        if any(re.search(pattern,content) for pattern in patterns): blocked.append(name)
if blocked:
    print('Review sensitive tracked files (values withheld):\n'+'\n'.join(blocked))
    sys.exit(1)
print('PASS: tracked-file hygiene. Also use GitHub secret scanning and push protection.')
