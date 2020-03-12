
[![Build Status](https://travis-ci.org/aetperf/pymeteofr.svg?branch=master)](https://travis-ci.org/aetperf/pymeteofr)
[![Documentation Status](https://readthedocs.org/projects/docs/badge/?version=latest)](https://pymeteofr.readthedocs.io/en/latest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-brightgreen.svg)](https://opensource.org/licenses/MIT)
[![Python 3.6](https://img.shields.io/badge/python-3.6+-brightgreen.svg)](https://www.python.org/downloads/release/python-360/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# PyMeteoFr

Python wrapper of the Météo-France web services ([WCS](https://www.ogc.org/standards/wcs) only).

```python
from IPython.display import Image
from pymeteofr import Fetcher

fetcher = Fetcher(token="__xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx__")
fetcher.select_product(dataset='arome', area='polynésie')
fetcher.select_coverage_id("Temperature at specified height level above ground")
fetcher.check_run_time(horizon=24)
fetcher.set_bbox_of_interest(208, -18.5, 212, -16)
fetcher.create_3D_array()
fetcher.make_movie(root_name="tahiti")
Image(filename="./data/tahiti.gif")
```
<p align="center">
  <img width="800" src="tahiti.gif" alt="tahiti.gif">
</p>

## Requirements

[gifsicle](https://www.lcdf.org/gifsicle/) is required for the gif file optimization.


Free software: MIT License
Copyright (c) 2020, Architecture & Performance