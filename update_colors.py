#!/usr/bin/env python3
"""
BrickLink Color Table Updater for blender_studio_import.py
===========================================================

Fetches the complete BrickLink color palette from the Rebrickable API
and writes it as 'bricklink_colors.json' to the Blender Add-ons directory.

The plugin loads this file automatically on startup — the program logic
(blender_studio_import.py) is NOT modified in the process.

Requirements:
  Free Rebrickable API key:
  → https://rebrickable.com/users/create/ (registration)
  → https://rebrickable.com/users/<username>/settings/#api  (API key)

Usage:
  # Write JSON to the default Blender Add-ons directory:
  python3 update_colors.py --key YOUR_KEY

  # Explicit path (e.g. directly into the plugin directory):
  python3 update_colors.py --key YOUR_KEY --out /path/to/addons/

  # Print only, write nothing:
  python3 update_colors.py --key YOUR_KEY --dry-run

  # Auto-detect Blender Add-ons directory:
  python3 update_colors.py --key YOUR_KEY --blender /Applications/Blender.app
"""

import sys
import json
import os
import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ── Configuration ──────────────────────────────────────────────────────────────

REBRICKABLE_API = "https://rebrickable.com/api/v3/lego/colors/"
PAGE_SIZE       = 300   # more than enough for all ~230 BL colors
OUTPUT_FILENAME = "bricklink_colors.json"

# Known Blender Add-ons paths (checked in order)
BLENDER_ADDON_CANDIDATES = [
    # macOS
    os.path.expanduser("~/Library/Application Support/Blender"),
    # Linux
    os.path.expanduser("~/.config/blender"),
    # Windows
    os.path.expandvars(r"%APPDATA%\Blender Foundation\Blender"),
]

# Values empirically verified on Galaxy Explorer 497 — will NOT be
# overwritten by API values, as Blender expects linear color values
# and some API values (sRGB) appear too bright/dark there.
EMPIRICAL_OVERRIDES = {
    3:  (0.969, 0.820, 0.090, 1.0),   # Yellow — empirically
    5:  (0.788, 0.102, 0.035, 1.0),   # Red — empirically
    6:  (0.058, 0.369, 0.059, 1.0),   # Green — empirically
    7:  (0.000, 0.149, 0.651, 1.0),   # Blue — empirically + Blender linear correction
    9:  (0.541, 0.573, 0.553, 1.0),   # Light Gray — empirically
    11: (0.067, 0.067, 0.067, 1.0),   # Black — empirically
    17: (0.722, 0.153, 0.000, 0.55),  # Trans-Red — empirically
    19: (0.980, 0.945, 0.365, 0.55),  # Trans-Yellow — empirically
    20: (0.451, 0.706, 0.392, 0.55),  # Trans-Green — empirically
}

# Special IDs unknown to Rebrickable (BrickLink Studio-internal):
EXTRA_ENTRIES = {
    -11: (0.020, 0.020, 0.020, 1.0),  # Rubber Black
    0:   (0.067, 0.067, 0.067, 1.0),  # Fallback Black
}

# ── Helper functions ────────────────────────────────────────────────────────────

def find_blender_addons_dir(blender_hint: str | None = None) -> str | None:
    """
    Searches for the Blender Add-ons directory of the newest installed Blender version.
    Returns None if not found.
    """
    search_roots = []
    if blender_hint:
        # e.g. /Applications/Blender.app → search there for Resources/scripts/addons
        app_addons = os.path.join(blender_hint, "Contents", "Resources", "scripts", "addons")
        if os.path.exists(app_addons):
            return app_addons
        search_roots.append(blender_hint)

    search_roots.extend(BLENDER_ADDON_CANDIDATES)

    for root in search_roots:
        if not os.path.isdir(root):
            continue
        # Search subdirectories for version numbers (e.g. "4.2", "5.0")
        try:
            versions = sorted(
                [d for d in os.listdir(root)
                 if os.path.isdir(os.path.join(root, d))
                 and d.replace(".", "").isdigit()],
                reverse=True
            )
        except PermissionError:
            continue
        for ver in versions:
            candidate = os.path.join(root, ver, "scripts", "addons")
            if os.path.isdir(candidate):
                return candidate

    return None


def hex_to_rgba(hex_str: str, alpha: float) -> list:
    """Hex string (#RRGGBB or RRGGBB) → [R, G, B, A] with values 0.0–1.0."""
    h = hex_str.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return [round(r, 3), round(g, 3), round(b, 3), round(alpha, 3)]


def fetch_colors(api_key: str) -> list:
    """Fetches all colors from the Rebrickable API."""
    url = f"{REBRICKABLE_API}?page_size={PAGE_SIZE}&key={api_key}"
    print(f"[update_colors] Loading color table from Rebrickable ...")

    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"  ERROR HTTP {e.code}: {e.reason}")
        if e.code == 401:
            print("  → Invalid API key.")
            print("    Regenerate at: https://rebrickable.com/users/<name>/settings/#api")
        sys.exit(1)
    except URLError as e:
        print(f"  ERROR Connection: {e.reason}")
        sys.exit(1)

    colors = data.get("results", [])
    total  = data.get("count", len(colors))
    print(f"  {len(colors)} / {total} colors received")
    return colors


