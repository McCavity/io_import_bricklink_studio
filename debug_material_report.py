"""
debug_material_report.py — Material Diagnostic Report
======================================================
Run this script in Blender's Scripting tab to generate a standardized
diagnostic report for LDraw materials in the current scene.

Usage:
  1. Import a .io file with the BrickLink Studio Importer add-on
  2. Open the Scripting workspace in Blender
  3. Open this file (or paste its contents into a new script)
  4. Click "Run Script"
  5. Copy the output from the Blender System Console and paste it into
     your GitHub issue report

Optional — report only specific objects:
  Select one or more objects in the viewport BEFORE running the script.
  If nothing is selected, all LDraw objects in the scene are reported.

GitHub issues: https://github.com/McCavity/io_import_bricklink_studio/issues
"""

import bpy

# ── Configuration ──────────────────────────────────────────────────────────────

# Set to True to include objects with correct/expected values in the report.
# Default: False — only objects that might need attention are highlighted.
REPORT_ALL = True

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_bsdf_input(bsdf, *names):
    """Returns (input_name, value) for the first matching input, or (None, None)."""
    for name in names:
        if name in bsdf.inputs:
            val = bsdf.inputs[name].default_value
            # Convert color values to a readable tuple
            if hasattr(val, '__len__') and len(val) == 4:
                return name, (round(val[0], 3), round(val[1], 3),
                              round(val[2], 3), round(val[3], 3))
            return name, round(float(val), 4)
    return None, None


def format_color(rgba):
    """Format an RGBA tuple as a readable hex + linear string."""
    if rgba is None:
        return "N/A"
    r, g, b, a = rgba
    # Approximate hex (treating values as sRGB for display)
    ri, gi, bi = int(r * 255), int(g * 255), int(b * 255)
    return f"({r:.3f}, {g:.3f}, {b:.3f}, {a:.3f})  ≈ #{ri:02X}{gi:02X}{bi:02X}"


# ── Main report ────────────────────────────────────────────────────────────────

def run_report():
    # Collect objects to report
    selected = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    if selected:
        objects = selected
        scope = f"{len(objects)} selected object(s)"
    else:
        objects = [o for o in bpy.data.objects
                   if o.type == 'MESH' and o.name.startswith("LDraw_")]
        scope = f"all {len(objects)} LDraw object(s) in scene"

    print()
    print("=" * 70)
    print("  BrickLink Studio Importer — Material Diagnostic Report")
    print("=" * 70)
    print(f"  Blender:   {bpy.app.version_string}")
    print(f"  Renderer:  {bpy.context.scene.render.engine}")
    cm = bpy.context.scene.view_settings
    print(f"  Color Mgmt: view_transform='{cm.view_transform}'  "
          f"exposure={cm.exposure:.2f}  gamma={cm.gamma:.2f}")
    print(f"  Scope:     {scope}")
    print("=" * 70)

    if not objects:
        print("  No LDraw objects found. Import a .io file first.")
        print("=" * 70)
        return

    issues_found = 0

    for obj in sorted(objects, key=lambda o: o.name):
        mats = obj.data.materials if obj.data else []
        if not mats or mats[0] is None:
            print(f"\n  ⚠  {obj.name}: NO MATERIAL")
            issues_found += 1
            continue

        mat = mats[0]

        # Extract BrickLink color ID from material name (e.g. "LDraw_Color_11" → 11)
        bl_color_id = "?"
        if mat.name.startswith("LDraw_Color_"):
            try:
                bl_color_id = int(mat.name.split("_")[-1])
            except ValueError:
                pass

        # Find Principled BSDF node
        bsdf = None
        if mat.use_nodes:
            bsdf = next((n for n in mat.node_tree.nodes
                         if n.type == 'BSDF_PRINCIPLED'), None)

        if not bsdf:
            print(f"\n  ⚠  {obj.name} / '{mat.name}': NO PRINCIPLED BSDF NODE")
            issues_found += 1
            continue

        # Read all relevant parameters
        _, base_color  = get_bsdf_input(bsdf, "Base Color", "Color")
        _, alpha       = get_bsdf_input(bsdf, "Alpha", "Opacity")
        _, roughness   = get_bsdf_input(bsdf, "Roughness")
        trans_name, trans_val = get_bsdf_input(bsdf,
            "Transmission Weight", "Transmission", "Glass", "Transmission Amount")
        _, ior         = get_bsdf_input(bsdf, "IOR", "Index of Refraction")
        _, specular    = get_bsdf_input(bsdf,
            "Specular IOR Level", "Specular", "Reflectivity")

        srm            = getattr(mat, 'surface_render_method', 'N/A (Blender < 4.2)')
        blend_method   = getattr(mat, 'blend_method', 'N/A')
        backface_cull  = getattr(mat, 'use_backface_culling', 'N/A')
        is_trans       = isinstance(alpha, float) and alpha < 1.0

        print()
        print(f"  Object:       {obj.name}")
        print(f"  Material:     {mat.name}")
        print(f"  BL Color ID:  {bl_color_id}  "
              f"({'transparent' if is_trans else 'opaque'})")
        print(f"  Base Color:   {format_color(base_color)}")
        print(f"  Alpha:        {alpha}")
        print(f"  Roughness:    {roughness}")
        if trans_name:
            print(f"  {trans_name + ':':21}{trans_val}")
        else:
            print(f"  Transmission: (input not found in this Blender version)")
        if ior is not None:
            print(f"  IOR:          {ior}")
        if specular is not None:
            print(f"  Specular:     {specular}")
        print(f"  surface_render_method: {srm}")
        if blend_method != 'N/A':
            print(f"  blend_method:          {blend_method}")
        print(f"  use_backface_culling:  {backface_cull}")

    print()
    print("=" * 70)
    print(f"  Report complete. {len(objects)} object(s) checked, "
          f"{issues_found} issue(s) flagged.")
    print()
    print("  To report a color problem, open a GitHub issue at:")
    print("  https://github.com/McCavity/io_import_bricklink_studio/issues")
    print()
    print("  Please include in your issue:")
    print("    - The output above (copy from the Blender System Console)")
    print("    - BrickLink Color ID and expected color name")
    print("    - LEGO set number where the color appears")
    print("    - A screenshot if possible")
    print("=" * 70)


run_report()
