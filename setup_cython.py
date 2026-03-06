"""Build Cython extensions: python setup_cython.py build_ext --inplace"""
from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        "core/fast_collisions.pyx",
        compiler_directives={
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
    ),
)
