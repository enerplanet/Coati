"""Small models of each framework, built and solved with the framework itself.

The models serve two purposes. They produce the files under ``tests/data``, and
the tests marked ``frameworks`` build them with whatever version of a framework
is installed and compare what Coati reads from the file with what the framework
says about its own model.

Every module has a function ``build`` and can be run as a program::

    python -m models.pypsa_model OUTPUT_DIRECTORY
"""
