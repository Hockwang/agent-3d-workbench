# Assembly comparison evidence tools / 对照证据工具

Results: [English](../../docs/ASSEMBLY_COMPARISON.md) · [简体中文](../../docs/ASSEMBLY_COMPARISON.zh-CN.md).

These scripts measure and display already-produced artifacts. They are **not** the
agent's rigging, articulation or segmentation algorithm. They do not submit a paid
task, read credentials, or publish company service costs.

这些脚本用于已有交付的计量与展示，不是自动建模算法，不会提交付费任务或发布公司成本。
大型模型不包含在 Git 仓库中。下列路径均由你替换为自己的文件；不要把私有日志复制进仓库。

## Export usage / 导出用量

Use a **fresh agent session per route**. The parser freezes at the first terminal
task event, so later reviews or documentation in that chat do not contaminate the
experiment. Repairs must happen inside that first task to be included. Cumulative
token snapshots are not summed; cached input and reasoning output are subsets.
An incomplete, mixed-model, regressing or malformed log is not assigned a price.
Nonzero cache writes are not priced until their inclusion semantics are verified.

每条路线使用新会话，冻结首次任务结束前的累计计数；后续审查不混入实验消耗。修复应在该任务内完成。
价格只是公开 API 费率情景，不是 Codex 订阅账单或 3D 服务总成本。

Private manifest outside the repo / 仓外私有清单：

```json
{
  "runs": [{
    "case": "fox-rig",
    "route": "rig-local",
    "rollout": "/absolute/private/session.jsonl",
    "input_sha256": "replace-with-64-lowercase-hex-characters",
    "result": "completed"
  }]
}
```

```bash
uv run --frozen python examples/assembly_comparison/report_usage.py \
  --manifest /absolute/private/manifest.json --output /absolute/public/usage.json
uv run --frozen pytest tests/test_comparison_usage.py -q
```

The exporter allows only this batch's case/route IDs. Read the report's pricing
date before reuse; rates are a recorded snapshot, not automatically updated quotes.
Only allowlisted counters and identifiers enter the report; arbitrary manifest
fields, source paths, prompts, session IDs and API receipts do not.

## Render actual artifacts / 渲染真实产物

Requires Blender with its bundled Python and NumPy. In the commands below,
`blender` means your Blender executable (on macOS it may be inside `Blender.app`).
Output directories must not already contain a completed diagnostic GLB.

```bash
blender --background --python examples/assembly_comparison/pose_rig.py -- \
  --model /data/rig.glb --mapping /data/joints.json \
  --reference /data/source.glb --out /data/new-pose-check

blender --background --python examples/assembly_comparison/pose_urdf.py -- \
  --urdf /data/assembly/robot.urdf --up y \
  --reference /data/source.glb --out /data/new-joint-check

blender --background --python examples/assembly_comparison/render_parts.py -- \
  --model /data/segmented.glb --reference /data/source.glb --out /data/new-parts-check
```

- `pose_rig.py`: one armature, original geometry/weights retained. `joints.json`
  uses `{"mapping":{"front_left":{"upper":"bone-name"},"hind_right":{"upper":"bone-name"},"head":"bone-name","tail":"bone-name"}}`.
  Mappings need an explicit anatomical review; matching labels is not proof of matching anatomy.
- `pose_urdf.py`: follows declared limits and relative OBJ/GLB mesh paths; specify
  the actual URDF `--up y` or `--up z`. `--reverse` changes display phase direction
  only. Does not infer closure, repair geometry, or certify collision freedom.
- `render_parts.py`: displays assembled and centroid-exploded parts with a fixed
  palette. Colors do not establish cross-method semantic correspondence.

These are small diagnostic tests, not natural gait, printability, or simulation
certification. Geometry is not rescaled to make methods look alike.

这些脚本保留原几何和真实关节，仅生成检查用摆姿／展开。不能据此声称自然行走、可打印或仿真就绪。

### Animated evidence / 动图证据

Add `--animate` to any of the three Blender commands. This also writes a `frames/`
PNG sequence and `animation-render.json` via [render_sequence.py](render_sequence.py).
All cases sample at 12.5 fps: the fox's existing pose cycle is 2.4 seconds, the
desk's existing joint cycle is 4 seconds, and the fan's display-only explosion
goes out and back in 4 seconds. Model geometry, weights and part ownership are
unchanged. The renderer is Blender Cycles with 16 samples and denoising; lighting
and source-derived framing are shared within a case. No optical-flow frames are added.

```bash
ffmpeg -framerate 12.5 -i /data/new-pose-check/frames/frame-%04d.png \
  -c:v libx264 -crf 16 -pix_fmt yuv420p /data/fox-pose.mp4
```

Use the same full interval, frame rate and resolution for both/all methods when
converting to GIF. Horizontal stacking before GIF encoding gives a synchronized
comparison; independent GIFs in a Markdown table may start at different times.
Published parameters, hashes and display-production timings are in
[media-manifest.json](../../docs/assets/assembly-comparison/gifs/media-manifest.json).
Experiment token, time and API-equivalent cost remain in the separate
[usage.json](../../docs/assets/assembly-comparison/usage.json).

添加 `--animate` 可渲染真实网格序列。动图制作不会重新调用生成 API，也不计入原实验费用；
本地渲染耗时另记，电费和制作会话 token 未计量，不标成“总成本为零”。

## Local interactive review / 本地交互查看

`viewer.html` expects `manifest.json`, GLBs and a local Three.js runtime beside it.
Copy [manifest.example.json](manifest.example.json) as `manifest.json` for this
recorded batch. Its seven filenames refer to the separate display bundle, not
files shipped in Git. For different inputs, replace both the artifacts and the
`source_framing.bounds_y_up` values; use the same source frame for all routes.
The viewer starts in Chinese and offers an **EN / 中文** toggle.
Use only a dedicated, allowlisted review folder, never a private run-log directory.
Copy the matching dependency files from this repo after `npm ci`:

```text
review/
  index.html                 # copy viewer.html
  manifest.json
  rig-local.glb               # and the other explicitly selected display GLBs
  vendor/build/three.module.min.js
  vendor/build/three.core.min.js
  vendor/examples/jsm/loaders/GLTFLoader.js
  vendor/examples/jsm/controls/OrbitControls.js
  vendor/examples/jsm/utils/BufferGeometryUtils.js
  vendor/examples/jsm/utils/SkeletonUtils.js
  vendor/LICENSE             # Three.js license
```

Serve that folder on loopback and open the URL in a browser:

```bash
uv run python -m http.server 63871 --bind 127.0.0.1 --directory /absolute/review
```

The manifest must name display artifacts accurately: rig pose clips and converted
URDF motion are derived diagnostic files, not original API animations. Avoid
credentials or signed service URLs in the manifest. Local downloads do not upload
anything back to the service.

本地查看器仅服务你明确选入的文件。绑骨／URDF 动画是派生诊断文件，应与原 API 交付区分。
