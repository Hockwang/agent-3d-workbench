"""Blender helper: sample an existing diagnostic scene at 12.5 fps.

This renders actual geometry. It neither interpolates rendered images nor edits
the rig, skin weights, joint limits or semantic part ownership.
"""

import json
from pathlib import Path
import time

import bpy


def render_sequence(out: Path, duration: float, *, square: bool = False):
    directory = out / "frames"
    if directory.exists():
        raise RuntimeError("Refusing to overwrite an animation sequence")
    directory.mkdir()
    scene = bpy.context.scene
    source_fps = scene.render.fps / scene.render.fps_base
    output_fps = 12.5
    count = round(duration * output_fps)
    assert count == duration * output_fps
    scene.render.resolution_x = 360 if square else 420
    scene.render.resolution_y = 360 if square else 350
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    started = time.monotonic()
    for i in range(count):
        source_frame = 1 + i * source_fps / output_fps
        frame = int(source_frame)
        scene.frame_set(frame, subframe=source_frame - frame)
        scene.render.filepath = str((directory / f"frame-{i:04d}.png").resolve())
        bpy.ops.render.render(write_still=True)
    record = {
        "duration_seconds": duration,
        "fps": output_fps,
        "frames": count,
        "size": [scene.render.resolution_x, scene.render.resolution_y],
        "source_fps": source_fps,
        "source_frame_samples": [1 + i * source_fps / output_fps for i in range(count)],
        "renderer": "Blender Cycles, 16 samples, denoising",
        "blender_version": bpy.app.version_string,
        "frame_render_wall_seconds": round(time.monotonic() - started, 3),
        "note": "Display rendering only; excludes experiment and scene-building time.",
    }
    (out / "animation-render.json").write_text(json.dumps(record, indent=2) + "\n")
    print("ANIMATION_SEQUENCE_COMPLETE", json.dumps(record))
