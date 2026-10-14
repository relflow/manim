.DEFAULT_GOAL := help

.PHONY: help check preview render export-docs
help:
	@echo 'make check | preview | render | export-docs DOCS=/path/to/docs'
check:
	uv run ruff format --check scenes.py tools tests
	uv run ruff check scenes.py tools tests
	uv run pytest
	uv run python -m tools.build --check
	uv run python -m tools.archive --check
preview:
	uv run python -m tools.build all --quality preview --voice silent
render:
	uv run python -m tools.build all --quality production --voice files
export-docs:
	uv run python -m tools.catalog --docs "$(DOCS)"
