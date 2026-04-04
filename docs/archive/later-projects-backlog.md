# Later Projects Backlog

This document tracks assets intentionally left out of the current production path
so the repo stays focused while preserving training material.

## Kept for Battleship Training Branch

- `src/components/WallBattleshipLab.tsx`
- `src/components/WallBattleshipControlsWindow.tsx`
- `src/battleship/*`
- `docs/wall-battleship-reliability-report.md`

## Kept as Legacy OST Automation References

- `scripts/ost_orchestrator.py`
- `scripts/ost_training_lab.py`
- `scripts/ost_*` utilities
- `scripts/maverick_runtime.py`

## New Primary Production Path

- `takeoff_agent/*` (standalone CV service)
- `server/index.js` (`/api/takeoff/*`, `/api/sidekick/*`, `/api/schedule/*`)
- `src/components/TakeoffSidekickPanel.tsx`
- `src/screens/MobileSidekickScreen.tsx`

## Candidate Future Cleanup

- Move archived scripts into `scripts/archive/` after validating no active dependencies.
- Split CV service into dedicated repository once deployment traffic exceeds Railway free tier.
