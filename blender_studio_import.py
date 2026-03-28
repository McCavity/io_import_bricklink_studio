"""
BrickLink Studio (.io) Importer for Blender
============================================
Version 0.2.17 – Load color table from external JSON file (bricklink_colors.json)

Performance strategy:
  Each LDraw file (stud.dat, 4-4cyli.dat, ...) is traversed exactly ONCE
  and the result is cached as a numpy array. Further references only need
  a single matrix multiplication on the array.
"""

bl_info = {
    "name": "BrickLink Studio (.io) Importer",
    "author": "Studio Import Plugin",
    "version": (0, 2, 17),
    "blender": (3, 0, 0),
    "location": "File > Import > BrickLink Studio (.io)",
    "description": "Imports BrickLink Studio .io files as 3D models",
    "warning": "Requires LDraw library for complete rendering",
    "category": "Import-Export",
}

import bpy
import bmesh
import os
import time
import zipfile
import numpy as np
import mathutils
from collections import defaultdict
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty
from bpy.types import Operator, AddonPreferences

# Scale factor: 1 LDU = 1 mm = 0.001 m in Blender
SCALE = 0.001

# LDraw color IDs that mean "inherit color from parent"
_INHERIT = frozenset((-1, 16))

# BrickLink color table: color_id → (R, G, B, A)
#
# IMPORTANT: BrickLink Studio (.io) uses BrickLink color IDs in model2.ldr,
# NOT the standard LDraw IDs! The numbering schemes are completely different:
#   BrickLink  8 = Brown       ↔  LDraw  8 = Dark Red
#   BrickLink 10 = Dark Gray   ↔  LDraw 10 = (unused)
#   BrickLink 12 = Trans-Clear ↔  LDraw 12 = (unused)
#   etc.
#
# Source: BrickLink Color Guide v2 (v2.bricklink.com/catalog/color-guide)
#         + Swooshable LEGO Color Chart (swooshable.com/parts/colors)
#         + empirical verification on Galaxy Explorer 497
#
# RGB values: derived directly from BrickLink hex (passed as linear value).
# Color 7 (Blue) is corrected empirically, because Blender renders the linear value
# differently than the sRGB hex value would suggest.
#
# Alpha < 1.0 → transparent material (Principled BSDF with Transmission)
#
LDRAW_COLORS = {
    # ── Special negative IDs (BrickLink Studio special materials) ────────
    -11: (0.020, 0.020, 0.020, 1.0),  # Rubber Black (tires, cables)

    # ── Fallback for unknown IDs ────────────────────────────────────────
    0:   (0.067, 0.067, 0.067, 1.0),  # Black (fallback / unknown)

    # ── Opaque colors — BrickLink IDs 1–60 ─────────────────────────────
    1:   (0.957, 0.957, 0.957, 1.0),  # White           #F4F4F4  ✓ verified empirically
    2:   (0.690, 0.627, 0.435, 1.0),  # Tan             #B0A06F
    3:   (0.969, 0.820, 0.090, 1.0),  # Yellow          #FAC80A  ✓ verified empirically (Minifig heads)
    4:   (0.839, 0.475, 0.137, 1.0),  # Orange          #D67923
    5:   (0.788, 0.102, 0.035, 1.0),  # Red             #B40000  ✓ verified empirically (Astronaut)
    6:   (0.058, 0.369, 0.059, 1.0),  # Green           #00852B  ✓ verified empirically (computer panels)
    # BL 7 = Blue. Hex #1E5AA8 → sRGB (0.118, 0.353, 0.659).
    # Corrected empirically on Galaxy Explorer: Blender renders linear value
    # differently than sRGB → use empirical value (0.000, 0.149, 0.651).
    7:   (0.000, 0.149, 0.651, 1.0),  # Blue            #1E5AA8  ✓ verified empirically (hull)
    8:   (0.329, 0.196, 0.141, 1.0),  # Brown           #543324
    9:   (0.541, 0.573, 0.553, 1.0),  # Light Gray      #8A928D  ✓ verified empirically (frame)
    10:  (0.329, 0.349, 0.333, 1.0),  # Dark Gray       #545955
    11:  (0.067, 0.067, 0.067, 1.0),  # Black           #1B2A34  ✓ verified empirically (stripes, tires)
    21:  (0.875, 0.757, 0.463, 1.0),  # Chrome Gold     #DFC176
    22:  (0.808, 0.808, 0.808, 1.0),  # Chrome Silver   #CECECE
    23:  (0.816, 0.314, 0.596, 1.0),  # Dark Pink       #D05098
    24:  (0.404, 0.122, 0.631, 1.0),  # Purple          #671FA1
    25:  (0.941, 0.427, 0.380, 1.0),  # Salmon          #F06D61
    26:  (0.976, 0.718, 0.647, 1.0),  # Light Salmon    #F9B7A5
    27:  (0.647, 0.792, 0.094, 1.0),  # Lime            #A5CA18
    28:  (0.733, 0.502, 0.353, 1.0),  # Nougat          #BB805A  (Minifig hands/face)
    29:  (0.847, 0.427, 0.173, 1.0),  # Earth Orange    #D86D2C
    31:  (0.961, 0.525, 0.141, 1.0),  # Medium Orange   #F58624
    32:  (0.973, 0.604, 0.224, 1.0),  # Light Orange    #F89A39
    33:  (1.000, 0.839, 0.498, 1.0),  # Light Yellow    #FFD67F
    34:  (0.647, 0.792, 0.094, 1.0),  # Lime (alt.)     #A5CA18
    35:  (0.871, 0.918, 0.573, 1.0),  # Light Lime      #DEEA92
    36:  (0.345, 0.671, 0.255, 1.0),  # Bright Green    #58AB41  (OPAQUE! not transparent)
    37:  (0.498, 0.769, 0.459, 1.0),  # Medium Green    #7FC475
    38:  (0.678, 0.851, 0.659, 1.0),  # Light Green     #ADD9A8
    39:  (0.024, 0.616, 0.624, 1.0),  # Dark Turquoise  #069D9F
    40:  (0.000, 0.667, 0.643, 1.0),  # Light Turquoise #00AAA4
    41:  (0.612, 0.839, 0.800, 1.0),  # Aqua            #9CD6CC
    42:  (0.451, 0.588, 0.784, 1.0),  # Medium Blue     #7396C8
    43:  (0.686, 0.745, 0.839, 1.0),  # Violet          #AFBED6
    44:  (0.686, 0.745, 0.839, 1.0),  # Light Violet    #AFBED6
    46:  (0.898, 0.875, 0.827, 1.0),  # Glow In Dark Opaque  #E5DFD3
    48:  (0.439, 0.557, 0.486, 1.0),  # Sand Green      #708E7C
    49:  (0.737, 0.706, 0.647, 1.0),  # Very Light Gray #BCB4A5
    54:  (0.459, 0.396, 0.490, 1.0),  # Sand Purple     #75657D
    55:  (0.439, 0.506, 0.604, 1.0),  # Sand Blue       #70819A
    56:  (0.945, 0.471, 0.502, 1.0),  # Light Pink      #F17880
    58:  (0.533, 0.376, 0.369, 1.0),  # Sand Red        #88605E
    59:  (0.447, 0.000, 0.071, 1.0),  # Dark Red        #720012
    60:  (0.914, 0.914, 0.914, 0.70), # Milky White     #E9E9E9  (slightly milky)

    # ── Opaque colors — BrickLink IDs > 60 (modern colors, post-2003) ──────
    # IDs for post-2004 "Bluish" gray tones (Light/Dark Bluish Gray)
    61:  (0.639, 0.635, 0.643, 1.0),  # Light Bluish Gray   ≈ #A3A2A4
    62:  (0.424, 0.431, 0.408, 1.0),  # Dark Bluish Gray    ≈ #6C6E68
    # Minifig colors
    84:  (0.733, 0.502, 0.353, 1.0),  # Medium Nougat   #BB805A  (Minifig skin/hands)
    85:  (0.200, 0.133, 0.067, 1.0),  # Dark Brown      (hair, accessories)
    86:  (0.639, 0.635, 0.647, 1.0),  # Light Bluish Gray (alt. ID, common post-2004)
    # Metallics
    77:  (0.710, 0.584, 0.251, 1.0),  # Metallic Gold
    78:  (0.761, 0.761, 0.761, 1.0),  # Metallic Silver
    # Stickers/decals print accents (old Space sets)
    65:  (0.969, 0.820, 0.090, 1.0),  # Yellow (print accent)
    66:  (0.894, 0.894, 0.894, 1.0),  # Light Gray (print accent)

    # ── Transparent colors — BrickLink IDs 12–113 ─────────────────────────
    # Source: BrickLink Color Guide v2 — all IDs 12–20 are TRANSPARENT!
    12:  (0.933, 0.933, 0.933, 0.30), # Trans-Clear          #EEEEEE
    13:  (0.000, 0.078, 0.078, 0.50), # Trans-Black          #001414
    14:  (0.467, 0.718, 0.800, 0.55), # Trans-Dark Blue      #77B7CC
    15:  (0.678, 0.867, 0.929, 0.55), # Trans-Light Blue     #ADDDED
    16:  (0.980, 0.945, 0.357, 0.55), # Trans-Neon Green     #FAF15B
    17:  (0.722, 0.153, 0.000, 0.55), # Trans-Red            #B82700  ✓ verified empirically
    18:  (0.816, 0.427, 0.310, 0.55), # Trans-Neon Orange    #D06D4F
    19:  (0.980, 0.945, 0.365, 0.55), # Trans-Yellow         #FAF15D  ✓ verified empirically (cockpit windows)
    20:  (0.451, 0.706, 0.392, 0.55), # Trans-Green          #73B464  ✓ verified empirically (navigation lights)
    47:  (1.000, 1.000, 0.741, 0.55), # Trans-Clear (yellowish) #FFFFBD
    50:  (0.992, 0.557, 0.812, 0.55), # Trans-Dark Pink      #FD8ECF
    51:  (0.612, 0.584, 0.780, 0.55), # Trans-Purple         #9C95C7
    74:  (0.816, 0.898, 1.000, 0.55), # Trans-Medium Blue    #D0E5FF
    98:  (0.882, 0.553, 0.039, 0.55), # Trans-Orange         #E18D0A
    108: (0.686, 0.824, 0.275, 0.55), # Trans-Bright Green   #AFD246
    113: (0.675, 0.831, 0.871, 0.55), # Trans-Aqua           #ACD4DE
}
_DEFAULT_COLOR = (0.72, 0.74, 0.71, 1.0)  # Fallback: light gray

