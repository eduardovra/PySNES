from setuptools import setup, Extension
from Cython.Build import cythonize
import glob

# Find all .py files in pysnes directory recursively (excluding __init__.py for now)
py_files = glob.glob("pysnes/**/*.py", recursive=True)
py_files = [f for f in py_files if not f.endswith("__init__.py")]  # Exclude __init__.py

extensions = []
for py_file in py_files:
    module_name = py_file.replace("/", ".").replace(".py", "")
    extensions.append(Extension(
        name=module_name,
        sources=[py_file],
        libraries=["SDL2"],
        include_dirs=["/usr/include/SDL2/"],
    ))

setup(
    ext_modules=cythonize(
        extensions,
        annotate=False,  # enables generation of the html annotation file
    ),
    packages=["pysnes"],
)
