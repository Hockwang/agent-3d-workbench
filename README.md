[简体中文](README.zh-CN.md) · [Getting started](docs/GETTING_STARTED.md) · [Agent playbook](docs/AGENT_PLAYBOOK.md)

# Agent 3D Workbench

[![💬 Join Discord](docs/assets/discord-join.svg)](https://discord.gg/r8BVSGtR8H)

**Choose your tools. Let your AI agent model and split parts, then inspect and edit the results together.**

Works with Codex, Claude Code, and other MCP clients. Local code needs no DiT model,
3D service account, or 3D API key. You can also connect your own Hunyuan or Assembly service.
Your agent account/subscription and any 3D service fees are separate.

## What can you do?

You and your agent share one project, model, and selection. These tools run locally; install Blender, Node.js, or slicing software when a task needs them.

| Feature | What you can do |
| --- | --- |
| **View and edit** | Import GLB/STL, select parts, move, rotate, scale, undo/redo, and ask your agent to change only the intended objects. |
| **Model with code** | Have your agent create models with Python/CadQuery/Blender, specify dimensions and parts, and keep the scripts editable. |
| **Split and repair** | Use plane cuts, booleans, connected components, explicit face labels, small-hole repair, and simplification. |
| **Materials and appearance** | Adjust color, roughness, and metalness per object or material slot; replace textures and run UV/baking tasks. |
| **Functional geometry** | Create cavities, lids, head shells, locating pins/holes, color inserts, and joint modules from explicit dimensions and machining regions. |
| **Rigging and motion** | Bind explicit skeletons and repair weights; edit mechanical joints, bone poses, and keyframes, then preview and export animation. |
| **Inspect and check** | Review real renders, dimensions, and mesh reports; sample collisions at specified joint poses and record issues. |
| **Print preparation** | Orient parts, arrange plates, export STL/3MF projects, and estimate time and material with configured slicing software. |
| **Projects and delivery** | Save and reopen projects, find outputs and versions in Task overview, export GLB/STL, and keep editing generated models. |

Each tool has input requirements. Automatic semantic splitting, natural motion, and physical manufacturability need separate validation.
[Full capabilities and conditions](docs/PUBLIC_CAPABILITIES.md) · [Your first edit](docs/GETTING_STARTED.md)

## Edit together in the workbench

![Select a cup part in the 3D Workbench, let the agent edit it, then undo](docs/assets/point-and-edit.gif)

**Select a part → ask your agent to edit → inspect the change → undo.** This cup example shows a shared model, selection, and operation history.
In the current interface, click **Attach selection to chat** to include it in a message; agents can also read the live selection through MCP.
[Follow the first-edit tutorial →](docs/GETTING_STARTED.md)

**Pikachu head shell: keep editing its 13 existing parts.**

![Select and move the Pikachu ear, undo, then move the back shell to inspect the cavity in the workbench](docs/assets/pikachu-head-shell/workbench-edit.gif)

Move the yellow and black ear pieces together → undo → move the back shell aside to inspect the cavity → restore.
This is a keyframe replay of new operations on the v6 delivery model, using local MCP tools without a generation API.
Designed around a 60 cm head circumference; still a structural draft with a blocked sightline, not printed or test-fitted. [See the full STL-to-parts and magnet-mount case →](docs/PIKACHU_HEAD_SHELL.md)

For image-to-3D generation or specialized splitting, you can also choose an API route. The examples below show the differences in actual outputs.

## Modeling: code or a generation model?

The same cup reference image, processed with two different tools:

| Reference | Codex · Code modeling | Agent + Hunyuan · DiT modeling |
| --- | --- | --- |
| ![Cup reference image](docs/assets/cup-comparison/reference.png) | ![Local code model](docs/assets/cup-comparison/local.png) | ![Hunyuan generated model](docs/assets/cup-comparison/generated.png) |
| Same input image | Python builds a body, handle, lid, and knob: 4 separately editable parts | Hunyuan 3D generates a model with PBR textures; Part can split it afterward |
| Choose when you want… | Explicit dimensions and structure that you can keep adjusting in code | A 3D draft from an image, including surface detail |

The local model simplifies the shape and texture; Hunyuan also changes proportions and gloss.
An image does not establish real dimensions. [Models, prompts, and reproduction steps →](docs/CUP_COMPARISON.md)

## Splitting: local code or a specialized API?

The first two columns use **the same fan**; Hunyuan Part uses **the cup example**.
These show what each tool does, not a three-way ranking on one input.

| GPT-6 · Local splitting | GPT-6 + Assembly · P3RW | Agent + Hunyuan Part |
| --- | --- | --- |
| ![Local code splits the fan into seven parts](docs/assets/assembly-comparison/gifs/fan-segment-local.gif) | ![P3RW splits the same fan into nine parts](docs/assets/assembly-comparison/gifs/fan-segment-p3.gif) | ![Hunyuan Part separates the cup handle](docs/assets/cup-comparison/api-parts.png) |
| Agent-written mesh code: 7 parts here, retaining source triangles | Specialized segmentation service: 9 parts here, retaining source triangles | Generative part service: 2 parts here—handle, and body + lid + knob |
| Rear grille includes some base faces; rules still need adjustment | Some functional parts remain merged and need further splitting | Lid remains fused; topology changes and segment colors replace PBR textures |
| Specify splitting rules and keep refining the code with your agent | Get a first set of parts from a dedicated segmenter | Add separately editable parts to a generated model |

All three outputs need inspection. More parts do not necessarily mean better segmentation or printable solids.
[Fan GIFs, tokens, time, and estimates](docs/ASSEMBLY_COMPARISON.md) · [Hunyuan Part results and limits](docs/CUP_COMPARISON.md)

API routes need your own service access. [Hunyuan setup](docs/API_GENERATION_DEMO.md) · [Assembly setup](docs/ASSEMBLY_API.md).
The P3RW demo used the native Assembly service; the plugin OpenAPI gateway still needs end-to-end validation.

## Get started

You need Git, [uv](https://docs.astral.sh/uv/), Python 3.12+, Codex desktop, and a Codex CLI with plugin support:

```bash
git clone https://github.com/Hockwang/agent-3d-workbench.git
cd agent-3d-workbench
STUDIO_LANG=en ./install.sh --add
```

Reopen Codex, then ask: **“Open the 3D Workbench for this chat.”**
English and Chinese are supported. Install tools such as Blender when your chosen task needs them.
[Claude Code / other MCP clients, full setup, and your first edit →](docs/GETTING_STARTED.md)

Give the agent an image or model and name the tool you want, for example:

- **Code modeling:** “Use local code to model this reference. Make the body, handle, and lid separately editable. Do not call a generation API.”
- **DiT modeling:** “Generate a model from this image using my configured Hunyuan service.”
- **Splitting:** “Split this model using local code / Assembly P3RW / Hunyuan Part. Show the parts and report anything still fused.” Pick one of the three.

Use **Open file** for an existing model and **Task overview** for generated results.
Select a part, then ask your agent to edit, undo, or export it.
Agents should first read the [playbook](docs/AGENT_PLAYBOOK.md), check available tools, the current workspace and selection, then act and inspect the actual output.

More examples: [Pikachu head shell](docs/PIKACHU_HEAD_SHELL.md) · [Rigging and drawer motion](docs/ASSEMBLY_COMPARISON.md).
[Capabilities](docs/PUBLIC_CAPABILITIES.md) · [Tool reference](docs/TOOLS.md) · [Contributing](CONTRIBUTING.md) · [Feedback](https://github.com/Hockwang/agent-3d-workbench/issues)

Pre-1.0; full desktop workflow tested on macOS, pending on Linux/Windows. [MIT](LICENSE) · [Third-party notices](docs/THIRD_PARTY.md)
