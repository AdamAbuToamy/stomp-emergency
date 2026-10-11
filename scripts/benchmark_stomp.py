#!/usr/bin/env python3
"""Reproducible closed-loop STOMP echo benchmark; no dashboard/SQLite overhead."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import socket
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class Client:
    def __init__(self,port):
        self.sock=socket.create_connection(('127.0.0.1',port),timeout=10)
        self.buffer=b''
    def send(self,value):
        self.sock.sendall(value.encode()+b'\0')
    def receive(self):
        while b'\0' not in self.buffer:
            chunk=self.sock.recv(65536)
            if not chunk:
                raise RuntimeError('Unexpected connection closure')
            self.buffer+=chunk
        frame,self.buffer=self.buffer.split(b'\0',1)
        return frame.decode()
    def close(self):
        self.sock.close()

def occupied(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=.2): return True
    except OSError: return False

def percentile(values,p):
    values=sorted(values)
    return values[min(len(values)-1,round((len(values)-1)*p))]

def workload(port,clients,messages,size):
    clock={}
    barrier=threading.Barrier(clients,action=lambda:clock.update(start=time.perf_counter()),timeout=20)
    def worker(ident):
        client=Client(port)
        try:
            client.send(f'CONNECT\naccept-version:1.2\nhost:stomp.cs.bgu.ac.il\nlogin:bench_{ident}\npasscode:benchmark\n\n')
            if not client.receive().startswith('CONNECTED\n'): raise RuntimeError('Login failed')
            channel=f'bench/{ident}'
            client.send(f'SUBSCRIBE\ndestination:{channel}\nid:0\nreceipt:joined\n\n')
            if not client.receive().startswith('RECEIPT\n'): raise RuntimeError('Subscribe failed')
            def echo(seq):
                body=(str(seq)+':').ljust(size,'x')
                started=time.perf_counter_ns()
                client.send(f'SEND\ndestination:{channel}\n\n{body}')
                frame=client.receive()
                elapsed=(time.perf_counter_ns()-started)/1e6
                if not frame.startswith('MESSAGE\n') or frame.split('\n\n',1)[1]!=body:
                    raise RuntimeError('Message missing, duplicated or out of order')
                return elapsed
            for i in range(10): echo(-i-1)
            barrier.wait()
            samples=[echo(i) for i in range(messages)]
            return samples,time.perf_counter()
        except BaseException:
            barrier.abort()
            raise
        finally: client.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
        results=list(pool.map(worker,range(clients)))
    latency=[sample for samples,_ in results for sample in samples]
    elapsed=max(end for _,end in results)-clock['start']
    return {'clients':clients,'messages':len(latency),'payload_bytes':size,'elapsed_seconds':elapsed,
            'messages_per_second':len(latency)/elapsed,'p50_ms':statistics.median(latency),
            'p95_ms':percentile(latency,.95),'p99_ms':percentile(latency,.99),'errors':0}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients',type=int,nargs='+',default=[1,8,32])
    parser.add_argument('--messages',type=int,default=200)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--payload',type=int,default=256)
    parser.add_argument('--port',type=int,default=17777)
    parser.add_argument('--output',type=Path,default=ROOT/'benchmarks/results.json')
    args=parser.parse_args()
    if any(not 1<=n<=128 for n in args.clients) or not 1<=args.messages<=100000 or not 1<=args.repeats<=20 or not 32<=args.payload<=65536:
        parser.error('Use 1–128 clients, 1–100000 messages, 1–20 repeats and 32–65536 payload bytes.')
    if occupied(args.port) or occupied(7778):
        parser.error('Stop the dashboard/server first; benchmark and monitor ports must be free.')
    rows=[]
    classes=ROOT/'server/target/classes'
    if not classes.exists(): parser.error('Compile the Java server first.')
    java_version=subprocess.run(['java','-version'],capture_output=True,text=True,check=True).stderr.strip()
    try:
        for repeat in range(args.repeats):
            # Alternate order to reduce systematic first-mode bias.
            for mode in (['tpc','reactor'] if repeat%2==0 else ['reactor','tpc']):
                for count in args.clients:
                    with tempfile.TemporaryDirectory(prefix='stomp-benchmark-') as directory:
                        env=dict(os.environ,STOMP_BIND='127.0.0.1'); env.pop('STOMP_BRIDGE_SECRET',None)
                        with open(Path(directory)/'console.log','w') as log:
                            process=subprocess.Popen(['java','-Xms128m','-Xmx512m','-cp',str(classes),
                                'io.github.adamabutoamy.stomp.protocol.StompServer',str(args.port),mode],
                                cwd=directory,env=env,stdout=log,stderr=log)
                            try:
                                deadline=time.monotonic()+15
                                while not occupied(args.port):
                                    if process.poll() is not None or time.monotonic()>deadline: raise RuntimeError('Java startup failed')
                                    time.sleep(.05)
                                result=workload(args.port,count,args.messages,args.payload)
                                result.update(mode=mode,repeat=repeat+1)
                                rows.append(result)
                                print(f'{mode:7} {count:3} clients: {result["messages_per_second"]:8.1f} msg/s; p95 {result["p95_ms"]:.3f} ms',flush=True)
                            finally:
                                process.terminate()
                                try: process.wait(timeout=5)
                                except subprocess.TimeoutExpired: process.kill(); process.wait()
    finally:
        sources=hashlib.sha256()
        for path in sorted((ROOT/'server/src').rglob('*.java')):
            sources.update(str(path.relative_to(ROOT)).encode()); sources.update(path.read_bytes())
        data={'recorded_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'platform':platform.platform(),'logical_cpus':os.cpu_count(),'java':java_version,
              'java_source_sha256':sources.hexdigest(),'python':platform.python_version(),
              'method':'Closed-loop, one independent echo channel per client, 10 warmup messages/client; localhost; verified bodies; fresh JVM per run; startup excluded; Java logging enabled. Not a fanout, saturation, HTTP or database benchmark.',
              'complete':len(rows)==args.repeats*2*len(args.clients),'runs':rows}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(data,indent=2)+'\n')
        print('Results:',args.output)

if __name__=='__main__': main()
