import urllib.request
from urllib.parse import urlparse

import pytest

SEC_HOSTS = {"www.sec.gov", "efts.sec.gov", "data.sec.gov"}


@pytest.fixture(autouse=True)
def no_real_sec_requests(monkeypatch):
    """No test may reach sec.gov: the access rules forbid it and CI would hammer it."""
    real = urllib.request.urlopen

    def guarded(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        if urlparse(url).hostname in SEC_HOSTS:
            raise AssertionError(f"test tried to reach sec.gov: {url}")
        return real(req, *args, **kwargs)
    monkeypatch.setattr(urllib.request, "urlopen", guarded)