# ---------------------------------------------------------------------------
# Load external color table (bricklink_colors.json)
# ---------------------------------------------------------------------------
# The plugin searches at startup for a JSON file in the same directory
# as the plugin file itself (i.e. in the Blender add-ons folder).
# If found, it overrides the built-in table above.
#
# The JSON is generated and updated by update_colors.py.
# As long as no JSON exists, the plugin runs with the built-in table.
#
# JSON format: {"11": [0.067, 0.067, 0.067, 1.0], "19": [...], ...}
# (Keys are strings because JSON has no integer keys)
#
import json as _json
import os   as _os

def _load_external_colors():
    """
    Searches next to the plugin file for 'bricklink_colors.json' and returns
    the loaded dict {int → tuple}, or None if not found.
    """
    try:
        plugin_dir  = _os.path.dirname(_os.path.abspath(__file__))
        colors_file = _os.path.join(plugin_dir, "bricklink_colors.json")
        if not _os.path.exists(colors_file):
            return None
        with open(colors_file, "r", encoding="utf-8") as f:
            raw = _json.load(f)
        loaded = {int(k): tuple(v) for k, v in raw["colors"].items()}
        version = raw.get("version", "?")
        count   = len(loaded)
        print(f"[StudioImport] Color table loaded: bricklink_colors.json "
              f"v{version} — {count} colors")
        return loaded
    except Exception as e:
        print(f"[StudioImport] Warning: bricklink_colors.json could not be loaded: {e}")
        return None

