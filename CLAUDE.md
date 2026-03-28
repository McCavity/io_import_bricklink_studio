# CLAUDE.md — Project Context for Claude Code

## Project Overview

This is a **Blender add-on** that imports BrickLink Studio `.io` files (ZIP archives
containing LDraw geometry) directly into Blender as 3D meshes with correct colors.

**Key files:**
- `blender_studio_import.py` — the single-file Blender add-on (install this in Blender)
- `update_colors.py` — standalone script to fetch the full BrickLink color table from Rebrickable API
- `bricklink_colors.json` — generated color table (not in repo; created by `update_colors.py`)

## Critical Domain Knowledge

### The BrickLink vs. LDraw Color ID Problem
`model2.ldr` inside `.io` files uses **BrickLink color IDs**, NOT LDraw color IDs.
The same number means a completely different color in each system:
- BrickLink 11 = Black | LDraw 11 = Trans-Bright Green
- BrickLink 19 = Trans-Yellow | LDraw 19 = (other)
- BrickLink 20 = Trans-Green | LDraw 20 = Dark Gray

**Always check bricklink.com/catalogColors.asp for the authoritative BrickLink color mapping,
NOT ldraw.org color references.**

### Coordinate System Conversion
LDraw is left-handed (Y-down), Blender is right-handed (Z-up).
The correct conversion (implemented in `ldraw_point_to_blender`):
```python
SCALE = 0.001
bx = -lx * SCALE   # X must be NEGATED to avoid mirroring
by =  lz * SCALE
bz = -ly * SCALE
```
Do NOT change this without understanding the handedness issue.

### Color Inheritance
In LDraw, color IDs `-1` and `16` mean "inherit color from parent".
This is handled by `_INHERIT = frozenset((-1, 16))`.

### Transparent Materials (Blender 5 / EEVEE Next)
Current settings for transparent materials (empirically tuned):
- `Transmission Weight = 1.0` — full glass effect
- `Roughness = 0.15` — matte plastic (not mirror-like)
- `Alpha = 0.65` — compromise: Cycles (less double-darkening) + EEVEE (needs < 1.0 for BLENDED)
- `surface_render_method = 'BLENDED'` — clean transparency, no dithering noise
- `IOR = 1.46` — ABS plastic refractive index

**Why Alpha = 0.65 and not 1.0:** EEVEE with BLENDED mode requires Alpha < 1.0 to
perform any blending. Alpha = 1.0 makes EEVEE render transparent parts as fully opaque.
Cycles handles Transmission correctly regardless of Alpha.

### Color Management
On import, `view_transform` is set to `'Standard'` (not AgX). AgX is Blender 5's default
but heavily desaturates high-chroma LEGO colors. Always preserve this behavior.

## Development Conventions

- The plugin is a **single `.py` file** (not a package). Keep it that way unless there's
  a strong reason to restructure.
- **Color table** lives in `LDRAW_COLORS` dict in the plugin AND optionally in
  `bricklink_colors.json`. The JSON overrides the built-in table when present.
- **Version** in `bl_info["version"]` is a tuple like `(0, 2, 17)`. Bump the patch
  version for any user-visible change.
- All **print statements** use the prefix `[StudioImport]` for easy console filtering.
- **Empirically verified** colors (tested on Galaxy Explorer 497) are marked `✓ verified empirically`
  in comments and protected in `EMPIRICAL_OVERRIDES` in `update_colors.py`.

## Testing

Test file: `497-Galaxy-Explorer.io` (LEGO Set 497/928, Galaxy Explorer, 1979)
NOT in the repository (too large) — obtain separately from BrickLink Studio.

Expected colors in the Galaxy Explorer:
| BL Color ID | Expected appearance |
|---|---|
| 1 | White (Minifig torso) |
| 3 | Yellow (Minifig heads) |
| 5 | Red (astronaut suit) |
| 6 | Green (computer panel tiles) |
| 7 | Blue (main hull) |
| 9 | Light Gray (frame, struts) |
| 11 | Black (stripes, tires, wrench) |
| -11 | Black rubber (tires) |
| 17 | Trans-Red (warning lights) |
| 19 | Trans-Yellow (cockpit windows) |
| 20 | Trans-Green (navigation lights) |

## Diagnostic Tool

`debug_material_report.py` — run in Blender's Scripting tab.
- If objects are selected: reports only those objects
- If nothing is selected: reports all `LDraw_*` objects in the scene
- Prints BL color ID, Base Color (RGBA + hex approximation), Alpha, Roughness,
  Transmission, IOR, surface_render_method, blend_method, use_backface_culling
- Used by community members to generate standardized bug reports for color issues

When reviewing a color issue, ask the reporter to run this script and paste the output.
The `BL Color ID` in the report maps directly to a key in `LDRAW_COLORS`.

## Known Issues / Future Work

- Vertex deduplication not implemented (affects mesh quality / normal smoothing)
- Smooth normals / BFC (Back-Face Culling from LDraw META) not yet respected
- Camera positioned from bounding box only — LXFML camera data not yet used
- `modelv2.ldr` (type-11 Studio custom parts) ignored
- Color table for post-2003 sets incomplete without `bricklink_colors.json`
