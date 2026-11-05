# Isolated Ktor HTTP verification fixture

This fixture exercises a separate, loopback-only Ktor process. The memo demo
continues using local storage. API results do not establish Android, iOS, Web,
demo integration, or persistence across server restarts.

Versions reuse the repository's existing actual Ktor trial configuration:
Ktor 3.2.3/CIO, Kotlin 2.2.10, JVM 17. The Gradle 8.14.3 wrapper is copied from
the memo demo, retaining its distribution SHA-256 pin.

From the harness repository root:

```sh
rtk proxy python3 -B -m harness.verification_runner --definition tools/fixtures/ktor-memo/verification.json --root . --timeout 900 --output verification/ktor-memo/receipt.json
```

The approved test builds `installDist`, starts the actual server on a fresh
loopback port, waits for health readiness, POSTs a unique title/body, and performs
a separate GET using the returned id. It checks HTTP 201/200 and exact id/title/body.
Every run writes raw request/response bodies and status codes, PID, submitted
commit, validation input hashes, built-file hashes, build/server logs, and JUnit
under `verification/ktor-memo/`. Server storage is process memory; this API
scenario intentionally does not claim restart persistence.

`harness.test_server_verification` verifies the real completion entrypoint with
synthetic policy authority and disposable test keys. It checks required server
evidence independently of client evidence. Those signatures test gate behavior;
they are not administrator-issued product certification or a running protected
verification service.
