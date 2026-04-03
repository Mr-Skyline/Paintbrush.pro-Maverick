# OST UI Atlas

This atlas lets the agent use stable UI anchors + logic, instead of brittle one-off pixel clicks.

## Files

- `scripts/ost_ui_atlas.json` - anchor map + thresholds
- `scripts/ost_ui_mapper.py` - helper to capture/update anchors

## Capture/update anchors

```powershell
cd "C:\Users\travi\OneDrive\Documents\Paintbrush.pro"
python "scripts\ost_ui_mapper.py" capture --atlas "scripts\ost_ui_atlas.json"
```

Capture order:
1. `boost_button`
2. `boost_run_button`
3. `boost_close_button`

## Full mapping (Boost + Project Setup)

Use this when preparing end-to-end intake -> OST setup automation:

```powershell
cd "C:\Users\travi\OneDrive\Documents\Paintbrush.pro"
python "scripts\ost_ui_mapper.py" capture-full --atlas "scripts\ost_ui_atlas.json" --setup-config "scripts\ost_project_setup_agent.config.json"
```

This captures all required points in one run.

Boost points:
1. `boost_button`
2. `boost_run_button`
3. `boost_close_button`

Project setup points:
4. `training_playground_first_project` (a project row under Training Playground)
5. `file_menu`
6. `new_project_menu_item`
7. `project_name_input`
8. `project_path_input`
9. `project_pdf_input`
10. `project_ok_button`

## View atlas

```powershell
python "scripts\ost_ui_mapper.py" show --atlas "scripts\ost_ui_atlas.json"
```

## How Boost agent uses this

When `use_ui_atlas` is true in `scripts/ost_boost_agent.config.json`,
the Boost agent uses atlas anchors as source-of-truth.

This allows easier remapping after UI shifts without editing automation logic.
