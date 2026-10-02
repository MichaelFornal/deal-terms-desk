import socket
import urllib.request
from urllib.parse import urlparse

import pytest

SEC_HOSTS = {"www.sec.gov", "efts.sec.gov", "data.sec.gov"}


@pytest.fixture(autouse=True)
def no_real_sec_requests(monkeypatch):
    """No test may reach sec.gov: the access rules forbid it and CI would hammer it."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    real = urllib.request.urlopen

    def guarded(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        if urlparse(url).hostname in SEC_HOSTS:
            raise AssertionError(f"test tried to reach sec.gov: {url}")
        return real(req, *args, **kwargs)
    monkeypatch.setattr(urllib.request, "urlopen", guarded)

    real_gai = socket.getaddrinfo

    def guarded_gai(host, *args, **kwargs):
        name = host.decode("ascii", "ignore") if isinstance(host, bytes) else (host or "")
        name = name.lower().rstrip(".")
        if name == "sec.gov" or name.endswith(".sec.gov"):
            raise AssertionError(f"test tried to resolve sec.gov: {name}")
        return real_gai(host, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_gai)
