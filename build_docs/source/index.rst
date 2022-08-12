.. Biogeochemical model database documentation master file, created by
   sphinx-quickstart on Tue Sep  8 12:56:51 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Biogeochemical model database's documentation!
=========================================================

`bgc_md2  <https://github.com/MPIBGC-TEE/bgc_md2>`_ is a 
Python package to collect compartmental models of the form

.. math:: \frac{d}{dt}\,x(t) = B(x(t),t)\,x(t) + u(t).

Topics:
-------
.. toctree::
   :maxdepth: 2

   manual/usage
   manual/structure

API
---
.. toctree::
   :maxdepth: 3

   auto/modules.rst

Main modules
----------------

.. autosummary::
   :toctree: _autosummary

    ~bgc_md2.models
    ~bgc_md2.resolve


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
