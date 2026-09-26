# STOMP Emergency Reporting System

## Development status

This university project is being extended with automated tests and
reliability improvements. The repository includes Python integration
tests, C++ event-parser tests, and tests that run the real C++ client.

Current work includes concurrency review, further client robustness
improvements, and code organization. Some tests may expose known issues
while fixes are in progress. This is an educational portfolio project,
not a production emergency service.

A university networking project with a Java messaging server and a
multithreaded C++ client. Users subscribe to channels, publish simulated
emergency reports, and generate local summaries.

Originally developed by Adam Abu Toamy and Ammar Mawassi for the
Systems Programming course at Ben-Gurion University. Adam implemented
most of the original project. This revision adds Python integration
tests, targeted bug fixes, and Linux build improvements.

This is an educational prototype, not an operational emergency system.

## Technologies

Java, C++, Python unittest, TCP sockets, Boost.Asio, Maven, Make.

The server supports:
- Thread-Per-Client (TPC)
- Reactor

## Setup

Tested locally on Ubuntu through WSL 2, using JDK 17.

```bash
sudo apt update
sudo apt install -y openjdk-17-jdk maven build-essential libboost-dev python3
```

Build both components from the repository root:

```bash
(cd server && mvn compile)
make -C client
```

## Run

In terminal 1, from the repository root:

```bash
java -cp server/target/classes bgu.spl.net.impl.stomp.StompServer 7777 tpc
```

Replace `tpc` with `reactor` to use the other server mode.

In terminal 2:

```bash
cd client
./bin/StompEMIClient
```

Enter these commands one at a time. Wait for the login and subscription
confirmations before sending the report:

```text
login 127.0.0.1:7777 demo_user demo123
join police
report ../examples/police-demo.json
```

Allow the report to arrive, then generate the summary:

```text
summary police demo_user /tmp/stomp-demo-summary.txt
```

Read it from another terminal:

```bash
cat /tmp/stomp-demo-summary.txt
```

For one submission of the example report, the expected counts are:
- Total: 1
- Active: 1
- Forces arrival at scene: 0

Use disposable demo credentials. The current client connects to
127.0.0.1:7777; configurable network endpoints need further work.
Summary timestamps use the local timezone.

## Python integration tests

With the Java server running on port 7777, run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The tests use real TCP connections and Python's standard library:

1. Connect, subscribe, and verify the subscription receipt.
2. Connect two clients and verify the delivered message's content,
   destination, and recipient-specific subscription ID.

Both tests passed locally against TPC and Reactor.
The C++ report-to-summary scenario was also checked manually against Reactor.

## Fixes in this revision

- Removed a duplicate frame terminator from server encoding.
- Built outgoing messages with each recipient's subscription ID.
- Replaced unsafe manual destruction of StompFrame's map with default destruction.
- Matched the client's STOMP host header to the server's expected value.
- Updated legacy Boost.Asio API names.
- Removed Windows-specific build paths and unnecessary Boost.System linking.
- Added automatic build-directory creation and header dependencies.

The delivery test initially failed because the receiver obtained the
sender's subscription ID. It passed after recipient-specific delivery
was implemented.

## Scope and remaining work

Two passing tests cover specific scenarios, not complete correctness.
Disconnect/reconnect behavior, malformed input, concurrency, and resource
cleanup require additional tests and fixes. Other client cleanup code
has not yet been repaired.

AddressSanitizer and UndefinedBehaviorSanitizer were used during
debugging; a complete sanitizer-verified test suite is not yet available.

No production-readiness or full STOMP 1.2 compliance is claimed.
