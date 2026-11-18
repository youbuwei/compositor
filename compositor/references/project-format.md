# Compositor `.comp` format — invariants and adaptive notes

This note deliberately avoids a version-by-version feature list: the format
evolves, and hand-copied lists rot the day upstream ships a new version.
The skill stays current by **fetching upstream docs on demand** and by
**learning from the project's own manifest**. Use this file for the
invariants and the procedure; look everything else up.

## How to stay current (the adaptive procedure)

1. Read the project's manifest `version`.
2. Check `references/upstream/metadata.json` for the highest format version
   the cached docs cover, and the pinned upstream tag they came from.
3. Run `python3 scripts/fetch_format_docs.py --auto --for-version <version>`
   as automatic housekeeping (any Python 3, standard library only): it
   no-ops when the cache is fresh and refreshes it when missing, older than
   the project, fetched from a different pin, or older than 7 days. The
   fetch is pinned to a fixed upstream release tag — never the moving
   `main` branch — so the cached bytes are reproducible; moving the pin to
   a newer tag is an explicit, user-approved action (`--pin latest --yes`).
   Then read `references/upstream/project-format.md` — the format
   reference for that pinned version.
   `validate_comp.py` also warns when a project is newer than the cache.
4. Offline? Use this note plus whatever the cache holds, and tell the user
   the format knowledge may be stale.
5. For the exact shape of any structure not spelled out here, copy from the
   project's own manifest — the app is the schema generator. Upstream's own
   advice: add the thing in Compositor, save, and copy it from the manifest.

## Invariants (slow-changing rules)

- A `.comp` project is a directory: `manifest.json` plus `images/` holding
  files named after their layer id (`<id>.png`, `<id>.mask.png`; GIF sources
  `<id>.gif`). Compositor silently refuses mismatched names.
- `layers` runs bottom-to-top; the last layer draws on top.
- `transform` is in document pixels, `rotation` in degrees clockwise,
  `opacity` 0–1, `sampling` is `High quality`, `Smooth` or `Nearest`.
- Layer images are RGBA PNGs (16-bit PNG from v12, EXR from v13); masks are
  8-bit grayscale PNGs, white shows and black hides.
- Preserve `documentID`, existing layer ids, and all unknown fields.
- Write new/changed assets first, then replace `manifest.json` atomically
  (temp file in the package + rename).
- After writing: delete the `QuickLook` folder if present (stale Finder
  preview; Compositor rewrites it on next save) and remove assets the
  manifest no longer references.
- Canvases go up to 30,000 pixels on a side.
- Newer features are version-gated: a manifest declaring an older `version`
  must not contain them. Check the version before adding anything exotic.

## Quick orientation

- Manifest keys: `format` (`com.compositor.project`), `version`, `colorSpace`,
  `documentID`, `width`, `height`, `resolution` (optional, pixels/inch,
  defaults to 72), `activeLayerID`, `layers`.
- Layer record: `id`, `name`, `imageFile`, `isVisible`, `isGroup`, `opacity`,
  `blendMode`, `transform` — plus version-gated extensions named in the
  cached upstream docs (`maskFile`/`maskEnabled`, `maskSourceID`, `parentID`
  groups, `adjustment`, `text` metadata, `shape` styles, `gif`, …).
- Adjustment layers carry an `adjustment` object and no `imageFile`, affect
  everything composited below them, and every kind carries identity
  `levels`/`curves` blocks.

## Upstream documentation

- https://github.com/robbietilton/Compositor/blob/main/docs/writing-comp-files.md
- https://github.com/robbietilton/Compositor/blob/main/docs/project-format.md
