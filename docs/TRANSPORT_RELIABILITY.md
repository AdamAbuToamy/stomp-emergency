# Transport reliability: evidence and trade-offs

## Reproduced failure

The pre-change server accepted an oversized unterminated frame without a configured
limit. With the fault harness requesting a 64 KiB cap, `test_01` timed out waiting
for closure after sending more than 64 KiB. The configuration did not exist in that
version; this establishes a missing resource policy, not an observed production OOM.
After the change, the same test passes on both TPC and Reactor, and a separate
healthy client can still log in.

Code inspection also identified unbounded Reactor output buffering and blocking
TPC writes without a deadline. These were tested after the fixes using actual TCP
clients with constrained socket buffers. No before/after throughput claim is made
from these fault tests, and corruption of old TPC frames was not demonstrated.

## Implemented policies

| Resource | Default | Behavior at limit |
|---|---:|---|
| Incoming frame bytes, excluding NUL terminator | 256 KiB | Close offending connection and clean session |
| Reactor queued output bytes remaining | 4 MiB per connection | Disconnect slow consumer; log SLOW_CONSUMER |
| TPC write deadline | 2 seconds per serialized write | Watchdog closes socket; log WRITE_TIMEOUT |
| Reactor pending input high-water mark | 128 KiB per connection | Pause OP_READ until actor drains input |
| Reactor write budget | 256 KiB per selector dispatch | Yield to other ready connections |
| Retained direct input buffers | 64 × 8 KiB | Extra released buffers are not retained in pool |

The output cap bounds Java user-space queued bytes, not kernel socket buffers or
all process memory. Input buffering can overshoot the high-water mark by a read
buffer. This is per-connection protection, not a global connection/memory quota.

JVM options: `-Dstomp.maxFrameBytes=...`, `-Dstomp.maxQueuedBytes=...`,
`-Dstomp.writeTimeoutMillis=...`. `-Dstomp.sendBufferBytes=...` exists to make
backpressure tests reproducible; leaving it unset preserves OS defaults.

## Why these designs

TPC keeps blocking writes rather than adding a dedicated writer per connection
and changing its comparison with Reactor. Java socket read timeouts do not provide
write deadlines, so one shared daemon scheduler closes a stalled socket. Timers
are cancelled and removed after writes. Direct replies and broadcasts share an
explicit write lock.

A sender can still wait for a slow recipient up to the deadline, and multiple slow
recipients can add delays. This is bounded blocking, not perfect latency isolation.

Reactor tracks remaining bytes under its write lock and rejects queue growth above
the cap. Cleanup runs on the recipient's actor, avoiding a sender acquiring another
connection's protocol monitor. Input-read interest resumes after queued work drains.
Slow consumers are disconnected rather than silently dropping individual reports.

## Reproduce

Stop other test servers first. Build, then run:

    mvn -f server/pom.xml compile
    python3 scripts/test_resilience.py

The harness starts isolated JVMs on 127.0.0.1:17779, with monitoring on 7778.
It uses temporary logs and no dashboard account data. Its stricter thresholds
(64 KiB frames, 128 KiB output queue, 300 ms write deadline) are test settings.

1. Oversized unterminated input: offender closes, healthy login succeeds.
2. Stopped reader: 180 × roughly 8 KiB messages while a healthy subscriber drains;
   verify correct bodies and a protective log event, then verify a fresh login.
3. Concurrent broadcasts and direct receipts: verify 80 ordered messages plus
   30 intact subscription receipts on one connection.

After the changes, 37 original tests, 16 authenticated/storage tests and 3 fault
scenarios passed on each server mode: 112 test executions. The CI workflow now
includes the fault scenarios; local success does not claim a remote CI run.

## Remaining limits

No global connection limit, slow-drip input deadline, protocol heartbeat policy,
process-wide memory budget, sustained fanout saturation study or complete sanitizer
analysis is claimed. Full STOMP 1.2 compliance is not claimed. Test assertions prove
specific scenarios, not the absence of all races or denial-of-service behavior.

## Interview explanation

Start with the academic C++ client / Java TPC and Reactor server and credit the
original authors. Describe the subsequent dashboard, persistent workflow and
reliability work separately. Explain the reproduced missing frame limit, why a
read timeout does not solve stalled writes, the two backpressure policies, and how
the tests distinguish a healthy system from one merely absorbing data in buffers.
Show an actual failing test and its passing result, not only a feature list.
