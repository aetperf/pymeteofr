"""Main module."""
import json


def load_json_credentials(file_path):
    """ Loads username and password from a json file.
	"""
    with open("inspire_credentials.json") as json_file:
        creds = json.load(json_file)
    assert "username" in creds
    assert "password" in creds
    return creds


class Fetcher:
    """ Fetching weather data from Inspire web services (Meteo-France).
    """

    def __init__(self, username, password):
        self.username = username
        self.password = password
