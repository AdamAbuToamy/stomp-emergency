# Local TPC / Reactor measurement

Closed-loop, one independent echo channel per client, 10 warmup messages/client; localhost; verified bodies; fresh JVM per run; startup excluded; Java logging enabled. Not a fanout, saturation, HTTP or database benchmark.

Command: `python3 scripts/benchmark_stomp.py --messages 100 --repeats 3`

18 completed runs; 3 per mode/client count. 100 measured messages per client, 256-byte bodies. Medians below summarize the three runs; full runs and environment are in results.json.

| Mode | Clients | Median messages/s | Median run p95 (ms) |
|---|---:|---:|---:|
| tpc | 1 | 3590.5 | 0.435 |
| tpc | 8 | 10025.0 | 2.076 |
| tpc | 32 | 9016.5 | 10.512 |
| reactor | 1 | 2089.7 | 0.633 |
| reactor | 8 | 7668.2 | 2.022 |
| reactor | 32 | 10238.9 | 8.325 |

These short runs on a shared execution environment are exploratory. They do not establish a universal winner. JVM warmup, scheduling, Python client threads and localhost influence results. Repeat longer runs on the intended host before making capacity claims.
