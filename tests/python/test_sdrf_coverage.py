"""Offline tests for bin/sdrf_coverage.py. Run: python3 -m unittest discover -s tests/python -v"""

import importlib.util
import json
import os
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "bin", "sdrf_coverage.py")
spec = importlib.util.spec_from_file_location("sdrf_coverage", SCRIPT)
cov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cov)


def file_object(name, category):
    return {
        "fileName": name,
        "fileCategory": {"value": category},
        "publicFileLocations": [{"value": f"ftp://ftp.pride.ebi.ac.uk/pride/data/archive/{name}"}],
    }


def write_sdrf(text):
    fh = tempfile.NamedTemporaryFile("w", suffix=".sdrf.tsv", delete=False)
    fh.write(text)
    fh.close()
    return fh.name


class FakePride:
    """Serves /files/all and /files?page=N from canned data and records the URLs it was asked for."""

    def __init__(self, files, files_all_works=True):
        self.files = files
        self.files_all_works = files_all_works
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if url.endswith("/files/all"):
            if not self.files_all_works:
                raise OSError("HTTP Error 500")
            return self.files
        page = int(url.split("page=")[1].split("&")[0])
        return self.files[page * cov.PAGE_SIZE : (page + 1) * cov.PAGE_SIZE]


class CoverageReportTest(unittest.TestCase):
    def test_search_and_peak_files_do_not_lower_coverage(self):
        deposit = cov.parse_files(
            [file_object(f"r{i}.raw", "RAW") for i in range(8)]
            + [file_object("search.zip", "SEARCH"), file_object("r0.mgf", "PEAK")]
        )
        report = cov.coverage_report("PXD000001", {f"r{i}.raw" for i in range(8)}, deposit)
        self.assertEqual(report["denominator"], "RAW")
        self.assertEqual(report["deposit_data_count"], 8)
        self.assertEqual(report["coverage"], 1.0)
        self.assertEqual(report["missing"], [])

    def test_peak_lists_are_the_denominator_without_raw_files(self):
        deposit = cov.parse_files([file_object("a.mzML", "PEAK"), file_object("b.mzML", "PEAK"), file_object("s.zip", "SEARCH")])
        report = cov.coverage_report("PXD000001", {"a.mzML"}, deposit)
        self.assertEqual(report["denominator"], "PEAK")
        self.assertEqual(report["coverage"], 0.5)

    def test_missing_files_are_reported(self):
        deposit = cov.parse_files([file_object("a.raw", "RAW")])
        report = cov.coverage_report("PXD000001", {"a.raw", "invented.raw"}, deposit)
        self.assertEqual(report["matched"], ["a.raw"])
        self.assertEqual(report["missing"], ["invented.raw"])

    def test_string_file_lists_are_classified_by_extension(self):
        deposit = cov.parse_files(["pride/x/a.raw", "pride/x/b.wiff", "pride/x/txt.zip", "pride/x/README.txt"])
        report = cov.coverage_report("PXD000001", {"a.raw"}, deposit)
        self.assertEqual(report["deposit_data_count"], 2)
        self.assertEqual(report["coverage"], 0.5)


class FetchDepositTest(unittest.TestCase):
    def test_files_all_is_used_when_it_works(self):
        pride = FakePride([file_object("a.raw", "RAW")])
        self.assertEqual(cov.fetch_deposit("PXD000001", pride), {"a.raw": "RAW"})
        self.assertEqual(len(pride.urls), 1)

    def test_paginated_fallback_starts_at_page_zero(self):
        files = [file_object(f"r{i}.raw", "RAW") for i in range(105)]
        pride = FakePride(files, files_all_works=False)
        deposit = cov.fetch_deposit("PXD000001", pride)
        self.assertEqual(len(deposit), 105)
        self.assertIn("page=0", pride.urls[1])
        self.assertIn("page=1", pride.urls[2])
        self.assertEqual(len(pride.urls), 3)

    def test_fetch_json_retries_transient_failures(self):
        calls, sleeps = [], []
        real_urlopen = cov.urllib.request.urlopen

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, *args):
                return b'["a.raw"]'

        def flaky_urlopen(request, timeout):
            calls.append(request.full_url)
            if len(calls) < 3:
                raise OSError("connection reset")
            return Response()

        cov.urllib.request.urlopen = flaky_urlopen
        try:
            self.assertEqual(cov.fetch_json("https://example.org/x", sleep=sleeps.append), ["a.raw"])
        finally:
            cov.urllib.request.urlopen = real_urlopen
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, list(cov.RETRY_DELAYS))


class MainTest(unittest.TestCase):
    def run_main(self, sdrf_text, fetch):
        sdrf = write_sdrf(sdrf_text)
        out = sdrf + ".coverage.json"
        try:
            cov.main(["--pxd", "PXD000001", "--sdrf", sdrf, "--out", out], fetch=fetch)
            with open(out) as fh:
                return json.load(fh)
        finally:
            os.remove(sdrf)
            if os.path.exists(out):
                os.remove(out)

    def test_header_is_case_insensitive_and_cells_may_hold_several_files(self):
        report = self.run_main(
            "source name\tComment[data file]\ns1\ta.raw, b.raw\ns2\tc.raw\n",
            FakePride([file_object(n, "RAW") for n in ("a.raw", "b.raw", "c.raw")]),
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["matched_count"], 3)
        self.assertEqual(report["coverage"], 1.0)

    def test_unreachable_pride_is_not_verifiable(self):
        def down(url):
            raise OSError("network down")

        report = self.run_main("source name\tcomment[data file]\ns1\ta.raw\n", down)
        self.assertEqual(report["status"], "not_verifiable")
        self.assertIsNone(report["coverage"])
        self.assertEqual(report["sdrf_files"], 1)


if __name__ == "__main__":
    unittest.main()
