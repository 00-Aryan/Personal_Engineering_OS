.PHONY: install test run lint clean status config

install:
	python install.py

test:
	UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30

run:
	uv run --no-sync projectos run

lint:
	uv run --no-sync python -m py_compile core/*.py agents/*.py

clean:
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf .projectos_state/traces.jsonl
	rm -rf .projectos_state/decisions.jsonl

status:
	uv run --no-sync projectos status

config:
	uv run --no-sync projectos config show
