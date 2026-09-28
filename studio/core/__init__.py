"""studio.core: the local capability layer (A).

Everything here works offline: geometry and scene editing, the local task
queue (Blender / CadQuery workers), motion and observation, recipes, history,
projects and workspaces. Each module can be imported and tested without the
MCP server, the HTTP server, the network or Codex; ``python -m studio.core``
exposes the same capabilities on the command line.

Rule: modules in this package must NOT import ``studio.adapters.*`` or
``studio.shell.*`` (hosted services, network access and the MCP/HTTP protocol
details live in those layers). When core needs something the shell knows
(for example the cwd of a Codex thread), the caller passes it in as a
parameter; tests/test_layering.py enforces this.

中文：本机可跑的能力层（A）。几何 / 场景 / 任务队列 / 骨架与配方，都能在没有
MCP、HTTP、网络、Codex 的情况下单独 import 和测试；不得 import adapters / shell，
需要壳层信息时用参数注入。
"""

# Message catalogs for this layer (see studio/i18n.py): importing them registers
# the `<module>.<meaning>` codes that EditorError.coded() / render() look up.
from studio.core import messages as _messages  # noqa: E402,F401 - uploads, editor, materials, history, ...
from studio.core import messages_cli as _messages_cli  # noqa: E402,F401 - python -m studio.core
from studio.core import messages_head_shell as _messages_head_shell  # noqa: E402,F401 - head_shell*, task_recipe_progress
from studio.core import messages_observation as _messages_observation  # noqa: E402,F401 - observation*, print_state
from studio.core import messages_projects as _messages_projects  # noqa: E402,F401 - projects, recipes
from studio.core import messages_scene as _messages_scene  # noqa: E402,F401 - scene_assets, city, motion
from studio.core import messages_tasks as _messages_tasks  # noqa: E402,F401 - tasks, task_*, blender_catalog
from studio.core import messages_workspaces as _messages_workspaces  # noqa: E402,F401 - workspaces
