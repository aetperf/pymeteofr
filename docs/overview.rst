****************
Package overview
****************

**pymeteofr** is a `Python <https://www.python.org>`__ wrapper around the  Météo-France web service. Météo-France is the French national meteorological service. As stated is the documentation of the web service: 

	"The objective of Météo-France web service is to facilitate the access and the consultation of public data in order to make them interoperable with georeferenced data from other Administrations or other sources."

The documentation of the web service can be found `here <https://donneespubliques.meteofrance.fr/client/gfx/utilisateur/File/documentation-webservices-inspire-en.pdf>`_ (pdf file).

The aim of **pymeteofr** is to easily access Météo-France open-source data from a Python application.

**pymeteofr** runs on Python 3.6+. It is a fairly simple package, but uses behind the hoods large and handy libraries such as requests, matplotlib, numpy, pandas, rasterio, or xarray...

Data
----

Here are a few examples of the data that can be fetched with **pymeteofr** (more details in the web service documentation):

- "Results from the French high resolution atmospheric forecast model (called AROME) on a grid with a resolution of 0°01 or 0°025 for France. Data is updated every 3 hours and available up to 42 hours, with a temporal resolution of 1 hour."

- "Results from the French global atmospheric forecast model (called ARPEGE) on a grid with a resolution of 0°1 for Europe. Data is updated four times a day and available up to 4 days, with a temporal resolution of 3 hours."

Licence
-------

These results are available without royalty under the open license `Etalab <https://www.etalab.gouv.fr/wp-content/uploads/2018/11/open-licence.pdf>`_ (pdf file), as long as the authorship of the "Information" is acknowledged.

**pymeteofr** is under a MIT License.

API key
-------

An important point is that you need a valid token in order to get access to the weather data. As stated in the web service documentation:

	It is compulsory to register to be able to access the services even when these services provide data without any limitation of access nor use. Data access policy implementation is based on a key mechanism (API keys) for now.

So here is how you get an account: 

	To get an account, a request must be sent to support.inspire@meteo.fr. A reply will be sent with an account identifier (UID) and the associated password (pwd).

The identifier and password will then allow **pymeteofr** to fetch the access token.