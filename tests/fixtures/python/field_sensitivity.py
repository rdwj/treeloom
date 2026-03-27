"""Fixture for field-sensitivity tests.

Tests that the Python visitor emits field_name attrs on DATA_FLOWS_TO edges
produced by attribute access (e.g. request.form vs request.headers).
"""


class Request:
    def __init__(self):
        self.form = {}
        self.headers = {}


def handle(request):
    tainted = request.form
    safe = request.headers
    process(tainted)
    process(safe)


def process(data):
    return data
