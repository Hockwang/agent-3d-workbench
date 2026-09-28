> 中文：[zh-CN/index.md](zh-CN/index.md)

# Documentation index

Documents are written in English; the ones that also have a Chinese version link to it as `[中文](zh-CN/…)`. The Chinese copies live in [`docs/zh-CN/`](zh-CN/) and mirror the English files one-to-one. Root-level specs follow the same pattern: [SPEC.md](../SPEC.md) / [SPEC.zh-CN.md](../SPEC.zh-CN.md) (workbench spec) and [SPEC_RECIPES.md](../SPEC_RECIPES.md) / [SPEC_RECIPES.zh-CN.md](../SPEC_RECIPES.zh-CN.md) (recipe format).

Start here: [TOOLS.md](TOOLS.md), [ARCHITECTURE.md](ARCHITECTURE.md) ([中文](zh-CN/ARCHITECTURE.md)), [CONFIGURATION.md](CONFIGURATION.md) ([中文](zh-CN/CONFIGURATION.md)), [CORE_CLI.md](CORE_CLI.md) ([中文](zh-CN/CORE_CLI.md)), and [AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) ([中文](zh-CN/AGENT_PLAYBOOK.md)) cover the tool reference, system architecture, service configuration, the core CLI, and the agent-facing operating playbook, respectively.

## Product principles and scope

- [PUBLIC_CAPABILITIES.md](PUBLIC_CAPABILITIES.md) ([中文](zh-CN/PUBLIC_CAPABILITIES.md)) — local, no-service capability promises, explicit inputs and acceptance limits.
- [LOCAL_CAPABILITIES_VALIDATION_20260926.md](LOCAL_CAPABILITIES_VALIDATION_20260926.md) ([中文](zh-CN/LOCAL_CAPABILITIES_VALIDATION_20260926.md)) — real MCP, network-isolated fabrication and regression evidence.
- [AGENT_WORKSPACE.md](AGENT_WORKSPACE.md) ([中文](zh-CN/AGENT_WORKSPACE.md)) — product principle: the AI should be able to read state, act, gather evidence, and verify, the same way it does when writing code.
- [CAPABILITY_PARITY.md](CAPABILITY_PARITY.md) ([中文](zh-CN/CAPABILITY_PARITY.md)) — the task-coverage basis used to define "done" for a feature, and the current gaps.
- [WORKBENCH_V06.md](WORKBENCH_V06.md) ([中文](zh-CN/WORKBENCH_V06.md)) — the v0.6 feature summary: model editing and print preparation.
- [WORKBENCH_TASKS.md](WORKBENCH_TASKS.md) ([中文](zh-CN/WORKBENCH_TASKS.md)) — the modeling, service, and artifact task workspace.

## Core workflows

- [CITY_RUNTIME.md](CITY_RUNTIME.md) ([中文](zh-CN/CITY_RUNTIME.md)) — the full city/world workbench (requires a user-supplied scene package).
- [CODEX_V05_INTEGRATION.md](CODEX_V05_INTEGRATION.md) ([中文](zh-CN/CODEX_V05_INTEGRATION.md)) — how the v0.5 panel integrates with the Codex sidebar workspace.
- [DIRECT_PART_CHAT.md](DIRECT_PART_CHAT.md) ([中文](zh-CN/DIRECT_PART_CHAT.md)) — creating a per-part chat branch directly (includes host support matrix).
- [FOLDER_PROJECTS.md](FOLDER_PROJECTS.md) ([中文](zh-CN/FOLDER_PROJECTS.md)) — the folder-based project/ownership model.
- [GENERATED_ASSET_EDITING.md](GENERATED_ASSET_EDITING.md) ([中文](zh-CN/GENERATED_ASSET_EDITING.md)) — continuing to edit a generated asset after it comes back from a service.
- [HEAD_SHELL.md](HEAD_SHELL.md) ([中文](zh-CN/HEAD_SHELL.md)) — the built-in "character head-shell fabrication" recipe and task template.
- [MERGE_A8_WORKSPACE.md](MERGE_A8_WORKSPACE.md) ([中文](zh-CN/MERGE_A8_WORKSPACE.md)) — the merge/A8 viewer workspace integration.
- [MOTION_EDITING.md](MOTION_EDITING.md) ([中文](zh-CN/MOTION_EDITING.md)) — the motion/keyframe editing feature.
- [SCENE_EDITING.md](SCENE_EDITING.md) ([中文](zh-CN/SCENE_EDITING.md)) — editing scene instances (placement, transforms; includes host support matrix).
- [WORKTREE_COLLABORATION.md](WORKTREE_COLLABORATION.md) ([中文](zh-CN/WORKTREE_COLLABORATION.md)) — collaborating on the same part across worktrees.

## Service integrations

- [ASSEMBLY_API.md](ASSEMBLY_API.md) ([中文](zh-CN/ASSEMBLY_API.md)) — the optional remote Assembly workflow service.
- [BYOK_SERVICES.md](BYOK_SERVICES.md) ([中文](zh-CN/BYOK_SERVICES.md)) — bring-your-own-key setup for third-party 3D generation APIs.
- [HUNYUAN_API.md](HUNYUAN_API.md) ([中文](zh-CN/HUNYUAN_API.md)) — the Hunyuan 3D / Part generation service.
- [LUX3D.md](LUX3D.md) ([中文](zh-CN/LUX3D.md)) — Lux3D integration and capability notes.
- [WAVEAB_EVALUATION_PLATFORM.md](WAVEAB_EVALUATION_PLATFORM.md) ([中文](zh-CN/WAVEAB_EVALUATION_PLATFORM.md)) — integration with an internal evaluation platform (requires access you likely don't have).

## Licensing

- [THIRD_PARTY.md](THIRD_PARTY.md) ([中文](zh-CN/THIRD_PARTY.md)) — third-party dependencies and vendored-code attribution; read before redistributing.

## History

`docs/history/` holds superseded proposals, dated validation/fix logs, and other project-record material. These are kept for provenance but are not maintained and may describe states the product has since moved past — treat them as project record, not as current documentation.
