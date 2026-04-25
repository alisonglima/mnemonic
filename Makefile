# Mnemonic — Memory Stack
# Personal AI memory MCP gateway
#
# Usage: make <target>

.PHONY: setup test run docker-up docker-down reindex backup lint format help

# Detect sed -i flavour: GNU uses "-i", BSD/macOS uses "-i ''"
SED_I := $(shell sed --version 2>/dev/null | grep -q GNU && echo "-i" || echo "-i ''")

# ── Paths ──────────────────────────────────────────────────────────────
PYTHON   := python3
PIP      := $(PYTHON) -m pip
PKG_DIR  := mcp-memory
SRC      := $(PKG_DIR)/src
TESTS    := $(PKG_DIR)/tests
SCRIPTS  := $(PKG_DIR)/scripts

# ── Default ────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── Development ────────────────────────────────────────────────────────
setup: ## Install dependencies (editable)
	$(PIP) install -e $(PKG_DIR)

test: ## Run unit tests
	PYTHONPATH=$(SRC) $(PYTHON) -m unittest discover -s $(TESTS) -p "test_*.py" -v

run: ## Start MCP server locally (respects MCP_PORT from .env or env)
	@if [ -f .env ]; then set -a; . .env; set +a; fi; \
	PORT=$${MCP_PORT:-8080}; \
	echo "Starting MCP server on 127.0.0.1:$$PORT"; \
	PYTHONPATH=$(SRC) $(PYTHON) -m mcp_memory.main --host 127.0.0.1 --port $$PORT --serve

# ── Docker ─────────────────────────────────────────────────────────────
docker-up: ## Start all services (docker compose)
	docker compose up -d

docker-down: ## Stop all services
	docker compose down

# ── Maintenance ────────────────────────────────────────────────────────
reindex: ## Rebuild all indexes (Qdrant + Obsidian)
	PYTHONPATH=$(SRC) $(PYTHON) $(SCRIPTS)/rebuild_qdrant.py
	PYTHONPATH=$(SRC) $(PYTHON) $(SCRIPTS)/rebuild_obsidian.py

backup: ## Backup SQLite database
	PYTHONPATH=$(SRC) $(PYTHON) $(SCRIPTS)/backup_sqlite.py

# ── Quality (lightweight, no extra dependencies) ───────────────────────
lint: ## Syntax-check Python files (py_compile only — no style/lint rules)
	@echo "Checking Python syntax..."
	@find $(SRC) $(TESTS) $(SCRIPTS) -name '*.py' -exec $(PYTHON) -m py_compile {} + \
		&& echo "OK — no syntax errors"

format: ## Fix trailing whitespace and final newline in Python files
	@echo "Formatting Python files..."
	@COUNT=0; \
	for f in $$(find $(SRC) $(TESTS) $(SCRIPTS) -name '*.py'); do \
		FIXED=0; \
		if grep -Eq '[[:blank:]]+$$' "$$f"; then \
			sed $(SED_I) -E 's/[[:blank:]]+$$//' "$$f"; \
			FIXED=1; \
		fi; \
		if [ -s "$$f" ] && [ "$$(tail -c1 "$$f" | wc -l)" -eq 0 ]; then \
			echo "" >> "$$f"; \
			FIXED=1; \
		fi; \
		if [ $$FIXED -eq 1 ]; then COUNT=$$((COUNT + 1)); echo "  fixed: $$f"; fi; \
	done; \
	if [ $$COUNT -eq 0 ]; then echo "OK — no changes needed"; \
	else echo "Done — $$COUNT file(s) formatted"; fi
