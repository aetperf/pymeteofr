"""Main module."""
import json


def load_json_credentials(file_path):
    """ Loads username and password from a json file.
    """
    with open("inspire_credentials.json") as json_file:
        creds = json.load(json_file)
    credentials = {}
    credentials["username"] = creds["username"]
    credentials["password"] = creds["password"]
    return credentials


class Fetcher:
    """ Fetching weather data from Inspire web services (Meteo-France).
    """

    def __init__(self, username=None, password=None, credentials_file_path=None):
        if credentials_file_path is None:
            self.username = username
            self.password = password
        else:
            credentials = load_json_credentials(credentials_file_path)
            self.username = credentials["username"]
            self.password = credentials["password"]
