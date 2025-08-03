.PHONY: build clean run install test benchmark docs

PY ?= uv run --python pypy@3.10

all: build

build: build_pysnes

build_pysnes:
	@echo "Building PySNES..."
	${PY} setup.py build_ext -j $(shell getconf _NPROCESSORS_ONLN) --inplace

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
	${PY} run_pysnes.py

profile: build
	@echo "Profiling PySNES..."
	${PY} run_pysnes.py --profile
