"""studio.adapters: the hosted-service capability layer (C).

Clients for third-party services that need an API key and the network
(Lux3D, Hunyuan 3D, Seed3D, Meshy, Tripo, the assembly service) plus the
``services.py`` facade that presents them uniformly. Every adapter is optional:
without a key the rest of the workbench keeps working.

May import ``studio.core.*``. Must NOT import ``studio.shell.*`` (the MCP tool
protocol, HTTP routes and the Codex bridge do not belong here);
tests/test_layering.py enforces this.

中文：对接托管第三方服务的能力层（C）。封装需要 API key、走网络的客户端和统一的
services.py 门面；可 import studio.core，不得 import studio.shell。
"""

# Message catalogs for this layer (see studio/i18n.py): importing them registers
# the `<module>.<meaning>` codes that EditorError.coded() / render() look up.
from studio.adapters import messages as _messages  # noqa: E402,F401 - lux3d_*, seed3d, meshy, tripo, services, service_connections
from studio.adapters import messages_assembly as _messages_assembly  # noqa: E402,F401 - hunyuan, assembly, evaluation, platform_preview, transport, registry, service_diagnostics
