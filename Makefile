# Developer entry points. Every target is safe to run on a fresh clone after `make install`.
# Python runs through uv (`uv run`), JavaScript through npm; nothing here touches ~/.print-prep.

RUFF := uvx ruff@0.14.3

.PHONY: help install test test-py test-js lint format build dev stop tools-doc

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install Python (uv, locked) and Node dependencies
	uv sync --locked
	npm ci
	# To also register this as a Codex plugin: `./install.sh` (macOS/Linux), or on
	# Windows/any other OS follow "Manual install" in docs/CONFIGURATION.md.

test: test-py test-js ## Run the whole test suite

test-py: ## Python tests (pytest; Bambu Studio / Blender dependent tests skip when absent)
	uv run pytest -q

test-js: ## JavaScript tests (node --test)
	npm test

lint: ## Lint Python with ruff (configuration in pyproject.toml)
	$(RUFF) check .

format: ## Format Python with ruff (repo-wide pass is planned; run on the files you touch)
	$(RUFF) format .

build: ## Rebuild the MCP App bundles under studio/app/dist and vendored UI assets
	npm run build:app

dev: ## Start the local HTTP backend without Codex and print its URL (state under PRINT_PREP_HOME)
	uv run python scripts/studio.py start
	@echo "Open the URL above in a browser; append ?mock=1 to run the UI without a backend."

stop: ## Stop the local HTTP backend started by `make dev`
	uv run python scripts/studio.py stop

tools-doc: ## Regenerate docs/TOOLS.md from the MCP tool schemas
	uv run python scripts/gen_tool_reference.py
