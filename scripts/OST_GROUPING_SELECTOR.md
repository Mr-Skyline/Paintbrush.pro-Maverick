# OST Grouping Selector

Finds and scores takeoff groupings on the current page, then optionally clicks the best one.

## Analyze only

```powershell
cd "C:\Users\travi\OneDrive\Documents\Paintbrush.pro"
python "scripts\ost_grouping_selector.py" --monitor-index 1
```

Writes:
- `output/ost-grouping-selector/latest.json`

## Analyze + click best overall

```powershell
python "scripts\ost_grouping_selector.py" --monitor-index 1 --click-best
```

## Analyze + click best for specific unit label

```powershell
python "scripts\ost_grouping_selector.py" --monitor-index 1 --unit-label "unit-b2" --click-best
```

## Unit label normalization

The selector reads alias mappings from:
- `scripts/ost_unit_aliases.json`

You can edit that file to map noisy OCR variants into canonical labels (for example `unit-b2`).

## Notes

- This is black-box detection from current screen pixels + OCR.
- It is robust for repeated unit layouts when sheet visibility is stable.
- Use with fixed monitor/sizing for highest reliability.
