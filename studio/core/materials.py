"""Exact material-slot edits; geometry and unselected PBR channels stay intact."""

import copy
from pathlib import Path
import re

import numpy as np
from PIL import Image
from trimesh.visual import TextureVisuals
from trimesh.visual.material import MultiMaterial, PBRMaterial

from studio.i18n import render as _render_message


def slots(mesh):
    material = getattr(mesh.visual, "material", None)
    return list(material.materials) if isinstance(material, MultiMaterial) else ([material] if material else [])


def describe(mesh):
    result = []
    for index, mat in enumerate(slots(mesh)):
        rgba = getattr(mat, "baseColorFactor", None)
        rgba = [255, 255, 255, 255] if rgba is None else list(map(int, rgba))
        result.append(
            {
                "slot": index,
                "name": getattr(mat, "name", None) or _render_message("materials.default_slot_name", index=index + 1),
                "editable": isinstance(mat, PBRMaterial),
                "color": "#" + "".join(f"{x:02x}" for x in rgba[:3]),
                "alpha": rgba[3] / 255,
                "roughness": getattr(mat, "roughnessFactor", None)
                if getattr(mat, "roughnessFactor", None) is not None
                else 1,
                "metallic": getattr(mat, "metallicFactor", None)
                if getattr(mat, "metallicFactor", None) is not None
                else 1,
                "base_color_texture": getattr(mat, "baseColorTexture", None) is not None,
            }
        )
    return result


def edit(mesh, params):
    from studio.core.editor import EditorError

    selected = params.get("material_slots")
    if selected is not None and (
        not isinstance(selected, list)
        or not selected
        or any(type(i) is not int or i < 0 for i in selected)
        or len(set(selected)) != len(selected)
    ):
        raise EditorError.coded("materials.invalid_material_slots")
    if not slots(mesh):
        if selected is not None:
            raise EditorError.coded("materials.no_material_slots")
        if mesh.visual.kind in ("vertex", "face") and np.any(mesh.visual.main_color != mesh.visual.vertex_colors):
            raise EditorError.coded("materials.multicolor_requires_conversion")
        mesh.visual = TextureVisuals(material=PBRMaterial(baseColorFactor=mesh.visual.main_color))
    # A shared slot/material must never alter a different object or cached asset.
    mesh.visual.material = copy.deepcopy(mesh.visual.material)
    materials = slots(mesh)
    selected = list(range(len(materials))) if selected is None else selected
    if any(i >= len(materials) for i in selected):
        raise EditorError.coded("materials.stale_material_slots")
    updates = {}
    for key in ("roughness", "metallic"):
        if key in params:
            value = float(params[key])
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise EditorError.coded("materials.parameter_out_of_range")
            updates[key + "Factor"] = value
    if "color" in params:
        color = params["color"]
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise EditorError.coded("materials.invalid_color_format")
    if "base_color_texture" in params:
        filename = params["base_color_texture"]
        if filename is None:
            updates["baseColorTexture"] = None
        else:
            path = Path(filename).expanduser()
            if not path.is_absolute() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
                raise EditorError.coded("materials.texture_path_invalid")
            uv = getattr(mesh.visual, "uv", None)
            if uv is None or len(uv) != len(mesh.vertices) or not np.isfinite(uv).all():
                raise EditorError.coded("materials.texture_requires_uv")
            with Image.open(path) as image:
                if image.format not in ("PNG", "JPEG", "WEBP") or image.width * image.height > 16_777_216:
                    raise EditorError.coded("materials.texture_format_or_size")
                updates["baseColorTexture"] = image.convert("RGBA").copy()
    for index in selected:
        mat = materials[index]
        if not isinstance(mat, PBRMaterial):
            raise EditorError.coded("materials.requires_pbr_material")
        for key, value in updates.items():
            setattr(mat, key, value)
        if "color" in params:
            alpha = int(mat.baseColorFactor[3]) if mat.baseColorFactor is not None else 255
            mat.baseColorFactor = [int(params["color"][i : i + 2], 16) for i in (1, 3, 5)] + [alpha]
    return mesh
