.PHONY: build clean run install test benchmark docs

PY ?= --python pypy@3.11

all: build

build: build_pysnes

build_pysnes:
	@echo "Building PySNES..."
	uv run ${PY} setup.py build_ext -j $(shell getconf _NPROCESSORS_ONLN) --inplace

clean:
	@echo "Cleaning..."
	rm -rf pysnes.egg-info
	rm -rf build
	rm -rf dist
	find pysnes/ -type f -name "*.pyo" -delete
	find pysnes/ -type f -name "*.pyc" -delete
	find pysnes/ -type f -name "*.pyd" -delete
	find pysnes/ -type f -name "*.so" -delete
	find pysnes/ -type f -name "*.c" -delete
	find pysnes/ -type f -name "*.h" -delete
	find pysnes/ -type f -name "*.dll" -delete
	find pysnes/ -type f -name "*.lib" -delete
	find pysnes/ -type f -name "*.exp" -delete
	find pysnes/ -type f -name "*.html" -delete
	find pysnes/ -type d -name "__pycache__" -delete
	find . -maxdepth 1 -type f -name "*.so" -delete

run: build
	@echo "Running PySNES..."
	uv run ${PY} pysnes

profile: build
	@echo "Profiling PySNES..."
	uv run ${PY} scripts/run_pysnes.py --profile

tests: build
	@echo "Running tests..."
	uv run ${PY} pytest
