# STOMP Emergency Reporting System

A Java messaging server and a multithreaded C++ client for publishing simulated
emergency reports over TCP. Clients subscribe to channels, exchange reports,
and generate local summaries.

Originally developed by Adam Abu Toamy and Ammar Mawassi for the Systems
Programming course at Ben-Gurion University. Adam implemented most of the
original project and is extending it with automated tests, reliability fixes,
and Linux build improvements.

## Architecture

- **Java server:** STOMP message parsing, login, subscriptions and message routing.
- **TPC mode:** a dedicated thread handles each connection.
- **Reactor mode:** a selector handles socket readiness with worker threads for processing.
- **C++ client:** keyboard commands, socket reception, JSON reports and local summaries.
- **Python tests:** real TCP clients and subprocess tests of the actual C++ executable.

The server routes messages; the C++ client interprets event data and generates summaries.

## Build

Developed and tested locally on Ubuntu through WSL 2 with JDK 17.
The current shutdown implementation targets Linux/WSL.

```bash
sudo apt update
sudo apt install -y openjdk-17-jdk maven build-essential libboost-dev python3
mvn -f server/pom.xml compile
make -C client
```

## Run the example

From the repository root, start the server in one terminal:

```bash
java -cp server/target/classes io.github.adamabutoamy.stomp.protocol.StompServer 7777 tpc
```

Use `reactor` instead of `tpc` to run the other mode. Run only one server on
port 7777 at a time.

In another terminal:

```bash
cd client
./bin/StompEMIClient
```

Enter these commands one at a time, waiting for the login and channel-join confirmations:

```text
login 127.0.0.1:7777 demo_user demo123
join police
report ../examples/police-demo.json
```

After the event arrives:

```text
summary police demo_user /tmp/stomp-demo-summary.txt
```

Read the output in another terminal:

```bash
cat /tmp/stomp-demo-summary.txt
```

A single submission of the example should produce Total: 1, active: 1,
and forces arrival at scene: 0. Summary times use the local timezone.
Use disposable demo credentials.

## Tests

### Automated build and test

Run `python3 scripts/test_all.py` from the repository root.
Stop any existing server on port 7777 first.

The script builds Java and C++, runs three C++ parser checks, then
runs the Python suite against fresh TPC and Reactor servers.
It stops its servers afterwards and prints the server-log location.

GitHub Actions runs the same script on Ubuntu with Java 17 for
pushes and pull requests, and saves available server logs.

[View test runs](https://github.com/AdamAbuToamy/stomp-emergency/actions)

### Python integration and client tests

Build both components first and keep the Java server running on port 7777.
From the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The repository contains **37 Python test methods**, covering:

- Login, incorrect passwords, duplicate login and repeated CONNECT.
- Subscription authorization, recipient-specific IDs and channel isolation.
- Unsubscribe, resubscribe, disconnect and reconnect behavior.
- TCP input split across writes, multiple frames in one write and larger UTF-8 bodies.
- Real C++ client shutdown, incomplete commands and report file errors.
- Report-to-summary behavior and routing metadata separated from report content.
- Concurrent login attempts for the same username.
- Simultaneous subscriptions to the same channel.
- Requested client ports and invalid endpoint handling.
- Summary snapshots while reports arrive.
- Receipt handling and login again after logout.

The concurrent-login test repeats its scenario 25 times. A passing run alone
does not prove the absence of race conditions.

Repeat the tests with each server mode. These tests use the local development
server; they are not intended for a production deployment.

### C++ event-parser tests

These three checks do not require a running server:

```bash
event_test_dir=$(mktemp -d)
g++ -std=c++11 -Wall -Wextra -Iclient/include \
  tests/cpp/test_event_parser.cpp client/src/event.cpp \
  -o "$event_test_dir/test_event_parser" && \
  "$event_test_dir/test_event_parser"
```

### Memory diagnostics

Build an isolated ASan/UBSan client without replacing the regular executable:

```bash
sanitizer_dir=$(mktemp -d)
cp -r client/src client/include client/makefile "$sanitizer_dir/"
make -C "$sanitizer_dir" -B \
  CFLAGS="-c -Wall -g -O1 -std=c++11 -Iinclude -pthread -fsanitize=address,undefined -fno-omit-frame-pointer" \
  LDFLAGS="-pthread -fsanitize=address,undefined"
```

With the server running, test report generation and cleanup:

```bash
STOMP_CLIENT_BIN="$sanitizer_dir/bin/StompEMIClient" \
ASAN_OPTIONS="detect_leaks=1:halt_on_error=1" \
UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1" \
python3 -m unittest discover -s tests -p 'test_client_report_summary.py' -v
```

These tools check executed paths and do not establish thread safety.

## Reliability improvements

- Removed duplicate server frame terminators.
- Delivered messages using each recipient's subscription ID.
- Rejected commands requiring authentication before login, duplicate subscription IDs,
  and repeated CONNECT on an authenticated connection.
- Added cleanup after normal disconnect and transport closure.
- Changed Reactor handling to flush final replies before closing and stop failed write loops.
- Replaced unsafe manual C++ member destruction with default destruction.
- Added EOF shutdown before and after login.
- Validated command argument counts and recovered from report file errors.
- Preserved colons in event values and separated descriptions from general fields.
- Used parsed message metadata directly for channel routing.
- Added a shared authentication lock after a test exposed two successful concurrent logins.

## Verification status and remaining work

The automated runner passed locally on Ubuntu/WSL: three C++ parser
checks and 37 Python tests against each of TPC and Reactor.
The GitHub Actions workflow also completed successfully.

Recent improvements include concurrent channel creation fixes,
configurable numeric IPv4 endpoints with port validation, protected
summary snapshots and receipt tracking, and coordinated client
session cleanup supporting login again after logout.

Selected client shutdown and report-to-summary scenarios previously
passed with ASan/UBSan. A complete sanitizer run of the current suite
is not claimed.

Passing tests cover specific scenarios and do not prove the absence
of race conditions or complete protocol correctness.

Remaining work includes shared-state concurrency review, malformed
input handling, resource limits, logging and code organization.
Hostname resolution and IPv6 support are not claimed.

This is an educational portfolio project. It is not an operational emergency
system, and full STOMP 1.2 compliance is not claimed. The bundled `json.hpp`
is the third-party nlohmann/json library; its license notice is retained.
