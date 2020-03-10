""" 

service.py contains all tools concerning the wrapper of the Meteo-France web services.


Notes
-----
- we only select predicted weather fields that are available on a 1H-based 
frequency
- all times are UTC
- coords are expressed in WGS84 (EPSG:4326) CRS
"""
import os
from json import load
from datetime import datetime, timedelta
from typing import List
import urllib
from time import sleep
from pathlib import Path

import xmltodict
import requests
import numpy as np
import pandas as pd
import rasterio as rio
import xarray as xr
import matplotlib as mpl
from matplotlib import pyplot as plt
import imageio
from colorcet import palette
import geopandas as gpd
from shapely.geometry import Point, Polygon
from pygifsicle import optimize
from scipy import interpolate

Vector_float = List[float]
Vector_str = List[str]


class Fetcher:
    """ 
    Main class for the web service wrapper.
    """

    def __init__(self, token: str = "") -> None:
        self.token = None
        if token != "":
            self.token = token

        self._WCS_version = "2.0.1"  # The only supported version
        self._proj = "EPSG:4326"  # The only supported projection
        self.compression = "DEFLATE"  # tiff compression : PACKBITS, LZW, JPEG, DEFLATE
        self.max_trials = 20  # maximum number of trials of the same request
        self.sleep_time = 1.0  # seconds to wait before retrying a request
        self._bbox_margin = 0.5  # degrees

        self.bbox = None
        self.pois = None
        self._url_base = ""
        self._CoverageId = ""

    def fetch_token(
        self, username: str = "", password: str = "", credentials_file_path: str = ""
    ) -> None:
        """
        Fetch the service token from Meteo-France.
        """

        if credentials_file_path == "":
            if (username == "") or (password == ""):
                raise AttributeError(f"both username and password should be given.")
        else:
            username, password = self._load_json_credentials(credentials_file_path)

        url = (
            "https://geoservices.meteofrance.fr/"
            + f"services/GetAPIKey?username={username}&password={password}"
        )

        try:
            r = requests.get(url)
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print("Http Error:", e)
        except requests.exceptions.ConnectionError as e:
            print("Error Connecting:", e)
        except requests.exceptions.Timeout as e:
            print("Timeout Error:", e)
        except requests.exceptions.RequestException as e:
            print("Something is wrong with the request", e)

        print("-- GetAPIKey request --")
        xmlData = r.content.decode("utf-8")
        d = xmltodict.parse(xmlData, process_namespaces=True)
        self.token = d["http://ws.apache.org/ns/synapse:Token"]
        assert self.token[:2] == "__"
        assert self.token[-2:] == "__"

    def select_product(
        self, dataset: str = "", area: str = "", accuracy: float = 0.0
    ) -> None:
        """ 
        Select a weather product: model (AROME, ARPEGE, ...), 
        area coverage (France, Europe, ...), accuracy (0.5, 0.01, ...).
        """
        self._build_base_url(dataset, area, accuracy)
        self._get_capabilities()  # refresh the list of available data

    def list_titles(self) -> List[str]:
        """ 
        Give the list of titles (fields) available on the web service for the
        chosen product. 

        Notes
        -----
        We only select titles that are available on a 1H-based frequency. Other 
        titles are excluded.
        """
        return list(np.sort(self._capa_1H.Title.unique()))

    def set_title(
        self, title: str = "Temperature at specified height level above ground"
    ) -> None:
        """ 
        Set the Title (field) that is requested.
        """
        if title in list(np.sort(self._capa_1H.Title.unique())):
            self.title = title
            self.title_with_height = False
            if "at specified height level above ground" in self.title:
                self.title_with_height = True
        else:
            raise ValueError(f"title '{title}' not found")

    def list_available_run_times(self, title="") -> List[str]:
        """ 
        Return a list of run times available on the web service for the
        chosen product/title.
        """

        if title != "":
            self.set_title(title)

        run_times = list(
            np.sort(
                self._capa_1H.loc[self._capa_1H.Title == self.title, "run_time"].values
            )
        )
        run_times = np.datetime_as_string(run_times, timezone="UTC")
        run_times = [dt.split(":")[0] for dt in run_times]
        return run_times

    def select_coverage_id(
        self,
        title: str = "Temperature at specified height level above ground",
        run_time: str = "latest",
    ) -> None:
        """
        Specify a CoverageId, which is a combination of Title and 
        run_time. 
        """
        self.set_title(title)
        self._set_coverage_id(run_time)
        self.run_time = self.CoverageId.split("___")[-1].replace(".", ":")

    def update(self) -> None:
        """ 
        Refresh the list of available data from the web services, 
        i.e. latest run time.
        """
        self._get_capabilities()

    def describe(self):
        """
        Get spatial and temporal information about the selected CoverageId
        """
        describer = Describer(self._url_base, self.CoverageId, self._WCS_version)
        describer.get_description(self.max_trials, self.sleep_time)

        # bounding box of the area covered
        self.max_bbox = describer.max_bbox

        # available time stamps
        start = datetime.strptime(describer.beginPosition, "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(describer.endPosition, "%Y-%m-%dT%H:%M:%SZ")
        self.dts = pd.date_range(start=start, end=end, freq="H")
        self.dts_iso = [dt.isoformat() + "Z" for dt in self.dts]

    def check_run_time(self, horizon: int = 24) -> None:
        """
        Look for the latest available run time that can cover the horizon, e.g.
        the next 24 hours.
        """
        self.describe()
        idx = -1
        while not self._check_next_hours_availability(horizon):
            run_times = self.list_available_run_times()
            idx -= 1
            self.run_time = run_times[idx]
            print(f"Switched to previous (Python index: {idx}) run time")
            self._set_coverage_id(self.run_time)
            self.describe()

    def set_bbox_of_interest(
        self, lon_min: float, lat_min: float, lon_max: float, lat_max: float
    ) -> None:
        """ 
        Set a bounding box of interest from corners coords.
        """

        lon_min = self._convert_longitude(lon_min)
        lon_max = self._convert_longitude(lon_max)

        if (lon_min >= lon_max) or (lat_min >= lat_max):
            raise ValueError(
                f"min coord ({lon_min}, {lat_min})"
                + f" should be smaller than max ({lon_max}, {lat_max})"
            )
        self._check_coords_in_domain(lon_min, lat_min)
        self._check_coords_in_domain(lon_max, lat_max)
        self.bbox = (lon_min, lat_min, lon_max, lat_max)

    def create_3D_array(self) -> None:
        """
        Loop over the requested dts, fetch the data and gather everything into a xarray.
        """

        arrays = []
        meta_data = {}

        got_grid = False
        for dt in self.requested_dts:

            url = self._create_get_coverage_url(dt)

            valid_data = False
            trial = 0
            while (not valid_data) & (trial < self.max_trials):
                fetched_dt = False
                trial += 1
                print(f"-- GetCoverage request {dt} --")
                try:
                    r = urllib.request.urlopen(url)
                    fetched_dt = True
                except:
                    sleep(self.sleep_time)
                    while (not fetched_dt) & (trial < self.max_trials):
                        trial += 1
                        print(f"-- GetCoverage request {dt} --")
                        try:
                            r = urllib.request.urlopen(url)
                            fetched_dt = True
                        except:
                            sleep(self.sleep_time)
                try:
                    with rio.open(r) as dataset:
                        if not got_grid:
                            meta_data["width"] = dataset.width
                            meta_data["height"] = dataset.height
                            meta_data["bounds"] = dataset.bounds
                        arrays.append(dataset.read(1)[::-1, :])
                        valid_data = True
                except:
                    pass
        array = np.dstack(arrays)

        dts = [datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ") for dt in self.requested_dts]
        x = np.linspace(
            meta_data["bounds"].left, meta_data["bounds"].right, meta_data["width"]
        )
        y = np.linspace(
            meta_data["bounds"].bottom, meta_data["bounds"].top, meta_data["height"]
        )
        self.data = xr.DataArray(
            array, dims=["y", "x", "dt"], coords={"x": x, "y": y, "dt": dts},
        )

    def make_movie(
        self,
        n_levels: int = 40,
        cc_cmap: str = "rainbow",
        root_name: str = "movie",
        tmp_dir_name: str = "data",
        dpi: int = 100,
        duration: float = 0.333,
        figsize: (int, int) = (13, 7),
        fontsize: int = 18,
        border_line: bool = False,
        optim: bool = True,
    ) -> None:
        """
        Create an animated gif from currently stored 3D array (self.data).
        """
        # create temp data dir if not exists
        Path(tmp_dir_name).mkdir(parents=True, exist_ok=True)

        # register the colorcet colormap
        cmap = mpl.colors.ListedColormap(palette[cc_cmap], name=cc_cmap)

        # figure text size
        mpl.rcParams.update({"xtick.labelsize": fontsize - 6})
        mpl.rcParams.update({"ytick.labelsize": fontsize - 6})
        mpl.rcParams.update({"axes.labelsize": fontsize})
        mpl.rcParams.update({"axes.titlesize": fontsize})
        mpl.rcParams.update({"font.size": fontsize - 4})

        if border_line:
            world = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres"))
            p1 = Point(self.bbox[0], self.bbox[1])
            p2 = Point(self.bbox[2], self.bbox[1])
            p3 = Point(self.bbox[2], self.bbox[3])
            p4 = Point(self.bbox[0], self.bbox[3])
            np1 = (p1.coords.xy[0][0], p1.coords.xy[1][0])
            np2 = (p2.coords.xy[0][0], p2.coords.xy[1][0])
            np3 = (p3.coords.xy[0][0], p3.coords.xy[1][0])
            np4 = (p4.coords.xy[0][0], p4.coords.xy[1][0])
            bb_polygon = Polygon([np1, np2, np3, np4])
            bbox = gpd.GeoDataFrame(geometry=[bb_polygon])
            bbox.crs = "EPSG:4326"
            borders = gpd.overlay(world, bbox, how="intersection")

        X, Y = np.meshgrid(self.data["x"], self.data["y"])
        array = self.data.values
        mean = np.mean(array[np.where(array < 9999)])
        array = np.where(array == 9999.0, mean, array)
        mini, maxi = np.min(array), np.max(array)
        levels = np.linspace(np.floor(mini), np.ceil(maxi), n_levels)
        file_paths = []
        for i in range(array.shape[2]):
            fig, ax = plt.subplots(figsize=figsize)
            CS = ax.contourf(X, Y, array[:, :, i], levels=levels, cmap=cmap)
            dt_string = np.datetime_as_string(
                self.data["dt"].values[i], unit="h", timezone="UTC"
            )
            cbar = fig.colorbar(CS)
            plt.text(
                x=0.5,
                y=0.95,
                s=dt_string,
                horizontalalignment="center",
                verticalalignment="center",
                transform=ax.transAxes,
                alpha=0.6,
            )
            ax.set_title(self.title)
            ax.set_xlabel("Lon")
            ax.set_ylabel("Lat")
            if border_line:
                borders.geometry.boundary.plot(
                    ax=ax, color=None, edgecolor="k", linewidth=2, alpha=0.15
                )
            file_path = os.path.join(tmp_dir_name, f"{root_name}_{str(i).zfill(2)}.png")
            file_paths.append(file_path)
            plt.savefig(file_path, dpi=dpi)
            plt.close()
        images = []
        for file_path in file_paths:
            images.append(imageio.imread(file_path))
        movie_file_path = os.path.join(tmp_dir_name, root_name + ".gif")
        imageio.mimsave(movie_file_path, images, duration=duration)

        if optim:
            optimize(movie_file_path)

    def set_poi(self, name: str, lon: float, lat: float) -> None:
        """ 
        Set a point of interest from coords.
        """
        self._check_coords_in_domain(lon, lat)
        self.pois = [(name, lon, lat)]

        lon_min = np.max([lon - self._bbox_margin, self.max_bbox[0]])
        lat_min = np.max([lat - self._bbox_margin, self.max_bbox[1]])
        lon_max = np.min([lon + self._bbox_margin, self.max_bbox[2]])
        lat_max = np.min([lat + self._bbox_margin, self.max_bbox[3]])

        self.set_bbox_of_interest(lon_min, lat_min, lon_max, lat_max)

    def set_pois(self, names: Vector_str, lons: Vector_float, lats: Vector_float) -> None:
        """ 
        Set points of interest from coords.
        """
        n_pois = len(lons)

        if (len(lons) != len(lats)) or (len(lons) != len(names)):
            raise ValueError(
                "Input variable lengths do not match : "
                + f"{len(lons)} POI longitude(s)"
                + f"{len(lats)} POI latitude(s)"
                + f"{len(names)} POI names"
            )

        for lon, lat in zip(lons, lats):
            self._check_coords_in_domain(lon, lat)

        self.pois = []
        for name, lon, lat in zip(names, lons, lats):
            self.pois.append((name, lon, lat))

        min_lons = np.min(lons)
        min_lats = np.min(lats)
        max_lons = np.max(lons)
        max_lats = np.max(lats)

        lon_min = np.max([min_lons - self._bbox_margin, self.max_bbox[0]])
        lat_min = np.max([min_lats - self._bbox_margin, self.max_bbox[1]])
        lon_max = np.min([max_lons + self._bbox_margin, self.max_bbox[2]])
        lat_max = np.min([max_lats + self._bbox_margin, self.max_bbox[3]])

        self.set_bbox_of_interest(lon_min, lat_min, lon_max, lat_max)

    def create_time_series(self, interp: str = "quintic") -> None:
        """
        Fetch a 3D array and create a time serie for each POI given.

        interpolation kinds:  linear, cubic, quintic
        """
        self.create_3D_array()
        array = self.data.values

        x = self.data["x"].values
        y = self.data["y"].values

        dts = []
        values = {}
        for item in self.pois:
            name = item[0]
            values[name] = []

        for i in range(array.shape[2]):
            dt = self.data["dt"].values[i]
            dts.append(dt)
            f = interpolate.interp2d(x, y, array[:, :, i], kind=interp)
            for item in self.pois:
                name, lon, lat = item
                val = f(lon, lat)[0]
                values[name].append(val)
        dt_index = pd.date_range(start=dts[0], end=dts[-1], freq="H")

        self.series = pd.DataFrame(values, index=dt_index)

    # ==========

    def _load_json_credentials(self, file_path: str = "") -> (str, str):
        # Loads username and password from a json file.
        with open(file_path) as json_file:
            creds = load(json_file)
        return creds["username"], creds["password"]

    def _build_base_url(
        self, dataset: str = "", area: str = "", accuracy: float = 0.0,
    ) -> None:
        dataset = dataset.lower()
        area = area.lower()
        service_type = "wcs"

        # checks if the requested service is found
        self._url_base = ServiceOptionsChecker(
            dataset=dataset, area=area, accuracy=accuracy, service_type=service_type,
        ).get_url_base()

        # add token to base url
        self._url_base = self._url_base.replace("VOTRE_CLE", self.token)

    def _get_capabilities(self) -> None:

        url = (
            self._url_base
            + f"SERVICE=WCS&REQUEST=GetCapabilities&version={self._WCS_version}"
            + "&Language=eng"
        )
        trial = 0
        while trial < self.max_trials:
            try:
                print("-- GetCapabilities request --")
                trial += 1
                r = requests.get(url)
                xmlData = r.content.decode("utf-8")
                d = xmltodict.parse(xmlData, process_namespaces=True)
                root = d[list(d.keys())[0]]
                capa = pd.DataFrame(
                    root["http://www.opengis.net/wcs/2.0:Contents"][
                        "http://www.opengis.net/wcs/2.0:CoverageSummary"
                    ]
                )
                capa.columns = [col.split(":")[-1] for col in capa.columns]
                capa["run_time_suffix"] = capa.CoverageId.map(
                    lambda s: s.split("___")[-1].split("Z")[-1].strip()
                )
                break
            except KeyError:
                sleep(self.sleep_time)

        self._capa_1H = capa[capa.run_time_suffix == ""].copy(deep=True)
        self._capa_1H.drop("run_time_suffix", axis=1, inplace=True)
        self._capa_1H["run_time"] = self._capa_1H.CoverageId.map(
            lambda s: s.split("___")[-1].split("Z")[0].strip()
        )
        self._capa_1H.run_time = self._capa_1H.run_time.map(
            lambda s: datetime.strptime(s, "%Y-%m-%dT%H.%M.%S")
        )

    def _set_coverage_id(self, run_time: str = "latest") -> None:
        if run_time == "latest":
            self.CoverageId = (
                self._capa_1H.loc[self._capa_1H.Title == self.title]
                .sort_values(by="run_time", ascending=False)
                .iloc[0]
                .CoverageId
            )
        else:
            if run_time not in self.list_available_run_times():
                raise ValueError(f"run time {run_time} not found in available run times")
            self.CoverageId = self._capa_1H.loc[
                (self._capa_1H.Title == self.title) & (self._capa_1H.run_time == run_time)
            ].CoverageId.values[0]

    def _create_next_hours_dts_iso(self, n: int = 24) -> List[str]:
        now = datetime.utcnow()
        next24h = []
        for i in range(n):
            next24h.append(
                datetime(now.year, now.month, now.day, now.hour, 0, 0)
                + timedelta(hours=i + 1)
            )
        next24h = [dt.isoformat() + "Z" for dt in next24h]
        return next24h

    def _check_next_hours_availability(self, n: int = 24) -> bool:
        available_dts = self.dts_iso
        self.requested_dts = self._create_next_hours_dts_iso(n)
        is_available = False
        if len(set(self.requested_dts).difference(set(available_dts))) == 0:
            is_available = True
        return is_available

    def _check_coords_in_domain(self, lon: float, lat: float):
        if (
            (lon <= self.max_bbox[0])
            or (lon >= self.max_bbox[2])
            or (lat <= self.max_bbox[1])
            or (lat >= self.max_bbox[3])
        ):
            raise ValueError(f"Point ({lon}, {lat}) is outside the model domain")

    def _create_get_coverage_url(self, dt: str) -> str:

        url = (
            self._url_base
            + f"SERVICE=WCS&VERSION={self._WCS_version}&REQUEST=GetCoverage"
            + f"&format=image/tiff&geotiff:compression={self.compression}"
            + f"&CRS={self._proj}"
            + f"&coverageId={self.CoverageId}"
            + f"&subset=time({dt})"
        )
        if self.bbox is None:
            self.bbox = self.max_bbox
        url = (
            url
            + f"&subset=long({self.bbox[0]},{self.bbox[2]})"
            + f"&subset=lat({self.bbox[1]},{self.bbox[3]})"
        )
        if self.title_with_height:
            url += "&subset=height(2)"

        return url

    def _convert_longitude(self, lon: float) -> float:
        while lon > 180.0:
            lon -= 360.0
        while lon < -180.0:
            lon += 360.0
        return lon


class Describer:
    def __init__(
        self, url_base: str = "", CoverageId: str = "", WCS_version: str = "2.0.1"
    ) -> None:
        if url_base == "":
            raise ValueError("Please set the base url by selecting a product")
        if CoverageId == "":
            raise ValueError("Please set the CoverageId by selecting a field")
        self._url_base = url_base
        self._CoverageId = CoverageId
        self._WCS_version = WCS_version

    def _build_url(self) -> str:
        url = (
            self._url_base
            + f"SERVICE=WCS&version={self._WCS_version}"
            + f"&REQUEST=DescribeCoverage&CoverageId={self._CoverageId}"
        )
        return url

    def get_description(self, max_trials: int = 20, sleep_time: float = 0.5) -> None:
        """
        Retrieve the information found in the result of the DescribeCoverage 
        request.
        """
        url = self._build_url()

        trial = 0
        while trial < max_trials:
            try:
                print("-- DescribeCoverage request --")
                r = requests.get(url)
                xmlData = r.content.decode("utf-8")
                d = xmltodict.parse(xmlData, process_namespaces=True)
                description = d["http://www.opengis.net/wcs/2.0:CoverageDescriptions"][
                    "http://www.opengis.net/wcs/2.0:CoverageDescription"
                ]["http://www.opengis.net/gml/3.2:boundedBy"][
                    "http://www.opengis.net/gml/3.2:EnvelopeWithTimePeriod"
                ]
                break
            except KeyError:
                sleep(sleep_time)

        self.axisLabels = description["@axisLabels"]
        self.uomLabels = description["@uomLabels"]
        self.srsDimension = description["@srsDimension"]

        self.lowerCorner = description["http://www.opengis.net/gml/3.2:lowerCorner"]
        self.upperCorner = description["http://www.opengis.net/gml/3.2:upperCorner"]

        self.beginPosition = description["http://www.opengis.net/gml/3.2:beginPosition"][
            "#text"
        ]
        self.endPosition = description["http://www.opengis.net/gml/3.2:endPosition"][
            "#text"
        ]

        self.lon_min = float(self.lowerCorner.split(" ")[0])
        self.lat_min = float(self.lowerCorner.split(" ")[1])
        self.lon_max = float(self.upperCorner.split(" ")[0])
        self.lat_max = float(self.upperCorner.split(" ")[1])

        self.max_bbox = (self.lon_min, self.lat_min, self.lon_max, self.lat_max)


class ServiceOptionsChecker:
    """ 
    Check the different WCS options, e.g. dataset, area, accuracy.
    """

    # list of possible options:
    root = "https://geoservices.meteofrance.fr/api/VOTRE_CLE/"
    OPTIONS = [
        {
            "dataset": "arpege",
            "area": "world",
            "accuracy": 0.5,
            "url_base": root + "MF-NWP-GLOBAL-ARPEGE-05-GLOBE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arpege",
            "area": "europe",
            "accuracy": 0.1,
            "url_base": root + "MF-NWP-GLOBAL-ARPEGE-01-EUROPE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "france",
            "accuracy": 0.025,
            "url_base": root + "MF-NWP-HIGHRES-AROME-0025-FRANCE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "france",
            "accuracy": 0.01,
            "url_base": root + "MF-NWP-HIGHRES-AROME-001-FRANCE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "antilles",
            "accuracy": 0.025,
            "url_base": root + "MF-NWP-HIGHRES-AROME-OM-0025-ANTIL-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "guyane",
            "accuracy": 0.025,
            "url_base": root + "MF-NWP-HIGHRES-AROME-OM-0025-GUYANE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "réunion",
            "accuracy": 0.025,
            "url_base": root + "MF-NWP-HIGHRES-AROME-OM-0025-INDIEN-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "nouvelle-calédonie",
            "accuracy": 0.025,
            "url_base": root + "MF-NWP-HIGHRES-AROME-OM-0025-NCALED-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "polynésie",
            "accuracy": 0.025,
            "url_base": root + "MF-NWP-HIGHRES-AROME-OM-0025-POLYN-WCS?",
            "service_type": "wcs",
        },
    ]

    OPTIONS_DF = pd.DataFrame(OPTIONS)

    def __init__(
        self,
        dataset: str = "",
        area: str = "",
        accuracy: float = 0.0,
        service_type: str = "wcs",
    ) -> None:

        self.choice = self.OPTIONS_DF.copy(deep=True)

        if len(service_type) > 0:
            self.choice = self.choice[self.choice.service_type == service_type]

        if len(dataset) > 0:
            self.choice = self.choice[self.choice.dataset == dataset]

        if len(area) > 0:
            self.choice = self.choice[self.choice["area"] == area]

        if accuracy > 0.0:
            self.choice = self.choice[self.choice.accuracy == accuracy]

    def get_url_base(self) -> str:
        """
        Return a base url, if the requested service has been found.
        """

        if len(self.choice) == 0:
            raise ValueError("No service matching the criteria")
        elif len(self.choice) > 1:
            print(self.choice[["dataset", "area", "accuracy", "service_type"]])
            raise ValueError("Several services match the criteria")

        return self.choice["url_base"].values[0]
