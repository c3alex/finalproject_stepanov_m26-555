install:
	uv sync

project:
	uv run project

build:
	uv build

publish:
	uv publish --dry-run

package-install:
	uv tool install --force dist/*.whl

lint:
	uv run ruff check .

format:
	uv run ruff format .

.PHONY: install project build publish package-install lint format
