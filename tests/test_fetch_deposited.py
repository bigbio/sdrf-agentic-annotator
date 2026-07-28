from sdrf_harness.fetcher import deposited_sdrf_url, fetch_deposited_sdrf
from sdrf_harness.models import Bundle

def test_url_builder():
    u = deposited_sdrf_url("PXD000001", "2014/01", "PXD000001.sdrf.tsv")
    assert u == "https://ftp.pride.ebi.ac.uk/pride/data/archive/2014/01/PXD000001/PXD000001.sdrf.tsv"

class _Sess:
    def __init__(self, text): self._t = text; self.url = None
    def get(self, url, timeout=0):
        self.url = url
        class R:
            def __init__(s, t): s.text = t
        return R(self._t)

def test_fetch_returns_none_without_deposited():
    b = Bundle(accession="X", repository="pride", deposited_sdrf=None)
    assert fetch_deposited_sdrf(b, "2020/01", session=_Sess("x")) is None

def test_fetch_downloads_when_present():
    b = Bundle(accession="PXD1", repository="pride", deposited_sdrf="PXD1.sdrf.tsv")
    s = _Sess("source name\ta.raw\n")
    txt = fetch_deposited_sdrf(b, "2020/01", session=s)
    assert txt.startswith("source name")
    assert s.url.endswith("/2020/01/PXD1/PXD1.sdrf.tsv")
