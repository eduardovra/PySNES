from setuptools import setup, Extension
from Cython.Build import cythonize

setup(
    # ext_modules = cythonize("pysnes/**.py"),
    # ext_modules=[Extension("", [""])],  # Added to trigger a binary wheel
    ext_modules=[
        Extension(
            name="pysnes.pysnes",  # This will create pysnes/pysnes.so
            sources=["pysnes/pysnes.py"],
            libraries=["SDL2"],  # Link against SDL2 library
            # Add include_dirs if SDL2 headers are not in standard locations
            include_dirs=["/usr/include/SDL2/"],
            # Add library_dirs if SDL2 libraries are not in standard locations
            # library_dirs=["/path/to/SDL2/lib"],
        ),
        # Add more extensions for other modules if needed
        # Extension(
        #     name="pysnes.cpu.cpu",
        #     sources=["pysnes/cpu/cpu.py"],
        # ),
    ],
    packages=["pysnes"],
)
