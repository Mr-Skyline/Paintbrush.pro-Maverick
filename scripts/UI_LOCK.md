## UI Lock Policy

This repository uses a hash-based UI lock to prevent accidental UI changes.

Locked files include core UI surfaces:
- `src/components/**/*.tsx`
- `src/screens/**/*.tsx`
- `src/index.css`

## Commands

- Check lock (fails when UI changed):
  - `npm run ui:lock:check`

- Update lock intentionally after approved UI changes:
  - `npm run ui:lock:update`

## Build behavior

`npm run build` runs `npm run ui:lock:check` first.

If UI changes are intentional and approved, update the lock file with:
- `npm run ui:lock:update`

## Emergency override

To bypass lock check for a one-off run:
- `UI_LOCK_ALLOW=1 npm run build`

Use override only when explicitly approved.
