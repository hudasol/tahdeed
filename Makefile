PYTHON ?= python
PBF ?= united_arab_emirates.osm.pbf
DB ?= data/gazetteer.sqlite
MODEL ?= data/models/ranker.npz
IMAGE ?= tahdeed:local

.PHONY: help install test lint format build-data train eval serve docker build-dist clean

help:
	@echo "install     editable install with development tools and pre-commit hooks"
	@echo "test        run the tests with the coverage gate"
	@echo "lint        ruff check, ruff format --check and mypy"
	@echo "format      apply ruff formatting and import sorting"
	@echo "build-data  build the gazetteer from PBF=<osm extract>"
	@echo "train       train and calibrate the ranker"
	@echo "eval        run the evaluation harness"
	@echo "serve       run the API and dashboard on 127.0.0.1:8000"
	@echo "docker      build the Docker image"
	@echo "build-dist  build the sdist and wheel into dist/"

install:
	$(PYTHON) -m pip install -e ".[dev]"
	pre-commit install

test:
	$(PYTHON) -m pytest --cov=tahdeed --cov-fail-under=70

lint:
	ruff check .
	ruff format --check .
	mypy

format:
	ruff check --select I --fix .
	ruff format .

build-data:
	tahdeed build $(PBF) --out $(DB)

train:
	tahdeed train --db $(DB) --out $(MODEL)

eval:
	tahdeed eval --db $(DB) --model $(MODEL)

serve:
	TAHDEED_DB=$(DB) TAHDEED_MODEL=$(MODEL) tahdeed serve

docker:
	docker build -t $(IMAGE) .

build-dist:
	$(PYTHON) -m build

clean:
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache .hypothesis .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