_external = _load_external_colors()
if _external is not None:
    LDRAW_COLORS = _external   # external table overrides built-in
    print(f"[StudioImport] Built-in color table replaced by bricklink_colors.json")
else:
    print(f"[StudioImport] Built-in color table active "
          f"({len(LDRAW_COLORS)} colors, no bricklink_colors.json found)")


def get_color(color_id):
    return LDRAW_COLORS.get(color_id, _DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# LDR Parser (unchanged)
# ---------------------------------------------------------------------------

def parse_ldr_into_files(content):
    """
    Parses LDR content with embedded FILE sections.
    Returns a dict {name_lowercase: [lines]}.
    """
    files = {}
    current_name = None
    current_lines = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        tokens = line.split(None, 2)
        if len(tokens) >= 3 and tokens[0] == '0' and tokens[1] == 'FILE':
            if current_name is not None:
                files[current_name.lower()] = current_lines
            current_name = tokens[2].strip()
            current_lines = []
        elif len(tokens) >= 2 and tokens[0] == '0' and tokens[1] == 'NOFILE':
            if current_name is not None:
                files[current_name.lower()] = current_lines
            current_name = None
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None and current_lines:
        files[current_name.lower()] = current_lines

    return files


# ---------------------------------------------------------------------------
# File resolution with caching
# ---------------------------------------------------------------------------

def _resolve_file(name, internal_files, ldraw_path, file_cache, dir_cache):
    """
    Searches for a file in this order:
      1. Result cache
      2. Embedded FILE sections (case-insensitive)
      3. LDraw library (directory index is built once)

    Normalizes backslashes (LDraw spec allows \\ on Windows):
      "48\\1-4cyli.dat"  →  search in  ldraw/p/48/1-4cyli.dat
      "parts\\s\\stud4.dat"  →  ldraw/parts/s/stud4.dat
    """
    # Build canonical key: backslashes → '/', lowercase, trimmed
    name_key = name.strip().replace('\\', '/').lower()

    if name_key in file_cache:
        return file_cache[name_key]

    result = None

    if 'ndis' in name_key:
        pass  # inner stud surfaces → always skip

    elif name_key in internal_files:
        result = internal_files[name_key]

    elif ' copy' in name_key:
        base = name_key.split(' copy')[0].strip()
        result = internal_files.get(base)

    elif ldraw_path:
        # OS-native separator for filesystem access
        name_os   = name_key.replace('/', os.sep)
        base_name = name_key.rsplit('/', 1)[-1]   # filename only, without subdir

        # Build candidate paths (in priority order)
        candidates = []

        # 1) Does the name have a subdir prefix (e.g. "48/1-4cyli.dat")?
        if '/' in name_key:
            for base_lib in ('p', 'parts', ''):
                if base_lib:
                    candidates.append(os.path.join(ldraw_path, base_lib, name_os))
                else:
                    candidates.append(os.path.join(ldraw_path, name_os))

        # 2) Standard library subdirectories (filename only, no subdir)
        std_subdirs = (
            'parts',
            'p',
            os.path.join('p', '48'),
            os.path.join('p', '8'),
            os.path.join('parts', 's'),
            'models',
        )
        for subdir in std_subdirs:
            candidates.append(os.path.join(ldraw_path, subdir, name_os))

        # Direct file tests (case-sensitive, fastest)
        for candidate in candidates:
            if os.path.isfile(candidate):
                try:
                    with open(candidate, 'r', encoding='utf-8', errors='replace') as fh:
                        result = fh.read().splitlines()
                    break
                except OSError:
                    pass

        # Case-insensitive fallback via directory index
        if result is None:
            for subdir in std_subdirs:
                dir_path = os.path.join(ldraw_path, subdir)

                if dir_path not in dir_cache:
                    dir_cache[dir_path] = {}
                    if os.path.isdir(dir_path):
                        try:
                            dir_cache[dir_path] = {
                                fn.lower(): fn for fn in os.listdir(dir_path)
                            }
                        except OSError:
                            pass

                fn = dir_cache[dir_path].get(base_name)
                if fn:
                    fpath = os.path.join(dir_path, fn)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                            result = fh.read().splitlines()
                        break
                    except OSError:
                        pass

    file_cache[name_key] = result
    return result


# ---------------------------------------------------------------------------
# Geometry cache: local LDraw coordinates, numpy-based
# ---------------------------------------------------------------------------

_EMPTY = (np.zeros((0, 3), dtype=np.float64), np.zeros(0, dtype=np.int32))


def _build_local_geom(name, internal_files, ldraw_path,
                      file_cache, dir_cache, geom_cache,
                      missing_files, depth=0):
    """
    Computes and caches the geometry of `name` in local LDraw coordinates.

    Returns: (verts, tri_colors)
      verts:      np.array (3*N, 3) — every 3 consecutive rows = 1 triangle
      tri_colors: np.array (N,)     — color ID per triangle (-1 = inherit from parent)

    Core optimization: stud.dat (1,193x), 4-4cyli.dat (hundreds of times) etc. are
    traversed exactly ONCE; every further reference costs only one numpy matmul.
    """
    key = name.strip().replace('\\', '/').lower()

    if key in geom_cache:
        return geom_cache[key]

    if depth > 60 or 'ndis' in key:
        geom_cache[key] = _EMPTY
        return _EMPTY

    geom_cache[key] = _EMPTY  # sentinel against cycles

    lines = _resolve_file(name, internal_files, ldraw_path, file_cache, dir_cache)
    if lines is None:
        missing_files.add(name.strip())
        return _EMPTY

    verts_blocks = []
    color_blocks = []

    for line in lines:
        parts = line.split()
        if not parts:
            continue
        ltype = parts[0]

        # --- Type 1: sub-reference ---
        if ltype == '1' and len(parts) >= 15:
            try:
                ref_color = int(parts[1])
                nums = [float(p) for p in parts[2:14]]
                subfile = ' '.join(parts[14:])
            except (ValueError, IndexError):
                continue

            sub_v, sub_c = _build_local_geom(
                subfile, internal_files, ldraw_path,
                file_cache, dir_cache, geom_cache, missing_files, depth + 1,
            )
            if len(sub_v) == 0:
                continue

            # Build local 4×4 transformation matrix
            M = np.array([
                [nums[3], nums[4],  nums[5],  nums[0]],
                [nums[6], nums[7],  nums[8],  nums[1]],
                [nums[9], nums[10], nums[11], nums[2]],
                [0.,      0.,       0.,       1.     ],
            ], dtype=np.float64)

            # Batch-transform all vertices (one matmul instead of N individual ones)
            N = len(sub_v)
            h = np.empty((N, 4), dtype=np.float64)
            h[:, :3] = sub_v
            h[:, 3] = 1.0
            transformed = (M @ h.T).T[:, :3]

            # Color resolution: -1 in sub → insert ref_color (if not inherit)
            if ref_color not in _INHERIT:
                resolved_c = np.where(sub_c == -1, ref_color, sub_c)
            else:
                resolved_c = sub_c  # -1 stays -1 (propagate further up)

            verts_blocks.append(transformed)
            color_blocks.append(resolved_c)

        # --- Type 3: triangle ---
        elif ltype == '3' and len(parts) >= 11:
            try:
                color = int(parts[1])
                if color in _INHERIT:
                    color = -1
                nums = [float(p) for p in parts[2:11]]
            except (ValueError, IndexError):
                continue
            verts_blocks.append(np.array(nums, dtype=np.float64).reshape(3, 3))
            color_blocks.append(np.array([color], dtype=np.int32))

        # --- Type 4: quad → 2 triangles ---
        elif ltype == '4' and len(parts) >= 14:
            try:
                color = int(parts[1])
                if color in _INHERIT:
                    color = -1
                v = np.array([float(p) for p in parts[2:14]], dtype=np.float64).reshape(4, 3)
            except (ValueError, IndexError):
                continue
            verts_blocks.append(np.vstack([v[[0, 1, 2]], v[[0, 2, 3]]]))
            color_blocks.append(np.array([color, color], dtype=np.int32))

        # Types 0 (META), 2 (edges), 5 (optional edges) → ignore

    if verts_blocks:
        result = (np.vstack(verts_blocks), np.concatenate(color_blocks))
    else:
        result = _EMPTY

    geom_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# Create Blender objects
# ---------------------------------------------------------------------------

# One-time diagnostic output per Blender session (shows available BSDF inputs)
_BSDF_INPUTS_REPORTED = False


def _report_bsdf_inputs_once():
    """
    Prints all available Principled BSDF input names once.
    Also tests two colors (opaque + transparent) directly,
    so you can immediately see in the terminal output whether Alpha/Transmission
    are set correctly.
    """
    global _BSDF_INPUTS_REPORTED
    if _BSDF_INPUTS_REPORTED:
        return
    _BSDF_INPUTS_REPORTED = True
    try:
        tmp = bpy.data.materials.new("__ldraw_probe__")
        tmp.use_nodes = True
        bsdf = next((n for n in tmp.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            names = [inp.name for inp in bsdf.inputs]
            print(f"[StudioImport] Blender {bpy.app.version_string} – "
                  f"BSDF_PRINCIPLED Inputs: {names}")
            # Quick check: which of the critical inputs actually exist?
            critical = ["Base Color", "Alpha", "Roughness",
                        "Transmission Weight", "Transmission",
                        "Specular IOR Level", "Specular", "IOR"]
            found    = [n for n in critical if n in bsdf.inputs]
            missing  = [n for n in critical if n not in bsdf.inputs]
            print(f"[StudioImport] Inputs OK: {found}")
            if missing:
                print(f"[StudioImport] Inputs NOT found: {missing}")
        else:
            print("[StudioImport] WARNING: No BSDF_PRINCIPLED node found!")
        bpy.data.materials.remove(tmp)

        # surface_render_method check: which enum values are valid?
        probe2 = bpy.data.materials.new("__ldraw_probe2__")
        if hasattr(probe2, 'surface_render_method'):
            orig = probe2.surface_render_method
            valid_vals = []
            for v in ('BLENDED', 'DITHERED', 'HASHED', 'CLIP', 'OPAQUE'):
                try:
                    probe2.surface_render_method = v
                    valid_vals.append(v)
                except (TypeError, AttributeError):
                    pass
            probe2.surface_render_method = orig  # restore
            print(f"[StudioImport] surface_render_method valid values: {valid_vals}")
        else:
            print("[StudioImport] surface_render_method: not available (Blender < 4.2)")
        bpy.data.materials.remove(probe2)
    except Exception as e:
        print(f"[StudioImport] Diagnostic failed: {e}")


def _log_trans_materials():
    """
    Prints the relevant BSDF values for all Trans materials to the console after import,
    so you can immediately see whether Alpha/Transmission are correct.
    Only printed when at least one Trans material exists.
    """
    trans_mats = [
        m for m in bpy.data.materials
        if m.name.startswith("LDraw_Color_") and m.use_nodes
        and get_color(int(m.name.split("_")[-1]))[3] < 1.0
    ]
    if not trans_mats:
        return
    print("[StudioImport] ── Trans materials diagnostic ──────────────────────────")
    for mat in sorted(trans_mats, key=lambda m: m.name):
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not bsdf:
            print(f"  {mat.name}: NO BSDF NODE!")
            continue
        alpha_val = bsdf.inputs["Alpha"].default_value if "Alpha" in bsdf.inputs else "N/A"
        trans_val = None
        for tname in ("Transmission Weight", "Transmission", "Glass"):
            if tname in bsdf.inputs:
                trans_val = f"{tname}={bsdf.inputs[tname].default_value:.3f}"
                break
        srm = getattr(mat, 'surface_render_method', 'N/A')
        print(f"  {mat.name}: Alpha={alpha_val}, {trans_val}, surface_render_method={srm}")
    print("[StudioImport] ─────────────────────────────────────────────────────────")


def _set_bsdf_input(bsdf, possible_names, value, fallback_index=None):
    """
    Sets a Principled BSDF input robustly: tries all possible names
    (input names change between Blender versions), falls back to index.
    Returns True if successful.
    """
    for name in possible_names:
        if name in bsdf.inputs:
            try:
                bsdf.inputs[name].default_value = value
                return True
            except (TypeError, AttributeError, KeyError):
                pass
    if fallback_index is not None:
        try:
            if fallback_index < len(bsdf.inputs):
                bsdf.inputs[fallback_index].default_value = value
                return True
        except (TypeError, AttributeError, KeyError):
            pass
    return False


def _get_or_create_material(color_id):
    """
    Creates a realistic LEGO material for a BrickLink color ID.

    Opaque parts:   Principled BSDF with slight gloss (LEGO ABS plastic)
    Trans parts:    Principled BSDF with Transmission + Alpha (glass effect)

    Robust input search:
      All Principled BSDF input names are tried with multiple aliases
      (Blender 3/4/5 names inputs differently) and fall back to positional index.
    """
    mat_name = f"LDraw_Color_{color_id}"
    old = bpy.data.materials.get(mat_name)
    if old is not None:
        bpy.data.materials.remove(old)

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    r, g, b, a = get_color(color_id)
    is_trans = a < 1.0

    # Version-independent node search via node.type
    bsdf = None
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            bsdf = node
            break

    if not bsdf:
        print(f"[StudioImport] WARNING: No BSDF_PRINCIPLED node for color {color_id}")
        return mat

    # ── Base color (index 0 in all known Blender versions) ────────
    _set_bsdf_input(bsdf, ["Base Color", "Color", "Diffuse Color"], (r, g, b, 1.0),
                    fallback_index=0)

    if is_trans:
        # ── Transparent LEGO plastic (cockpit windows, position lights, ...) ──────
        #
        # LEGO transparent parts are colored ABS plastic/polystyrene, similar to
        # glass but slightly more matte. Goal: real glass effect instead of "particle cloud".
        #
        # Strategy for Blender 5 EEVEE Next + Cycles:
        #
        # LEGO transparent parts = colored ABS plastic (not optical glass!).
        # Slightly matte surface, no metallic look.
        #
        # Parameter choices:
        #   Roughness = 0.15  → matte plastic (0.05 looks like polished metal,
        #                        gives hard mirror reflections on flat surfaces)
        #   IOR = 1.46        → refractive index of ABS plastic
        #   Transmission = 1.0 → full glass effect; color comes from Base Color
        #   Alpha = 0.65      → compromise:
        #                        - Cycles: less double-darkening than 0.55
        #                        - EEVEE without raytracing: BLENDED needs Alpha < 1.0
        #                          (Alpha=1.0 makes EEVEE completely opaque without raytracing)
        #   Specular = 0.3    → less glossy surface (LEGO ≠ optical glass)
        #
        _set_bsdf_input(bsdf, ["Roughness"],                        0.15)
        _set_bsdf_input(bsdf, ["IOR", "Index of Refraction"],       1.46)
        _set_bsdf_input(bsdf,
            ["Transmission Weight", "Transmission", "Glass", "Transmission Amount"],
            1.0)
        _set_bsdf_input(bsdf, ["Alpha", "Opacity", "Transparency"], 0.65)
        _set_bsdf_input(bsdf,
            ["Specular IOR Level", "Specular", "Reflectivity"],     0.3)

        # Render mode: BLENDED for real alpha blending (no dither noise)
        if hasattr(mat, 'blend_method'):
            try:   mat.blend_method = 'BLEND'
            except (TypeError, AttributeError):
                try: mat.blend_method = 'HASHED'
                except (TypeError, AttributeError): pass
        if hasattr(mat, 'shadow_method'):
            try:   mat.shadow_method = 'CLIP'
            except (TypeError, AttributeError): pass
        if hasattr(mat, 'surface_render_method'):
            try:   mat.surface_render_method = 'BLENDED'
            except (TypeError, AttributeError): pass
        # Disable backface culling → glass visible from inside
        mat.use_backface_culling = False

    else:
        # ── Opaque LEGO ABS plastic: slightly glossy ─────────────────────
        _set_bsdf_input(bsdf, ["Roughness"],                                    0.25)
        _set_bsdf_input(bsdf, ["Specular IOR Level", "Specular", "Reflectivity"], 0.5)

    return mat


def _setup_scene_lighting():
    """
    Sets up studio-like lighting (sun + fill light + bright background).
    Removes Blender's default light ("Light") and sets up studio lights only once.

    Raytracing is ALWAYS enabled (even on re-import), as it is required
    for glass transparency.
    """
    scene = bpy.context.scene

    # EEVEE Next (Blender 4.2+ / 5.x): enable raytracing.
    # Set BEFORE the StudioSun guard so re-import also works.
    if hasattr(scene, 'eevee'):
        eevee = scene.eevee
        # Diagnostic: print all raytracing attributes (once on first import)
        rt_all = sorted(a for a in dir(eevee) if not a.startswith('_') and
                        any(kw in a.lower() for kw in ('ray', 'shadow', 'gi', 'ao')))
        if rt_all:
            print(f"[StudioImport] EEVEE RT/Shadow-Attrs: {rt_all}")
        for rt_attr in ('use_raytracing', 'use_raytracing_refraction',
                        'use_shadows', 'use_global_illumination'):
            if hasattr(eevee, rt_attr):
                try:
                    setattr(eevee, rt_attr, True)
                    print(f"[StudioImport] EEVEE {rt_attr} = True ✓")
                except (TypeError, AttributeError) as e:
                    print(f"[StudioImport] EEVEE {rt_attr}: could not set: {e}")

    # Already set up by an earlier import → don't duplicate lights
    if "StudioSun" in bpy.data.objects:
        return

    # Remove Blender's default light (always named "Light" in new scenes)
    default_light = bpy.data.objects.get("Light")
    if default_light is not None:
        bpy.data.objects.remove(default_light, do_unlink=True)

    # World background: bright neutral gray (replaces black default background)
    if scene.world and scene.world.use_nodes:
        bg = scene.world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = (0.72, 0.72, 0.72, 1.0)
            bg.inputs["Strength"].default_value = 0.5  # reduced → less overexposure

    # Main sun light (from top-front-left)
    sun_data = bpy.data.lights.new("StudioSun", 'SUN')
    sun_data.energy = 2.0  # reduced from 3.0 → less overexposure
    sun_data.angle = 0.0523  # ~3° → sharp shadows
    sun_obj = bpy.data.objects.new("StudioSun", sun_data)
    sun_obj.rotation_euler = (0.698, 0.175, 0.349)  # ~40° elevation, slightly to the side
    scene.collection.objects.link(sun_obj)

    # Fill light (from opposite side, softer)
    fill_data = bpy.data.lights.new("StudioFill", 'SUN')
    fill_data.energy = 1.0
    fill_obj = bpy.data.objects.new("StudioFill", fill_data)
    fill_obj.rotation_euler = (0.524, 3.316, 3.491)  # from bottom-back-right
    scene.collection.objects.link(fill_obj)


def _setup_camera(collection):
    """
    Replaces Blender's default camera ("Camera") with an automatically
    positioned studio camera that frames the imported model.
    """
    # Already set up by an earlier import → do nothing
    if "StudioCamera" in bpy.data.objects:
        return

    # Remove Blender's default camera
    default_cam = bpy.data.objects.get("Camera")
    if default_cam is not None:
        bpy.data.objects.remove(default_cam, do_unlink=True)

    # Compute bounding box of all mesh objects in the collection
    mins = [+1e9, +1e9, +1e9]
    maxs = [-1e9, -1e9, -1e9]
    has_geom = False
    for obj in collection.all_objects:
        if obj.type != 'MESH':
            continue
        has_geom = True
        for corner in obj.bound_box:
            pt = obj.matrix_world @ mathutils.Vector(corner)
            for axis in range(3):
                mins[axis] = min(mins[axis], pt[axis])
                maxs[axis] = max(maxs[axis], pt[axis])

    if not has_geom:
        return

    center = mathutils.Vector([(mins[i] + maxs[i]) / 2.0 for i in range(3)])
    size   = max(maxs[i] - mins[i] for i in range(3))
    dist   = size * 1.6  # camera distance = 160% of the largest dimension

    # Isometric studio perspective: front-right-top
    cam_offset = mathutils.Vector([dist * 0.60, -dist * 0.90, dist * 0.65])
    cam_loc    = center + cam_offset

    cam_data = bpy.data.cameras.new("StudioCamera")
    cam_data.lens = 50.0  # 50 mm equivalent

    cam_obj = bpy.data.objects.new("StudioCamera", cam_data)
    cam_obj.location = cam_loc

    # Point camera at model center
    direction = center - cam_loc
    rot_quat  = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot_quat.to_euler()

    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj


def _create_mesh_object(name, verts_np, collection):
    """
    Creates a Blender mesh object from a (3*N, 3) numpy array.
    Uses foreach_set for maximum performance with large meshes.

    Normal correction:
      LDraw primitives sometimes have reversed winding order (CW vs CCW).
      Without correction some faces point inward → bright speckling
      from inverted lighting. bmesh.ops.recalc_face_normals()
      orients all normals consistently outward.
    """
    n_verts = len(verts_np)
    n_tris = n_verts // 3

    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(n_verts)
    mesh.vertices.foreach_set("co", verts_np.ravel())

    mesh.loops.add(n_verts)
    mesh.loops.foreach_set("vertex_index", np.arange(n_verts, dtype=np.int32))

    loop_starts = np.arange(0, n_verts, 3, dtype=np.int32)
    loop_totals = np.full(n_tris, 3, dtype=np.int32)

    mesh.polygons.add(n_tris)
    mesh.polygons.foreach_set("loop_start", loop_starts)
    mesh.polygons.foreach_set("loop_total", loop_totals)

    mesh.update(calc_edges=True)

    # Orient normals consistently outward (eliminates bright speckling
    # from incorrectly wound LDraw primitive faces)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()

    # Enable smooth shading for all polygons
    mesh.polygons.foreach_set("use_smooth", np.ones(n_tris, dtype=bool))
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# Viewport helper function
# ---------------------------------------------------------------------------

def _switch_viewport_to_material():
    """
    Switches all 3D viewports from SOLID to MATERIAL PREVIEW.
    Background: In SOLID mode Blender shows random object colors
    instead of materials — Trans parts look opaque, colors are wrong.
    Viewports already on MATERIAL or RENDERED are NOT changed
    (no downgrade from Rendered mode).
    """
    switched = 0
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        if space.shading.type == 'SOLID':
                            space.shading.type = 'MATERIAL'
                            switched += 1
                        break
    except Exception as e:
        print(f"[StudioImport] Viewport switch failed: {e}")
    if switched:
        print(f"[StudioImport] {switched} viewport(s) → MATERIAL PREVIEW switched")


# ---------------------------------------------------------------------------
# Color management setup
# ---------------------------------------------------------------------------

def _setup_color_management():
    """
    Sets Blender's Color Management to 'Standard' (linear sRGB, no tone mapping).

    Why this matters:
      Blender 5 uses the 'AgX' tone mapper by default. AgX is designed for
      photorealistic scenes and intentionally desaturates highly chromatic colors.
      For LEGO visualizations this is wrong:

        Trans-Bright Green (0.62, 0.89, 0.18)  AgX→  light gray-green  (looks gray+opaque)
        Yellow             (0.97, 0.82, 0.09)  AgX→  slightly muted
        Blue               (0.00, 0.15, 0.65)  AgX→  darker, slightly shifted

      With 'Standard' the values in the color table correspond 1:1 to the
      sRGB output values → LEGO colors look correct.

    Set on every import so the value is correct even after File→New.
    The previous value is printed to the console.
    """
    try:
        cs = bpy.context.scene.view_settings
        old = getattr(cs, 'view_transform', '(unknown)')
        if old != 'Standard':
            cs.view_transform = 'Standard'
            print(f"[StudioImport] Color Management: '{old}' → 'Standard' "
                  f"(AgX/Filmic desaturates LEGO colors; Standard = correct display)")
        else:
            print(f"[StudioImport] Color Management: 'Standard' already active ✓")
    except Exception as e:
        print(f"[StudioImport] Color Management could not be set: {e}")


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def import_studio_file(filepath, ldraw_path=""):
    t0 = time.time()

    # Version banner (so you immediately see which version is running on plugin reload)
    _ver = '.'.join(str(v) for v in bl_info['version'])
    print(f"[StudioImport] ══ v{_ver} ══ Import: {os.path.basename(filepath)}")

    # 1) Read model2.ldr from ZIP
    try:
        with zipfile.ZipFile(filepath, 'r') as z:
            if 'model2.ldr' not in z.namelist():
                return False, "model2.ldr not found in .io archive"
            content = z.read('model2.ldr').decode('utf-8-sig', errors='replace')
    except zipfile.BadZipFile:
        return False, f"Not a valid ZIP archive: {filepath}"
    except Exception as e:
        return False, f"Error reading file: {e}"

    # 2) Parse FILE sections
    internal_files = parse_ldr_into_files(content)
    if not internal_files:
        return False, "No FILE sections found in model2.ldr"

    root_name = next(iter(internal_files))
    print(f"[StudioImport] Root: '{root_name}' | {len(internal_files)} internal files")

    # 3) Collect geometry (numpy + cache)
    file_cache  = {}
    dir_cache   = {}
    geom_cache  = {}
    missing_files = set()

    root_lines  = internal_files.get(root_name, [])
    type1_lines = [
        l for l in root_lines
        if l.split() and l.split()[0] == '1' and len(l.split()) >= 15
    ]
    n_top = len(type1_lines)

    # Progress bar in Blender's header
    wm = bpy.context.window_manager
    try:
        wm.progress_begin(0, n_top + 1)
    except Exception:
        wm = None

    verts_by_color = defaultdict(list)
    t_geom = time.time()

    for idx, line in enumerate(type1_lines):
        if wm:
            wm.progress_update(idx)

        parts = line.split()
        try:
            top_color = int(parts[1])
            nums = [float(p) for p in parts[2:14]]
            subfile = ' '.join(parts[14:])
        except (ValueError, IndexError):
            continue

        print(f"[StudioImport] [{idx+1}/{n_top}] {subfile}", flush=True)

        sub_v, sub_c = _build_local_geom(
            subfile, internal_files, ldraw_path,
            file_cache, dir_cache, geom_cache, missing_files,
        )
        if len(sub_v) == 0:
            continue

        # World transformation (batch)
        W = np.array([
            [nums[3], nums[4],  nums[5],  nums[0]],
            [nums[6], nums[7],  nums[8],  nums[1]],
            [nums[9], nums[10], nums[11], nums[2]],
            [0.,      0.,       0.,       1.     ],
        ], dtype=np.float64)
        N = len(sub_v)
        h = np.empty((N, 4), dtype=np.float64)
        h[:, :3] = sub_v
        h[:, 3] = 1.0
        world_v = (W @ h.T).T[:, :3]

        # Final color resolution (replace remaining -1 with top_color or fallback)
        fallback = top_color if top_color not in _INHERIT else 7  # Light Gray
        final_c = np.where(sub_c == -1, fallback, sub_c)

        # LDraw → Blender coordinates + scaling:
        #   bx =  lx * SCALE   (X unchanged)
        #   by =  lz * SCALE   (Z → Y, depth)
        #   bz = -ly * SCALE   (Y-down → Z-up)
        blender_v = np.empty_like(world_v)
        blender_v[:, 0] =  world_v[:, 0] * SCALE
        blender_v[:, 1] =  world_v[:, 2] * SCALE
        blender_v[:, 2] = -world_v[:, 1] * SCALE

        # Split by color
        for cid in np.unique(final_c):
            tri_mask = np.repeat(final_c == cid, 3)
            verts_by_color[int(cid)].append(blender_v[tri_mask])

    t_geom_dur = time.time() - t_geom
    total_tris = sum(
        sum(v.shape[0] for v in vlist) // 3
        for vlist in verts_by_color.values()
    )
    print(
        f"[StudioImport] Geometry: {t_geom_dur:.2f}s | "
        f"{total_tris:,} triangles | "
        f"Cache: {len(geom_cache)} files | "
        f"Missing: {len(missing_files)}"
    )
    if missing_files:
        sample = ', '.join(sorted(missing_files)[:10])
        sfx = '…' if len(missing_files) > 10 else ''
        print(f"[StudioImport] Missing parts: {sample}{sfx}")

    if total_tris == 0:
        if wm:
            wm.progress_end()
        hint = " (set LDraw path in add-on preferences)" if not ldraw_path else ""
        return False, f"No geometry found{hint}"

    # 4) Delete all existing LDraw materials (complete clean slate).
    #    Prevents cached or outdated materials from previous imports
    #    from overwriting or overlaying the new color settings.
    _report_bsdf_inputs_once()
    for mat in list(bpy.data.materials):
        if mat.name.startswith("LDraw_Color_"):
            bpy.data.materials.remove(mat, do_unlink=True)

    # 4b) Set up scene lighting (removes default light, adds studio lights)
    _setup_scene_lighting()

    # 4c) Set Color Management to Standard (prevents AgX desaturation of LEGO colors)
    _setup_color_management()

    # 5) Create Blender collection + objects
    t_mesh = time.time()
    model_name = os.path.splitext(os.path.basename(filepath))[0]

    # Remove old import collection (important for re-import without File > New).
    # Without cleanup, old objects with deleted materials remain in the scene
    # and render as Blender default (yellowish-gray) → overlays new objects.
    old_coll = bpy.data.collections.get(model_name)
    if old_coll is not None:
        for obj in list(old_coll.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old_coll)

    coll = bpy.data.collections.new(model_name)
    bpy.context.scene.collection.children.link(coll)

    n_objects = 0
    for color_id, vlist in sorted(verts_by_color.items()):
        all_v = np.vstack(vlist)          # (3*N, 3)
        obj_name = f"LDraw_{color_id}"
        obj = _create_mesh_object(obj_name, all_v, coll)
        mat = _get_or_create_material(color_id)
        obj.data.materials.append(mat)
        n_objects += 1

    # Diagnostic output: check all Trans materials with their BSDF values
    _log_trans_materials()

    if wm:
        wm.progress_end()

    # 6) Position camera (removes default camera, sets up studio camera)
    _setup_camera(coll)

    # 7) Switch viewport to Material Preview (prevents SOLID mode confusion:
    #    in SOLID materials don't appear → Trans parts look opaque,
    #    colors correspond to random Blender object colors instead of the material)
    _switch_viewport_to_material()

    # 8) Link diagnostic: object → material (confirms correct assignment)
    print("[StudioImport] ── Object→Material links ──────────────────────")
    for obj in sorted(coll.all_objects, key=lambda o: o.name):
        if obj.type != 'MESH':
            continue
        mats = obj.data.materials
        if not mats:
            print(f"  {obj.name}: NO MATERIAL!")
            continue
        mat = mats[0]
        if mat is None:
            print(f"  {obj.name}: Material slot empty (None)!")
            continue
        # Get color value from BSDF for quick sanity check
        bsdf = next((n for n in mat.node_tree.nodes
                     if n.type == 'BSDF_PRINCIPLED'), None)
        bc_str = ""
        if bsdf and "Base Color" in bsdf.inputs:
            bc = bsdf.inputs["Base Color"].default_value
            bc_str = f" | Base Color: ({bc[0]:.3f}, {bc[1]:.3f}, {bc[2]:.3f})"
        print(f"  {obj.name} → '{mat.name}'{bc_str}")
    print("[StudioImport] ─────────────────────────────────────────────────────────")

    t_total = time.time() - t0
    print(
        f"[StudioImport] Mesh: {time.time()-t_mesh:.2f}s | "
        f"Total: {t_total:.1f}s | {n_objects} objects"
    )

    msg = f"Imported: {total_tris:,} triangles, {n_objects} objects ({t_total:.1f}s)"
    if missing_files:
        msg += f" | {len(missing_files)} parts missing (LDraw library)"
    return True, msg


# ---------------------------------------------------------------------------
# Blender add-on classes
# ---------------------------------------------------------------------------

class StudioImportPreferences(AddonPreferences):
    bl_idname = __name__

    ldraw_path: StringProperty(
        name="LDraw Library Path",
        description=(
            "Path to the LDraw parts library (contains 'parts' and 'p' subdirectories). "
            "Download: https://www.ldraw.org/parts/latest-parts.html"
        ),
        default=os.path.expanduser("~/Documents/Blender/lib/ldraw"),
        subtype='DIR_PATH',
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="LDraw Parts Library (for complete rendering):")
        layout.prop(self, "ldraw_path")
        layout.label(
            text="Download: https://www.ldraw.org/parts/latest-parts.html",
            icon='URL',
        )


class IMPORT_OT_studio_io(Operator, ImportHelper):
    """Imports a BrickLink Studio .io file"""

    bl_idname  = "import_scene.studio_io"
    bl_label   = "BrickLink Studio (.io)"
    bl_description = "Import a BrickLink Studio .io file as a 3D model"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".io"
    filter_glob: StringProperty(default="*.io", options={'HIDDEN'})

    def execute(self, context):
        prefs_addon = context.preferences.addons.get(__name__)
        ldraw_path  = prefs_addon.preferences.ldraw_path if prefs_addon else ""

        success, message = import_studio_file(self.filepath, ldraw_path)

        if success:
            self.report({'INFO'}, message)
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


def _menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_studio_io.bl_idname, text="BrickLink Studio (.io)")


def register():
    bpy.utils.register_class(StudioImportPreferences)
    bpy.utils.register_class(IMPORT_OT_studio_io)
    bpy.types.TOPBAR_MT_file_import.append(_menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu_func_import)
    bpy.utils.unregister_class(IMPORT_OT_studio_io)
    bpy.utils.unregister_class(StudioImportPreferences)


if __name__ == "__main__":
    register()