def build_table(colors: list) -> dict:
    """
    Converts the Rebrickable list into {bricklink_id_str: [R, G, B, A]}.
    Also returns a separate name_map {bricklink_id: "Name  #RRGGBB"}.
    """
    table    = {}
    name_map = {}
    skipped  = 0

    for color in colors:
        hex_str  = color.get("rgb", "000000")
        is_trans = color.get("is_trans", False)
        name     = color.get("name", "")
        ext      = color.get("external_ids", {})
        bl_ids   = ext.get("BrickLink", {}).get("ext_ids", [])

        if not bl_ids:
            skipped += 1
            continue

        # Alpha strategy: Trans → 0.55, Milky → 0.70, rest → 1.0
        if is_trans:
            alpha = 0.55
        elif "milky" in name.lower():
            alpha = 0.70
        else:
            alpha = 1.0

        for bl_id in bl_ids:
            label = f"{name}  #{hex_str}"
            name_map[bl_id] = label

            if bl_id in EMPIRICAL_OVERRIDES:
                r, g, b, a = EMPIRICAL_OVERRIDES[bl_id]
                table[str(bl_id)] = [r, g, b, a]
            else:
                table[str(bl_id)] = hex_to_rgba(hex_str, alpha)

    # Special IDs
    for bl_id, rgba in EXTRA_ENTRIES.items():
        table[str(bl_id)] = list(rgba)

    print(f"  {len(table)} BrickLink color IDs "
          f"({skipped} Rebrickable colors without BL ID skipped)")
    return table, name_map


def build_json(table: dict, name_map: dict) -> dict:
    """Builds the complete JSON document."""
    now = datetime.datetime.now(datetime.timezone.utc)
    # Names dict for readability (optional section, ignored by the plugin)
    names = {k: name_map.get(int(k), "") for k in table}
    return {
        "version":     now.strftime("%Y-%m-%d"),
        "generated":   now.isoformat(),
        "source":      "Rebrickable API v3 + empirical corrections (Galaxy Explorer 497)",
        "count":       len(table),
        "empirical_overrides": list(str(k) for k in EMPIRICAL_OVERRIDES),
        "colors":      table,
        "names":       names,   # for information only, not used by the plugin
    }


def write_json(data: dict, out_dir: str) -> str:
    """Writes the JSON file and returns the full path."""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, OUTPUT_FILENAME)

    # Backup if file already exists
    if os.path.exists(out_path):
        bak = out_path + ".bak"
        os.replace(out_path, bak)
        print(f"  Backup: {os.path.basename(bak)}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return out_path


# ── Main program ──────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generates bricklink_colors.json for blender_studio_import.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 update_colors.py --key abc123
  python3 update_colors.py --key abc123 --out ~/Desktop
  python3 update_colors.py --key abc123 --blender /Applications/Blender.app
  python3 update_colors.py --key abc123 --dry-run

Free API key at: https://rebrickable.com/users/create/
        """
    )
    parser.add_argument("--key",     required=True,
                        help="Rebrickable API key")
    parser.add_argument("--out",     default=None,
                        help="Target directory for bricklink_colors.json")
    parser.add_argument("--blender", default=None,
                        help="Path to Blender installation (e.g. /Applications/Blender.app)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print only, do not write")
    args = parser.parse_args()

    # 1. Fetch colors
    colors_raw = fetch_colors(args.key)

    # 2. Build table
    table, name_map = build_table(colors_raw)

    # 3. Assemble JSON document
    data = build_json(table, name_map)

    if args.dry_run:
        print("\n── Result (--dry-run, will not be saved) ─────────────────")
        print(f"  Date:       {data['version']}")
        print(f"  Colors:     {data['count']}")
        print(f"  Empirical:  {data['empirical_overrides']}")
        print("\n  First 10 entries:")
        for k, v in list(data["colors"].items())[:10]:
            print(f"    BL {k:>4}: {v}  # {data['names'].get(k, '')}")
        print("  ...")
        return

    # 4. Determine target directory
    out_dir = args.out
    if not out_dir:
        out_dir = find_blender_addons_dir(args.blender)
        if out_dir:
            print(f"[update_colors] Blender Add-ons directory found: {out_dir}")
        else:
            # Fallback: same directory as update_colors.py
            out_dir = os.path.dirname(os.path.abspath(__file__))
            print(f"[update_colors] No Blender directory found → writing to: {out_dir}")

    # 5. Write
    out_path = write_json(data, out_dir)
    print(f"[update_colors] ✓ Saved: {out_path}")
    print(f"  {data['count']} colors, as of: {data['version']}")
    print()
    print("  → Next steps in Blender:")
    print("    1. Edit → Preferences → Add-ons → 'BrickLink Studio'")
    print("    2. Disable the add-on → enable it again")
    print("    3. Blender console: check for '[StudioImport] color table loaded'")
    print()
    print("  Note: The JSON must be in the same directory as the plugin.")
    print(f"  Plugin directory = {out_dir}")


if __name__ == "__main__":
    main()
