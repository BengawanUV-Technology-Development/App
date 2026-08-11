# UAV v0.3 Delivery Gates

This checklist contains dynamic implementation work only. Contracts are frozen
in `../PROJECT_CONTEXT.md` and status/evidence belongs in
`../PROJECT_STATUS.md`.

- [x] Freeze schema v2.0, normalized XYXY, timestamps, statuses, and tokens.
- [x] Add durable SQLite catalog for missions, epochs, commands, detections,
  imports, and reports.
- [x] Reject unauthenticated state changes and Jetson ingest requests.
- [ ] Assign identity at Arducam capture and persist epoch manifests/sidecars.
- [ ] Preserve identity in RTP and prove loss/reorder/wrap behavior.
- [ ] Ship exact-frame WebSocket/canvas overlay with 150 ms metadata deadline.
- [ ] Verify baseline s-YOLOv11 checkpoint provenance and Jetson performance.
- [ ] Pass 60-minute reliability qualification and network/storage faults.
- [ ] Pass persistent idempotent command lifecycle in SITL.
- [ ] Pass checksum-verified import and five-frame reviewed propagation.
- [ ] Pass non-coordinate reporting failure isolation and final E2E.

No item that requires target hardware or SITL may be checked solely from a unit
test or code review.
