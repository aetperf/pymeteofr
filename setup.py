"""The setup script."""

from setuptools import setup, find_packages

with open("README.md", "r") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst", "r") as history_file:
    history = history_file.read()

requirements = [
    "requests",
    "matplotlib",
    "numpy",
    "pandas",
    "xmltodict",
    "rasterio",
    "scipy",
    "xarray",
    "imageio",
    "colorcet",
    "geopandas",
    "descartes",
    "pygifsicle",
]

setup_requirements = []

test_requirements = []

setup(
    author="Francois Pacull",
    author_email="francois.pacull@architecture-performance.fr",
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    description="Python wrapper for the meteo-france web services.",
    long_description_content_type="text/markdown",
    install_requires=requirements,
    license="MIT license",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="pymeteofr",
    name="pymeteofr",
    packages=find_packages(include=["pymeteofr", "pymeteofr.*"]),
    setup_requires=setup_requirements,
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/aetperf/pymeteofr",
    version="0.1.0",
    zip_safe=False,
)
