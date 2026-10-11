# TPC / Reactor measurements after transport hardening

Command: `python3 scripts/benchmark_stomp.py --messages 1000 --repeats 3`

Closed-loop, one independent echo channel per client, 10 warmup messages/client; localhost; verified bodies; fresh JVM per run; startup excluded; Java logging enabled. Not a fanout, saturation, HTTP or database benchmark.

18 runs, 3 per combination. 1,000 messages/client, 256-byte bodies. Values below are medians across runs.

| Mode | Clients | Messages/s | Run p95 ms | Sampled peak RSS MiB | Java CPU seconds |
|---|---:|---:|---:|---:|---:|
| tpc | 1 | 6360.920 | 0.305 | Unavailable | Unavailable |
| tpc | 8 | 16084.983 | 1.219 | Unavailable | Unavailable |
| tpc | 32 | 16254.449 | 4.951 | Unavailable | Unavailable |
| reactor | 1 | 4226.571 | 0.443 | 51.574 | 0.000 |
| reactor | 8 | 17437.575 | 0.990 | Unavailable | Unavailable |
| reactor | 32 | 17366.788 | 4.527 | Unavailable | Unavailable |

Resource counters were unavailable in this execution environment; null values are retained rather than estimated. Run on Linux with accessible /proc process files to collect them. CPU is process-wide CPU time, not utilization percent. Resource sampling includes connection setup and warmup; RSS sampling is every 20 ms. Message timings exclude setup/warmup.

These are local closed-loop measurements on a shared execution environment. They do not establish a universal winner or predict production capacity. No fanout saturation, HTTP/SQLite throughput, or end-to-end user experience is measured.

Raw runs, Java version, CPU count, timestamp and Java source fingerprint are in results.json. Earlier 100-message results remain in before-transport-hardening.json. Different workloads and shared-machine conditions prevent a controlled before/after performance claim.
