# OST Training Program

This defines a dedicated training pipeline for the OST black-box agent using your
training database and completed historical projects.

## What was set up

- Program definition: `scripts/ost_training_program.json`
- Registry template for imported projects: `scripts/ost_training_registry.example.json`
- 10 initial training modules (L1-L3) with pass criteria and promotion gates.

## Recommended workflow with your 21 projects

1. Duplicate `scripts/ost_training_registry.example.json` to:
   - `scripts/ost_training_registry.json`
2. Add all 21 imported projects to that registry.
3. Tag each project with module targets (start with T01-T06).
4. Run Boost/takeoff agent episodes and save evidence to:
   - `output/ost-boost-agent/<timestamp>/`
5. Score each run against module criteria from `ost_training_program.json`.

## Suggested onboarding order

- First pass (all 21 projects):
  - T01, T02, T03, T06
- Second pass (subset with best data quality):
  - T04, T05, T07
- Third pass (complex/repeated plan sets):
  - T08, T09, T10

## Naming convention for future modules

- `T##-<skill>-L#`
- Example: `T11-boost-multi-page-L3`

This keeps the curriculum stable while your training database grows.
