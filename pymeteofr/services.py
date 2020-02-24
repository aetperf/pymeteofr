""" 

service.py contains all tools concerning the wrapper of the Meteo-France web services.


Notes
-----
- we only select predicted weather fields that are available on a 1H-based 
frequency
- all times are UTC
- coords are expressed in WGS84 (EPSG:4326) CRS
"""
from json import load
from datetime import datetime, timedelta
from typing import List

import xmltodict
import requests
import numpy as np
import pandas as pd


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
        self, dataset: str = "arome", area: str = "france", accuracy: float = 0.01
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
        self._get_coverage_id(run_time)
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
        describer.get_description()

        # bounding box of the area covered
        self.max_bbox = describer.max_bbox

        # available time stamps
        start = datetime.strptime(describer.beginPosition, "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(describer.endPosition, "%Y-%m-%dT%H:%M:%SZ")
        self.dts = pd.date_range(start=start, end=end, freq="H")
        self.dts_iso = [dt.isoformat() + "Z" for dt in self.dts]

    def set_complete_run_time(self, horizon: int = 24) -> None:
        """
        Look for the latest available run time that can cover the horizon, e.g.
        the next 24 hours.
        """
        if not self._check_next_hours_availability(horizon):
            run_times = self.list_available_run_times()
            self.run_time = run_times[-2]
            print("Switched to before last available run time")
            self._get_coverage_id(self.run_time)
        else:
            print("Kept the last available run time")

    def set_bbox_of_interest(
        self, lon_min: float, lat_min: float, lon_max: float, lat_max: float
    ):
        """ 
        Set a bounding box of interest from corners coords.
        """
        if (lon_min >= lon_max) or (lat_min >= lat_max):
            raise AttributeError(
                f"min coord ({lon_min}, {lat_min})"
                + f" should be smaller than max ({lon_max}, {lat_max})"
            )
        self._check_coords_in_domain(lon_min, lat_min)
        self._check_coords_in_domain(lon_max, lat_max)
        self.bbox = (lon_min, lat_min, lon_max, lat_max)
        self._create_an_integer_bbox(lon_min, lat_min, lon_max, lat_max)

    # def fetch_

    # ==========

    def _load_json_credentials(self, file_path: str = "") -> (str, str):
        # Loads username and password from a json file.
        with open(file_path) as json_file:
            creds = load(json_file)
        return creds["username"], creds["password"]

    def _build_base_url(
        self, dataset: str = "arome", area: str = "france", accuracy: float = 0.01,
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
            + f"SERVICE=WCS&REQUEST=GetCapabilities&version={self._WCS_version}&Language=eng"
        )
        print("-- GetCapabilities request --")
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

        self._capa_1H = capa[capa.run_time_suffix == ""].copy(deep=True)
        self._capa_1H.drop("run_time_suffix", axis=1, inplace=True)
        self._capa_1H["run_time"] = self._capa_1H.CoverageId.map(
            lambda s: s.split("___")[-1].split("Z")[0].strip()
        )
        self._capa_1H.run_time = self._capa_1H.run_time.map(
            lambda s: datetime.strptime(s, "%Y-%m-%dT%H.%M.%S")
        )

    def _get_coverage_id(self, run_time: str = "latest") -> None:
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
            (lon < self.max_bbox[0])
            or (lon > self.max_bbox[2])
            or (lat < self.max_bbox[1])
            or (lat > self.max_bbox[3])
        ):
            raise ValueError(f"Point ({lon}, {lat}) is outside the model domain")

    def _create_an_integer_bbox(
        self, lon_min: float, lat_min: float, lon_max: float, lat_max: float
    ):
        lon_min_int = int(np.floor(lon_min))
        if float(lon_min_int) < self.max_bbox[0]:
            raise ValueError("Left bounding box side is outside covered area")
        lat_min_int = int(np.floor(lat_min))
        if float(lat_min_int) < self.max_bbox[1]:
            raise ValueError("Lower bounding box side is outside covered area")
        lon_max_int = int(np.ceil(lon_max))
        if float(lon_max_int) > self.max_bbox[2]:
            raise ValueError("Right bounding box side is outside covered area")
        lat_max_int = int(np.ceil(lat_max))
        if float(lat_max_int) > self.max_bbox[3]:
            raise ValueError("Upper bounding box side is outside covered area")

        self._bbox_int = (lon_min_int, lat_min_int, lon_max_int, lat_max_int)

    # def set_poi(self, lon: float, lat: float) -> None:
    #     """ Set a point of interest from coords.
    #     """
    #     self._check_coords_in_domain(lon, lat)
    #     self.poi = {"lon": lon, "lat": lat}
    #     margin = 0.02
    #     self.set_bboxoi(lon - margin, lon + margin, lat - margin, lat + margin)

    # def create_url_arome_001(self, field="temperature", hours=2):

    #     # run_time_iso = run_time.isoformat()
    #     end_time = datetime.utcnow() + timedelta(hours=hours)
    #     end_time_iso = end_time.isoformat()

    #     if field == "temperature":
    #         url = f"https://geoservices.meteofrance.fr/api/{self.token}/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS?SERVICE=WCS&VERSION={self._WCS_version}&REQUEST=GetCoverage&format=image/tiff&coverageId=TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND__&subset=time({end_time_iso}Z)&subset=lat({str(self.bbox['lat_min'])},{str(self.bbox['lat_max'])})&subset=long({str(self.bbox['lon_min'])},{str(self.bbox['lon_max'])})&subset=height(2)"

    #     return url


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

    def get_description(self) -> None:
        """
        Retrieve the information found in the result of the DescribeCoverage 
        request.
        """
        url = self._build_url()
        print("-- DescribeCoverage request --")
        r = requests.get(url)
        xmlData = r.content.decode("utf-8")
        d = xmltodict.parse(xmlData, process_namespaces=True)
        description = d["http://www.opengis.net/wcs/2.0:CoverageDescriptions"][
            "http://www.opengis.net/wcs/2.0:CoverageDescription"
        ]["http://www.opengis.net/gml/3.2:boundedBy"][
            "http://www.opengis.net/gml/3.2:EnvelopeWithTimePeriod"
        ]
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
    OPTIONS = [
        {
            "dataset": "arpege",
            "area": "world",
            "accuracy": 0.5,
            "url_base": "https://geoservices.meteofrance.fr/api/VOTRE_CLE/MF-NWP-GLOBAL-ARPEGE-05-GLOBE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arpege",
            "area": "europe",
            "accuracy": 0.1,
            "url_base": "https://geoservices.meteofrance.fr/api/VOTRE_CLE/MF-NWP-GLOBAL-ARPEGE-01-EUROPE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "france",
            "accuracy": 0.025,
            "url_base": "https://geoservices.meteofrance.fr/api/VOTRE_CLE/MF-NWP-HIGHRES-AROME-0025-FRANCE-WCS?",
            "service_type": "wcs",
        },
        {
            "dataset": "arome",
            "area": "france",
            "accuracy": 0.01,
            "url_base": "https://geoservices.meteofrance.fr/api/VOTRE_CLE/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS?",
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
            self.choice = self.choice[self.choice.area == area]

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
