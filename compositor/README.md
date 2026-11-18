# Compositor Skill

An [agent skill](https://agentskills.io) for creating, inspecting, and editing
[Compositor](https://github.com/robbietilton/Compositor) `.comp` projects — the
native layered format of the macOS image editor — by writing files directly
instead of driving the UI.

## Why

A `.comp` project is just a folder: `manifest.json` plus PNG layer assets.
Compositor reloads the open canvas within ~0.3 s whenever the package changes,
so any agent that can write files can edit artwork: add layers and masks, set
blend modes and transforms, place adjustment layers — no automation APIs, no
screenshot-driven clicking. What you get are ordinary, fully editable layers.

## Install

With the [`skills`](https://github.com/vercel-labs/skills) CLI (Node.js ≥ 22.20):

```bash
npx skills add youbuwei/skills
```

Or manually: clone or copy this folder into your agent's skills directory,
e.g. `~/.claude/skills/compositor` for Claude Code.

## Use

Ask your agent anything about a `.comp` project, for example:

- "Inspect ~/Desktop/poster.comp and list every layer with its blend mode."
- "Add a soft white vignette on top of ~/Desktop/poster.comp."
- "Create ~/Desktop/demo.comp — a 1920×1080 moody night scene, one or two
  layers at a time so I can watch it build."

The skill enforces a careful workflow — inspect → plan → write assets →
update the manifest atomically → validate → report. It backs up before the
first edit, preserves unknown fields and existing IDs, never invents schema,
and asks before destructive actions.

## What's inside

| Path | Purpose |
| --- | --- |
| `SKILL.md` | The workflow, safety rules, and trigger description |
| `scripts/validate_comp.py` | Structural validator: manifest keys, duplicate ids, image/mask assets, PNG headers, upstream naming rules |
| `scripts/comp_png.py` | Zero-dependency PNG asset generator (`solid`, `gradient`, `ellipse`, `rect`, `dots`, `mask`) and preview compositor |
| `scripts/fetch_format_docs.py` | Auto-refreshing cache of the upstream format docs |
| `references/project-format.md` | Format invariants and the adaptive-knowledge procedure |
| `references/safe-editing.md` | Pre-flight and post-edit checklist |
| `references/upstream/` | Cached upstream docs + `metadata.json` (records the covered format version) |

## Self-adapting format knowledge

The `.comp` format evolves (upstream is at version 21 today). Instead of
hard-coding a feature list that rots, the skill:

1. reads the project's manifest `version`,
2. runs `fetch_format_docs.py --auto` before edits — a no-op when the cached
   docs are fresh, a fetch when they are missing, older than the project,
   fetched from a different pinned tag, or older than 7 days. Fetches are
   pinned to a fixed upstream release tag (never the moving `main` branch),
   so the cached bytes are reproducible; moving the pin is an explicit
   `--pin latest --yes`,
3. validates against the authoritative cached snapshot, and
4. falls back to the bundled invariants note when offline, and says so.

`validate_comp.py` additionally warns whenever a project declares a version
newer than the docs cache covers.

## Requirements

- Any Python 3 — all three scripts run on the standard library alone; Pillow,
  when present, only adds deeper PNG corruption checks.
- Network access is optional; it is used only to refresh the doc cache.
- The [Compositor](https://github.com/robbietilton/Compositor) macOS app to
  view the results — the skill itself only reads and writes files.

## Scripts

```bash
# structural check of a project (stdlib only)
python3 scripts/validate_comp.py path/to/Project.comp

# generate a layer asset — no Pillow, no throwaway scripts (stdlib only)
python3 scripts/comp_png.py gradient --size 1920x1080 --dir v \
    --from "#10143A" --to "#7A3E8C" --out path/to/Project.comp/images/<id>.png
python3 scripts/comp_png.py mask --size 300x300 --from 255 --to 60 --dir h \
    --out path/to/Project.comp/images/<id>.mask.png

# composite a project to a preview PNG for visual verification
python3 scripts/comp_png.py preview path/to/Project.comp --out preview.png

# refresh the upstream doc cache when needed
python3 scripts/fetch_format_docs.py --auto
```

## Acknowledgements

Format knowledge comes from the upstream documentation:
[writing-comp-files.md](https://github.com/robbietilton/Compositor/blob/main/docs/writing-comp-files.md)
and [project-format.md](https://github.com/robbietilton/Compositor/blob/main/docs/project-format.md).
