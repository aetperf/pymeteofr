""" 

service.py contains all tools concerning the wrapper of the Meteo-France web services.

"""
from json import load
from datetime import datetime, timedelta

import xmltodict
import requests
import numpy as np
import pandas as pd


class Fetcher:
    """ 
    Main class for the web service wrapper.
    """

    def __init__(self, token=None):
        self.token = None
        if token is not None:
            self.token = token

        self._WCS_version = "2.0.1"  # The only supported version

    def fetch_token(self, username=None, password=None, credentials_file_path=None):
        """ 
        Fetch the service token from Meteo-France.
        """

        if credentials_file_path is None:
            if (username is None) or (password is None):
                raise AttributeError(f"both username and password should be given.")
        else:
            username, password = self._load_json_credentials(credentials_file_path)

        if (not isinstance(username, str)) or (not isinstance(password, str)):
            raise TypeError("username and password should be strings")

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

        xmlData = r.content.decode("utf-8")
        d = xmltodict.parse(xmlData, process_namespaces=True)
        self.token = d["http://ws.apache.org/ns/synapse:Token"]
        assert self.token[:2] == "__"
        assert self.token[-2:] == "__"

    def select_product(
        self, dataset: str = "arome", area: str = "france", accuracy: float = 0.01
    ):
        """ 
        Select a weather product: model (AROME, ARPEGE, ...), 
        area coverage (France, Europe, ...), accuracy (0.5, 0.01, ...).
        """
        self._build_base_url(dataset, area, accuracy)
        self._get_capabilities()  # refresh the list of available data

    def list_titles(self):
        """ 
        Give the list of titles (fields) available on the web service for the
        chosen product. 

        Notes
        -----
        We only select titles that are avaible on a 1H-based frequency. Other 
        titles are excluded.
        """
        return list(np.sort(self._capa_1H.Title.unique()))

    def set_title(
        self, title: str = "Temperature at specified height level above ground"
    ):
        """ 
        Set the Title (field) that is requested.
        """
        if title in list(np.sort(self._capa_1H.Title.unique())):
            self.title = title
        else:
            raise ValueError(f"title '{title}' not found")

    def list_available_run_times(self, title=""):
        """ 
        Return a list of run times available on the web service for the
        chosen product/title.
        """

        if len(title) > 0:
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
    ):
        """
        Specify a CoverageId, which is a combination of Title and 
        run_time. 
        """
        self.set_title(title)
        self._get_coverage_id(run_time)

    def update(self):
        """ 
        Refresh the list of available data from the web services, 
        i.e. latest run time.
        """
        self._get_capabilities()

    # ==========

    def _load_json_credentials(self, file_path):
        # Loads username and password from a json file.
        with open(file_path) as json_file:
            creds = load(json_file)
        return creds["username"], creds["password"]

    def _build_base_url(
        self, dataset: str = "arome", area: str = "france", accuracy: float = 0.01,
    ):
        dataset = dataset.lower()
        area = area.lower()
        service_type = "wcs"

        # checks if the requested service is found
        self._url_base = ServiceOptionsChecker(
            dataset=dataset, area=area, accuracy=accuracy, service_type=service_type,
        ).get_url_base()

        # add token to base url
        self._url_base = self._url_base.replace("VOTRE_CLE", self.token)

    def _get_capabilities(self):

        url = (
            self._url_base
            + f"SERVICE=WCS&REQUEST=GetCapabilities&version={self._WCS_version}&Language=eng"
        )
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

    def _get_coverage_id(self, run_time: str = "latest"):
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

    # def _check_coords_in_domain(self, lon, lat):
    #     LON_MIN = -8.0
    #     LON_MAX = 12.0
    #     LAT_MIN = 38.0
    #     LAT_MAX = 53.0
    #     if (lon < LON_MIN) or (lon > LON_MAX) or (lat < LAT_MIN) or (lat > LAT_MAX):
    #         raise AttributeError(f"point ({lon}, {lat}) is outside the model domain")

    # def set_poi(self, lon, lat):
    #     """ Set a point of interest from coords.

    #         Note : coords are expressed in WGS84 (EPSG:4326) CRS.
    #     """

    #     if (not isinstance(lon, float)) or (not isinstance(lat, float)):
    #         raise TypeError("lon and lat coordinates should be floats")
    #     self._check_coords_in_domain(lon, lat)
    #     self.poi = {"lon": lon, "lat": lat}
    #     margin = 0.02
    #     self.set_bboxoi(lon - margin, lon + margin, lat - margin, lat + margin)

    # def set_bboxoi(self, lon_min, lon_max, lat_min, lat_max):
    #     """ Set a bounding box of interest from corners coords.

    #         Note : coords are expressed in WGS84 (EPSG:4326) CRS.
    #     """

    #     if (
    #         (not isinstance(lon_min, float))
    #         or (not isinstance(lon_max, float) or not isinstance(lat_min, float))
    #         or (not isinstance(lat_max, float))
    #     ):
    #         raise TypeError("lon and lat coordinates should be floats")
    #     if (lon_min >= lon_max) or (lat_min >= lat_max):
    #         raise AttributeError("min coord should be smaller than max")
    #     self._check_coords_in_domain(lon_min, lat_min)
    #     self._check_coords_in_domain(lon_max, lat_max)
    #     self.bbox = {
    #         "lon_min": int(np.floor(lon_min)),
    #         "lat_min": int(np.floor(lat_min)),
    #         "lon_max": int(np.ceil(lon_max)),
    #         "lat_max": int(np.ceil(lat_max)),
    #     }

    # def create_url_arome_001(self, field="temperature", hours=2):

    #     # run_time_iso = run_time.isoformat()
    #     end_time = datetime.utcnow() + timedelta(hours=hours)
    #     end_time_iso = end_time.isoformat()

    #     if field == "temperature":
    #         url = f"https://geoservices.meteofrance.fr/api/{self.token}/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS?SERVICE=WCS&VERSION={self._WCS_version}&REQUEST=GetCoverage&format=image/tiff&coverageId=TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND__&subset=time({end_time_iso}Z)&subset=lat({str(self.bbox['lat_min'])},{str(self.bbox['lat_max'])})&subset=long({str(self.bbox['lon_min'])},{str(self.bbox['lon_max'])})&subset=height(2)"

    #     return url


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
    ):

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
