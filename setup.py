from setuptools import setup, Extension
from Cython.Build import cythonize
import glob
import pathlib

# Find all .py files in pysnes directory recursively (excluding __init__.py for now)
py_files = glob.glob("pysnes/**/*.py", recursive=True)
py_files = [f for f in py_files if not f.endswith("__init__.py")]  # Exclude __init__.py

extensions = []
for py_file in py_files:
    pathlib_path = pathlib.Path(py_file)
    module_name = pathlib_path.with_suffix("").as_posix().replace("/", ".")
    extensions.append(Extension(
        name=module_name,
        sources=[py_file],
        libraries=["SDL2"],
        include_dirs=["/usr/include/SDL2/"],
    ))

extensions = [
    Extension(
        name="pysnes",
        sources=py_files,
        libraries=["SDL2"],
        include_dirs=["/usr/include/SDL2/"],
    )
]

import multiprocessing

setup(
    ext_modules=cythonize(
        extensions,
        nthreads=multiprocessing.cpu_count(),
        cache=True,
        annotate=True,  # enables generation of the html annotation file
    ),
    packages=["pysnes"],
)
