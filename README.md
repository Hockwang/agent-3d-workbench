[简体中文](README.zh-CN.md) · [Getting started](docs/GETTING_STARTED.md) · [Agent playbook](docs/AGENT_PLAYBOOK.md)

# Agent 3D Workbench

[![💬 Join Discord](docs/assets/discord-join.svg)](https://discord.gg/r8BVSGtR8H)

**Choose your tools. Let your AI agent model and split parts, then inspect and edit the results together.**

Works with Codex, Claude Code, and other MCP clients. Local code needs no DiT model,
3D service account, or 3D API key. You can also connect your own Hunyuan or Assembly service.
Your agent account/subscription and any 3D service fees are separate.

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
