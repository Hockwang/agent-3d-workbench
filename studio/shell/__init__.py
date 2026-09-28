"""studio.shell: the outward-facing Codex / HTTP shell.

This layer owns every external contract: the MCP server and its tool schemas
(the ``studio_*`` tool names and ``ui://`` resource URIs), the routes of the
local HTTP server, and the Codex thread bridge. It may import anything else in
the package (core and adapters) because it is the only place allowed to know
how internal capabilities are exposed; core and adapters never import it.
Renaming a tool, a route or a URI here is an API change for every client.

中文：对外的 Codex / HTTP 外壳层，拥有全部对外契约（MCP 工具 schema、`studio_*`
工具名、`ui://` URI、HTTP 路由、Codex 线程桥接）；可 import core / adapters，
反向不行。
"""

from studio.shell import messages as _messages  # noqa: F401 - registers studio.shell.* i18n message codes
