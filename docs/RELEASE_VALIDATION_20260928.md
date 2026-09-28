# Public snapshot verification — 2026-09-28

This is the initial MIT-licensed `Hockwang/agent-3d-workbench` source snapshot.
The development repository and its Git history remain separate.

## What was checked locally

- Full Python suite on macOS: **703 passed, 2 skipped**. The skipped tests are
  reported by pytest; a local pass does not certify other desktop platforms.
- A separate checkout installed dependencies with `uv sync --locked` and `npm ci`.
- JavaScript suite in that checkout: **139 passed**.
- Python lint: `uvx ruff@0.14.3 check .` passed.
- `npm run build:app` rebuilt the UI, codecs, motion worker and delivery templates.
- Both README files' relative links resolve and their JSON examples parse.
- `examples/demo/verify_tutorial.py` passed through a real stdio MCP subprocess
  in both the development checkout and the separate checkout. It imported five
  parts, scaled only the handle from approximately 14 × 8 × 23 mm to
  21 × 12 × 34.5 mm, undid the edit, exported GLB, saved a project archive and
  reopened five parts. No hosted generation service was used.
- The published file set excludes local MCP configuration, credentials, virtual
  environments, workspace state and user model outputs. Targeted secret, internal
  endpoint and private-path scans returned no hits. This is a bounded scan, not
  a claim of exhaustive security auditing.

## Scope of the evidence

The automated tutorial checks the MCP/model workflow, not native desktop button
clicks, artistic quality, physical manufacturing or wearability. Prior UI component
verification is described in the UI guide. Blender, Bambu Studio and AI host access
are optional prerequisites for the workflows that use them, not bundled services.

## Hosted CI template

The publishing credential does not have GitHub's `workflow` scope, so the first
push containing `.github/workflows/ci.yml` was rejected. No branch was uploaded by
that attempt. The same configuration is supplied as `docs/ci.github-actions.yml`;
GitHub Actions is not enabled by this release and no hosted CI pass is claimed.

To enable CI with an appropriately authorized GitHub login, copy the template to
`.github/workflows/ci.yml`, commit and push it. It runs Linux Python tests, the
MCP tutorial replay, JavaScript tests and the frontend build. Keep the explicit
skip behavior for Blender/Bambu Studio checks on runners without those programs.
