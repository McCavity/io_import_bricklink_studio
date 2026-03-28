# io_import_bricklink_studio

A Blender add-on that imports **BrickLink Studio `.io` files** directly as 3D meshes with correct colors and materials — no intermediate tools like LDraw Viewer or Mecabricks required.

![Blender Version](https://img.shields.io/badge/Blender-3.0%2B-orange)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-GPL%20v3-green)
![Version](https://img.shields.io/badge/Version-0.2.17-informational)

---

## Features

- **Direct `.io` import** — reads the ZIP archive and parses `model2.ldr` internally
- **Full LDraw geometry** — type 1 (sub-references), type 3 (triangles), type 4 (quads)
- **Recursive sub-assembly** with correct color inheritance (`-1` / `16` = inherit from parent)
- **BrickLink color system** — 60+ colors built-in, 230+ via `update_colors.py`
- **Correct coordinate conversion** — no left/right mirroring (LDraw left-handed → Blender right-handed)
- **Transparent materials** — Principled BSDF with Transmission + BLENDED mode for clean glass look
- **Automatic viewport setup** — switches to Material Preview, sets color management to Standard
- **Performance** — numpy-based geometry cache: each `.dat` primitive processed only once
- **Requires LDraw parts library** for complete geometry (missing parts are skipped with a warning)

## Requirements

| Requirement | Version |
|---|---|
| Blender | 3.0 or newer (tested with 5.0) |
| LDraw Parts Library | [latest-parts](https://www.ldraw.org/parts/latest-parts.html) |
| numpy | bundled with Blender |

> **Renderer notes:**
> - **Cycles** — best results for transparent parts; glass effect renders correctly
> - **EEVEE Next** — enable *Render Properties → Raytracing* for correct transparency

## Installation

1. Download `blender_studio_import.py`
2. Open Blender → **Edit → Preferences → Add-ons → Install**
3. Select `blender_studio_import.py` → **Install Add-on**
4. Enable the add-on (tick the checkbox)
5. In the add-on preferences, set the path to your **LDraw parts library**

## Usage

**File → Import → BrickLink Studio (.io)**

Select your `.io` file and click **Import**. The model appears in the current collection with one mesh object per BrickLink color.

## Updating the Color Table (optional)

The built-in color table covers ~60 BrickLink colors (IDs 1–113). For the **complete ~230-color table** (including modern colors like Medium Azure, Lavender, Coral, etc.):

### Step 1 — Get a free Rebrickable API key

1. Register at [rebrickable.com](https://rebrickable.com/users/create/)
2. Go to **Settings → API** and copy your key

### Step 2 — Run the updater

```bash
# Auto-detect Blender installation:
python3 update_colors.py --key YOUR_KEY

# Explicit Blender path (macOS example):
python3 update_colors.py --key YOUR_KEY --blender /Applications/Blender.app

# Preview without writing:
python3 update_colors.py --key YOUR_KEY --dry-run
```

The script writes `bricklink_colors.json` next to the installed plugin. Blender loads it automatically on the next add-on reload.

### Step 3 — Reload in Blender

**Edit → Preferences → Add-ons → BrickLink Studio (.io) Importer**
→ Disable → Re-enable (or press F3 → *Reload Scripts*)

The Blender console will show:
```
[StudioImport] Color table loaded: bricklink_colors.json v2026-03-28 — 231 colors
```

## File Structure

```
io_import_bricklink_studio/
├── blender_studio_import.py   # The add-on (single-file, install this in Blender)
├── update_colors.py           # Standalone color table updater (run from terminal)
├── bricklink_colors.json      # Generated color table (not in repo, create via updater)
└── README.md
```

## Known Limitations

| Issue | Status |
|---|---|
| External `.dat` files require LDraw library | Parts not found are skipped with a console warning |
| Recursion depth capped at 50 | Protects against infinite loops in malformed files |
| BrickLink Studio custom parts (`modelv2.ldr` type-11 lines) | Not supported |
| Smooth normals / BFC (Back-Face Culling) | Not yet implemented |
| Vertex deduplication | Not yet implemented (affects mesh quality) |

## Tested Models

| Set | Name | Result |
|---|---|---|
| 497 / 928 | Galaxy Explorer (1979) | ✅ All colors correct |

## Background — BrickLink vs. LDraw Color IDs

BrickLink Studio uses **BrickLink color IDs** in `model2.ldr`, which are completely different from LDraw color IDs — the same number means a different color in each system:

| BrickLink ID | BrickLink Color | LDraw Color |
|---|---|---|
| 11 | Black | Trans-Bright Green |
| 19 | Trans-Yellow | (undefined) |
| 20 | Trans-Green | Dark Gray |

This is the root cause of incorrect colors when using LDraw-based color tables with `.io` files.

## Contributing

Issues and pull requests welcome! If you have empirically verified a color on a specific LEGO set, please open an issue with the BrickLink color ID and your Blender linear RGB values — especially for post-2003 colors.

## License

This project is licensed under the **GNU General Public License v3.0** — see [LICENSE](LICENSE) for details.

GPL v3 is required for compatibility with Blender's own license.
