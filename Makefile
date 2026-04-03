.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# =============================================================================
# Development
# =============================================================================

.PHONY: format
format: ## Apply code formatting
	@uv run ruff format .

.PHONY: lint
lint: ## Check linting and formatting
	@uv run ruff check .
	@uv run ruff format --check .

.PHONY: pysmelly
pysmelly: ## Run pysmelly code smell analysis
	@pysmelly src/

# =============================================================================
# Testing
# =============================================================================

.PHONY: test
test: ## Run tests
	@uv run pytest

.PHONY: test-cov
test-cov: ## Run tests with coverage
	@uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=70

# =============================================================================
# Security
# =============================================================================

.PHONY: security
security: security-bandit security-deps ## Run all security checks
	@echo "=== Security Checks Complete ==="

.PHONY: security-bandit
security-bandit: ## Run bandit security linter
	@uv run bandit -c pyproject.toml -r src/ -ll

.PHONY: security-deps
security-deps: ## Check dependency vulnerabilities
	@uv run pip-audit

# =============================================================================
# Quality
# =============================================================================

.PHONY: check
check: lint test security ## All checks

# =============================================================================
# Documentation
# =============================================================================

.PHONY: format-docs
format-docs: ## Format markdown files
	@command -v mdformat >/dev/null 2>&1 || { echo "Error: mdformat not found. Install with: uv tool install mdformat --with mdformat-gfm"; exit 1; }
	@mdformat .

# =============================================================================
# Cleanup
# =============================================================================

.PHONY: clean
clean: ## Remove artifacts
	rm -rf dist build .pytest_cache htmlcov .coverage
