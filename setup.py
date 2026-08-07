import glob
import multiprocessing
import pathlib

from Cython.Build import cythonize
from setuptools import Extension, setup

# Modules excluded from Cython compilation: PyPy JIT cannot trace through
# compiled C extension call boundaries. The CPU/bus hot path (cpu.py, bus.py,
# dma.py, wdc65816/*.py) calls across module boundaries on every instruction
# cycle, so compiling them creates JIT trace breaks and causes a severe
# performance regression. These are left as pure Python for PyPy to JIT
# natively.
EXCLUDE_FROM_CYTHON = {
    "pysnes/cpu/cpu.py",
    "pysnes/cpu/dma.py",
    "pysnes/bus/bus.py",
}

py_files = glob.glob("pysnes/**/*.py", recursive=True)
py_files = [
    f
    for f in py_files
    if not f.endswith("__init__.py")
    and not pathlib.Path(f).name.startswith("test_")
    and pathlib.Path(f).name != "conftest.py"
    and f not in EXCLUDE_FROM_CYTHON
    and not f.startswith("pysnes/cpu/wdc65816/")
]

extensions = []
for py_file in py_files:
    module_name = (
        pathlib.Path(py_file).with_suffix("").as_posix().replace("/", ".")
    )
    extensions.append(
        Extension(
            name=module_name,
            sources=[py_file],
            libraries=["SDL2"],
            include_dirs=["/usr/include/SDL2/"],
        )
    )

setup(
    ext_modules=cythonize(
        extensions,
        nthreads=multiprocessing.cpu_count(),
        cache=True,
        annotate=True,
        compiler_directives={},
    ),
    packages=["pysnes"],
)
