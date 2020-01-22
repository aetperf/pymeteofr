"""Main module."""

class Fetcher:
    """ Fetching weather data from Inspire web services (Meteo-France).
    """
    def __init__(self, username, password):
        self.username = username
        self.password = password
        print(username, password)
