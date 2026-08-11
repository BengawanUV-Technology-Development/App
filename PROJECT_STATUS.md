# UAV Pipeline v0.3 — Qualification Status

Updated: 2026-08-11

| Batch | Software implementation | Qualification evidence |
| --- | --- | --- |
| 1 Contract/persistence/auth | Implemented | 47 unit tests, Python compile, and Vite build pass; hardware baseline remains external |
| 2 Canonical Jetson identity | Implemented | Synthetic durable epoch/sidecar tests pass; 10-minute Arducam capture remains required |
| 3 RTP-aware receiver | Not started | Synthetic and link recovery tests required |
| 4 Browser synchronized overlay | Not started | Component/integration tests required |
| 5 Production detector | Not started | Checkpoint provenance and Jetson benchmark required |
| 6 Reliability/observability | Not started | 60-minute hardware endurance required |
| 7 Command safety | Not started | SITL qualification required |
| 8 Post-flight workflow | Not started | Import/review tests required |
| 9 Reporting/final E2E | Not started | 60-minute final E2E required |

No hardware gate is considered passed merely because its code or synthetic test
passes. Test commands, checksums, logs, and acceptance reports must be attached
here when executed on the target equipment.
