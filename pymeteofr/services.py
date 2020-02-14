""" Services module.
"""

from json import load
import xml.etree.ElementTree as et
from datetime import datetime, timedelta

import requests
import numpy as np


class Fetcher:
    """ Fetching weather data from Inspire web services (Meteo-France).
    """

    def __init__(
        self, username=None, password=None, credentials_file_path=None, token=None
    ):
        """ Note : credentials_file_path is priorily used over username/password.
        """

        if credentials_file_path is None:
            if (username is None) or (password is None):
                raise AttributeError(f"both username and password should be given.")
            self._username = username
            self._password = password
        else:
            credentials = self._load_json_credentials(credentials_file_path)
            self._username = credentials["username"]
            self._password = credentials["password"]

        if (not isinstance(self._username, str)) or (not isinstance(self._password, str)):
            raise TypeError("username and password should be strings")

        if token is None:
            self.fetch_token()
        else:
            self.token = token

        self._WCS_version = '2.0.1'

    def _load_json_credentials(self, file_path):
        """ Loads username and password from a json file.
        """
        with open("inspire_credentials.json") as json_file:
            creds = load(json_file)
        credentials = {}
        credentials["username"] = creds["username"]
        credentials["password"] = creds["password"]
        return credentials

    def fetch_token(self):
        """ Fetch the service token from Meteo-France.
        """

        url = (
            "https://geoservices.meteofrance.fr/"
            + f"services/GetAPIKey?username={self._username}&password={self._password}"
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
            print("OOOOOps: Something is wrong with the request", e)

        xmlData = r.content.decode("utf-8")
        root = et.fromstring(xmlData)
        self.token = root.text

    def _check_coords_in_domain(self, lon, lat):
        LON_MIN = -8.0
        LON_MAX = 12.0
        LAT_MIN = 38.0
        LAT_MAX = 53.0
        if (lon < LON_MIN) or (lon > LON_MAX) or (lat < LAT_MIN) or (lat > LAT_MAX):
            raise AttributeError(f"point ({lon}, {lat}) is outside the model domain")

    def set_poi(self, lon, lat):
        """ Set a point of interest from coords.

            Note : coords are expressed in WGS84 (EPSG:4326) CRS.
        """

        if (not isinstance(lon, float)) or (not isinstance(lat, float)):
            raise TypeError("lon and lat coordinates should be floats")
        self._check_coords_in_domain(lon, lat)
        self.poi = {"lon": lon, "lat": lat}
        margin = 0.02
        self.set_bboxoi(lon - margin, lon + margin, lat - margin, lat + margin)

    def set_bboxoi(self, lon_min, lon_max, lat_min, lat_max):
        """ Set a bounding box of interest from corners coords.

            Note : coords are expressed in WGS84 (EPSG:4326) CRS.
        """

        if (
            (not isinstance(lon_min, float))
            or (not isinstance(lon_max, float) or not isinstance(lat_min, float))
            or (not isinstance(lat_max, float))
        ):
            raise TypeError("lon and lat coordinates should be floats")
        if (lon_min >= lon_max) or (lat_min >= lat_max):
            raise AttributeError("min coord should be smaller than max")
        self._check_coords_in_domain(lon_min, lat_min)
        self._check_coords_in_domain(lon_max, lat_max)
        self.bbox = {
            "lon_min": int(np.floor(lon_min)),
            "lat_min": int(np.floor(lat_min)),
            "lon_max": int(np.ceil(lon_max)),
            "lat_max": int(np.ceil(lat_max)),
        }

    def create_url_arome_001(self,  field="temperature", hours=2):

        # run_time_iso = run_time.isoformat()
        end_time = datetime.utcnow() + timedelta(hours=hours)
        end_time_iso = end_time.isoformat()

        if field == "temperature":
            url = f"https://geoservices.meteofrance.fr/api/{self.token}/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS?SERVICE=WCS&VERSION={self._WCS_version}&REQUEST=GetCoverage&format=image/tiff&coverageId=TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND__&subset=time({end_time_iso}Z)&subset=lat({str(self.bbox['lat_min'])},{str(self.bbox['lat_max'])})&subset=long({str(self.bbox['lon_min'])},{str(self.bbox['lon_max'])})&subset=height(2)"

        return url
