"""
Tests of the client address resolution.
"""

from starlette.requests import Request

from mimir.api.client_ip import get_client_ip


def _request(client, headers=()):
    return Request({"type": "http", "headers": list(headers), "client": client})


def test_direct_client_address():
    assert get_client_ip(_request(("192.168.1.50", 5000))) == "192.168.1.50"


def test_missing_client_is_unknown():
    assert get_client_ip(_request(None)) == "unknown"


def test_forwarding_headers_sent_by_the_client_are_ignored():
    headers = [(b"x-forwarded-for", b"6.6.6.6"), (b"x-real-ip", b"6.6.6.6")]
    assert get_client_ip(_request(("10.0.0.2", 5000), headers)) == "10.0.0.2"
