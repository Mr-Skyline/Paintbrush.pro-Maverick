# Wall Battleship Reliability Report

Date: 2026-03-31

## Scope
- Dedicated controls window route via Electron `BrowserWindow` + React `appMode=battleship-controls`.
- Typed IPC control path (`wall:control`) with payload validation.
- Replay-to-controls state sync (`wall:state`) and action acknowledgements (`wall:status`).
- Legacy fallback channels removed (`postMessage`, `BroadcastChannel`, `localStorage`, opener bridge).

## Must-Pass Checklist
- [x] Controls window lifecycle is stable (open/focus/reopen handled in Electron main process).
- [x] Controls actions are routed only through typed IPC and validated at boundaries.
- [x] Controls UI shows action ACK lifecycle: `sent -> received -> executed|failed`.
- [x] Replay state and tournament results stream to controls window via IPC.
- [x] Build/typecheck passed: `npm run build`.

## Validation Notes
- Build validation completed successfully in this session.
- Multi-monitor move policy uses persisted monitor preference and applies to replay window.
- Detached controls command no longer rewrites HTML at runtime; no script redeclaration path remains.
- Arena/policy enforcement and tournament/export handlers remain in replay engine and are triggered through IPC commands.

## Result
- Stability refactor is implemented end-to-end.
- Legacy fallback channels have been removed after IPC-first migration.
