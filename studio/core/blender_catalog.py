"""UI metadata independent of Blender runtime."""

CATALOG = [
    {
        "id": "scene-render",
        "title": "blender_catalog.scene_render_title",
        "description": "blender_catalog.scene_render_description",
        "params": {"resolution": 1200, "samples": 32},
    },
    {
        "id": "turntable",
        "title": "blender_catalog.turntable_title",
        "description": "blender_catalog.turntable_description",
        "params": {"frames": 120},
    },
    {
        "id": "rig-bind",
        "title": "blender_catalog.rig_bind_title",
        "description": "blender_catalog.rig_bind_description",
        "params": {},
    },
    {
        "id": "skin-weights",
        "title": "blender_catalog.skin_weights_title",
        "description": "blender_catalog.skin_weights_description",
        "params": {"max_influences": 4},
    },
    {
        "id": "motion-retarget",
        "title": "blender_catalog.motion_retarget_title",
        "description": "blender_catalog.motion_retarget_description",
        "params": {"root_scale": 1},
    },
    {
        "id": "texture-bake",
        "title": "blender_catalog.texture_bake_title",
        "description": "blender_catalog.texture_bake_description",
        "params": {"ratio": 0.5, "resolution": 1024},
    },
    {
        "id": "surface-fit",
        "title": "blender_catalog.surface_fit_title",
        "description": "blender_catalog.surface_fit_description",
        "params": {"offset_mm": 0.1},
    },
    {
        "id": "local-sculpt",
        "title": "blender_catalog.local_sculpt_title",
        "description": "blender_catalog.local_sculpt_description",
        "params": {"radius_mm": 10, "iterations": 10, "max_displacement_mm": 1},
    },
    {
        "id": "hair-cards",
        "title": "blender_catalog.hair_cards_title",
        "description": "blender_catalog.hair_cards_description",
        "params": {},
    },
]
