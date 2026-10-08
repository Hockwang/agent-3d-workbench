[简体中文](zh-CN/API_SETTINGS_ENTRY.md)

# API settings entry

The workbench navigation includes **API settings**, available from model editing, motion editing, tasks, observation, and print preparation. The task form retains its API settings button. Both entry points open the same connection dialog, and saving a connection refreshes the task provider options.

Service descriptions use protocol or provider names rather than organization-specific wording. The Seed3D template is labelled **Chat Completions-compatible gateway**. Existing custom connection titles are user data and are not overwritten by an update.

Implementation: `studio/web/workspace.js` owns the shared dialog; `tasks.js` reuses it and refreshes providers. The button is hidden for transports without service management. The packaged MCP App is rebuilt alongside the source.

Changes to backend message catalogs require a new backend process to take effect. Restart or reconnect the plugin when an existing process still shows an old template label.
