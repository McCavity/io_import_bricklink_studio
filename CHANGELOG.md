# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.2.17] - 2026-03-28

### Added
- External color table support: plugin auto-loads `bricklink_colors.json` from the
  add-on directory if present, overriding the built-in table
- `update_colors.py` now writes `bricklink_colors.json` (instead of patching the `.py` file)
- JSON includes version date, source info, and human-readable color names section

### Changed
- Decoupled color data from plugin logic — `blender_studio_import.py` is never modified
  by the color updater

---

## [0.2.16] - 2026-03-28

### Fixed
- Transparent material: `Roughness` reduced from `0.05` → `0.15` (eliminates metallic
  specular highlights on flat transparent surfaces like cockpit panels)
- `Alpha` set to `0.65` (compromise: less double-darkening in Cycles vs. 0.55;
  EEVEE requires Alpha < 1.0 for BLENDED mode to work without raytracing)

### Added
- `Specular IOR Level` set to `0.3` for transparent materials (less reflective surface)

---

## [0.2.15] - 2026-03-28

### Changed
- Transparent materials: `Alpha` set to `1.0` — relies purely on `Transmission = 1.0`
  for glass effect; eliminates double-darkening ("smoked glass" look) in Cycles
- **Note:** this caused EEVEE to render transparent parts as fully opaque
  (fixed in v0.2.16 by reverting Alpha to 0.65)

---

## [0.2.14] - 2026-03-28

### Changed
- Transparent materials: switched from `DITHERED` back to `BLENDED` surface render method
- `use_backface_culling = False` for transparent materials (glass visible from inside)
- `shadow_method` changed to `CLIP` for sharper shadows behind glass

---

## [0.2.13] - 2026-03-28

### Changed
- Complete rewrite of `LDRAW_COLORS` table based on **official BrickLink Color Guide v2**
  and Swooshable cross-reference — IDs 1–113 now fully correct
- Fixed systematic error: many IDs (8, 10, 12–16, 21–29, 36, 50–51) had wrong colors
  because they were based on LDraw IDs instead of BrickLink IDs

### Fixed
- BL 8: was Dark Blue → now **Brown** `#543324`
- BL 10: was Maersk Blue → now **Dark Gray** `#545955`
- BL 12–16: were opaque solid colors → now **transparent** (Trans-Clear, Trans-Black,
  Trans-Dark Blue, Trans-Light Blue, Trans-Neon Green)
- BL 21–29: completely wrong colors → now Chrome Gold, Chrome Silver, Dark Pink,
  Purple, Salmon, Light Salmon, Lime, Nougat, Earth Orange
- BL 36: was transparent lime green → now **Bright Green** (solid) `#58AB41`
- BL 50–51: were opaque grays → now **Trans-Dark Pink / Trans-Purple**

---

## [0.2.12] - 2026-03-28

### Fixed
- BL Color 19 = **Trans-Yellow** (was opaque Yellow) — empirically confirmed via
  cockpit windows in Galaxy Explorer 497
- BL Color 20 = **Trans-Green** (was Dark Gray) — empirically confirmed via
  navigation lights in Galaxy Explorer 497

---

## [0.2.11] - 2026-03-28

### Fixed
- BL Color 11 = **Black** (opaque) — was incorrectly set to Trans-Bright Green
  (LDraw Color 11 = Trans-Bright Green, but BrickLink Color 11 = Black)
- Root cause identified: `model2.ldr` inside `.io` files uses **BrickLink color IDs**,
  not LDraw color IDs — the same number has a completely different meaning in each system

---

## [0.2.10] - 2026-03-28

### Fixed
- Transparent geometry: switched to `DITHERED` surface render method to fix Z-sorting
  artifacts (transparent flat plates on opaque surfaces rendered as opaque gray)

---

## [0.2.9] - 2026-03-28

### Added
- Color management auto-set to `Standard` on import (fixes AgX tone-mapper
  desaturating high-chroma colors in Blender 5)
- Color `-11` (Rubber Black) added to color table — tires and cables now render black
- Object→Material linkage diagnostic output in console

### Fixed
- EEVEE raytracing attributes re-applied on every import (not guarded by `StudioSun` check)

---

## [0.2.8] - 2026-03-28

### Added
- Viewport auto-switches from SOLID to MATERIAL PREVIEW after import
- Version banner printed to Blender console at start of each import

---

## [0.2.7] - 2026-03-28

### Fixed
- BL Color 6 = **Green** (was incorrectly Dark Red) — empirically verified on
  computer panel tiles in Galaxy Explorer 497

---

## [0.2.6] - 2026-03-28

### Fixed
- BL Color 7 Blue: empirically corrected to `(0.000, 0.149, 0.651)` (Blender linear
  value differs from direct sRGB hex conversion)
- Trans-material diagnostic logging added (`_log_trans_materials()`)

---

## [0.2.5] - 2026-03-28

### Added
- All `LDraw_Color_*` materials purged at start of each import (prevents stale
  materials from previous imports persisting)
- numpy-based geometry cache: each `.dat` LDraw primitive processed only once,
  reused via matrix multiplication

---

## [0.2.0–0.2.4] - 2026-03-23 to 2026-03-28

### Added
- Initial working implementation
- LDraw ZIP parser, `FILE`/`NOFILE` section handling
- Recursive sub-reference traversal (type-1 lines) with color inheritance
- Triangle (type-3) and quad (type-4) geometry
- LDraw → Blender coordinate conversion (fixes left/right mirroring)
- Case-insensitive `.dat` file lookup
- `ndis` primitive exclusion (inner stud faces)
- `.dat copy` alias handling
- `StudioImportPreferences` with configurable LDraw library path
- Principled BSDF materials with full BrickLink color table
- `_setup_scene_lighting()` with EEVEE raytracing enable
- `_setup_camera()` from model bounding box
