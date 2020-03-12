=====
Usage
=====

To use PyMeteoFr in a project::

    import pymeteofr

The first thing to do is to set a valid API key.

Setting the web service token
=============================

First you need to import the ``Fetcher`` class:

.. code:: ipython3

    from pymeteofr import Fetcher

Then you can instanciate a ``Fetcher`` object without a token:

.. code:: ipython3

    fetcher = Fetcher()
    fetcher.token is None

.. parsed-literal::

    True

The token can later be fetched using a credentials JSON file of
the form:

.. code:: json

   {
       "username": "john.doe",
       "password": "1234"
   }

This is done with the ``credentials_file_path`` argument and by calling the ``fetch_token`` method:

.. code:: ipython3

    fetcher.fetch_token(credentials_file_path='/home/john/Workspace/pymeteofr/notebooks/credentials.json')

.. parsed-literal::

    -- GetAPIKey request --

Or by directly giving a username and password:

.. code:: ipython3

    fetcher.fetch_token(username="john.doe", password="1234")

.. parsed-literal::

    -- GetAPIKey request --

Finally the token can be directly given as an argument when instanciating the ``Fetcher`` object:

.. code:: ipython3

    fetcher = Fetcher(token="__xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx__")
