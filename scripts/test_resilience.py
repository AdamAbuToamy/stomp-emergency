#!/usr/bin/env python3
"""Run isolated fault-injection sockets against both server implementations."""
import os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for mode in ('tpc','reactor'):
    print('Transport fault tests:',mode,flush=True)
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests_resilience','-v'],
                   cwd=root,env=dict(os.environ,RESILIENCE_MODE=mode),check=True)
print('PASS: fault scenarios on TPC and Reactor.')
