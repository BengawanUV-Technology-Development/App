# UAV Pipeline v0.3 — Qualification Status

Updated: 2026-08-12

| Batch | Software implementation | Qualification evidence |
| --- | --- | --- |
| 1 Contract/persistence/auth | Implemented | 47 unit tests, Python compile, and Vite build pass; hardware baseline remains external |
| 2 Canonical Jetson identity | Implemented | Synthetic durable epoch/sidecar tests pass; 10-minute Arducam capture remains required |
| 3 RTP-aware receiver | Implemented | Synthetic loss/reorder/duplicate/wrap and 150 ms exact-sync tests pass; target link recovery remains required |
| 4 Browser synchronized overlay | Implemented | Binary-envelope unit test and frontend build pass; browser/target visual test remains required |
| 5 Production detector | Implemented; gate pending | Baseline checkpoint provenance is verified. [File-replay evidence](docs/qualification/BATCH_5_FILE_REPLAY_2026-08-12.md) validates authenticated RTP/Ground flow and isolated live-overlay publishing while exposing persistent-event pressure; browser p95 latency and exact rendered identity still require qualification |
| 6 Reliability/observability | Implementation in progress; gate pending | Added bounded Ground decode-to-publish p50/p95 metrics; 60-minute hardware endurance, network-outage recovery, and full alert coverage remain required |
| 7 Command safety | Not started | SITL qualification required |
| 8 Post-flight workflow | Not started | Import/review tests required |
| 9 Reporting/final E2E | Not started | 60-minute final E2E required |

No hardware gate is considered passed merely because its code or synthetic test
passes. Test commands, checksums, logs, and acceptance reports must be attached
here when executed on the target equipment.
