""" Services module.
"""

import json
import xml.etree.ElementTree as et

import requests


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

    def _load_json_credentials(self, file_path):
        """ Loads username and password from a json file.
        """
        with open("inspire_credentials.json") as json_file:
            creds = json.load(json_file)
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
            raise AttributeError(
                f"point ({lon}, {lat}) is outside the model domain"
            )

    def set_poi(self, lon, lat):
        """ Set a point of interest from coords.

            Note: coords are expressed in WGS84 (EPSG:4326) CRS.
        """

        if (not isinstance(lon, float)) or (not isinstance(lat, float)):
            raise TypeError("lon and lat coordinates should be floats")
        self._check_coords_in_domain(lon, lat)
        self.poi = {"lon": lon, "lat": lat}

    def set_bboxoi(self, lon_min, lon_max, lat_min, mat_max):
        """ Set a bounding box of interest from corners coords.

            Note: coords are expressed in WGS84 (EPSG:4326) CRS.
        """

        if (
            (not isinstance(lon_min, float))
            or (not isinstance(lon_max, float) or not isinstance(lat_min, float))
            or (not isinstance(lat_max, float))
        ):
            raise TypeError("lon and lat coordinates should be floats")
        if (lon_min < lon_max) or (lat_min < lat_max):
            raise AttributeError("min coord should be smaller than max")
        self._check_coords_in_domain(lon_min, lat_min)
        self._check_coords_in_domain(lon_max, lat_max)
        self.bbox = {
            "lon_min": lon_min,
            "lat_min": lat_min,
            "lon_max": lon_max,
            "lat_max": lat_max,
        }
