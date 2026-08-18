.PHONY: install install-all test lint format synthetic-smoke clean

install:
	python -m pip install -e .

install-all:
	python -m pip install -e ".[all,dev]"

test:
	pytest -q

lint:
	ruff check src tests scripts
	python -m compileall -q src scripts tests

format:
	ruff format src tests scripts
	ruff check --fix src tests scripts

synthetic-smoke:
	rm -rf _demo
	weldtool synthetic --output _demo/raw
	weldtool init --dataset-root _demo/raw --workspace _demo/workspace
	weldtool scan --workspace _demo/workspace --workers 2 --probe light
	weldtool validate --workspace _demo/workspace
	weldtool stats --workspace _demo/workspace

clean:
	rm -rf _demo .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
