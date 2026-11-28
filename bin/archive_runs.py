#!/usr/bin/env python3
"""List the run files inside the zip archives of a deposit, without downloading them.

usage: archive_runs.py EVIDENCE/files.json

Many deposits put all their runs in one zip (RAWFiles.zip). `sdrf-tools fetch` then lists only the zip, so the
annotate agent cannot see the runs and the coverage precheck calls every run in the SDRF "invented". This reads
the zip's central directory with HTTP range requests (a few kB to a few MB; ZIP64 included) and rewrites
files.json in place: `files` lists the runs inside each zip instead of the zip (Bruker .d and Waters .raw folders
as one run each), `deposited_files` keeps the original list and `archives` records each zip's url and run count,
or the error when it could not be read. A deposit without zip files is left untouched. Exits 0 in every case.
"""
import json
import struct
import sys
import time
import urllib.request
from pathlib import PurePosixPath

RUN_FILE = (".raw", ".wiff", ".wiff2", ".mzml", ".mzxml")
RUN_FOLDER = (".d", ".raw")
MAX_DIRECTORY = 200 * 1024 * 1024


def zip_names(read, size):
    """Entry names of a zip, from its central directory. read(start, end) returns bytes start..end inclusive."""
    tail_start = max(0, size - 65557)
    tail = read(tail_start, size - 1)
    i = tail.rfind(b"PK\x05\x06")
    if i < 0:
        raise ValueError("no end of central directory record: not a zip")
    _, _, _, _, total, cd_size, cd_offset, _ = struct.unpack("<4sHHHHIIH", tail[i:i + 22])
    if total == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        loc = tail[i - 20:i]
        if loc[:4] != b"PK\x06\x07":
            raise ValueError("ZIP64 locator missing")
        z64_offset = struct.unpack("<4sIQI", loc)[2]
        z64 = read(z64_offset, z64_offset + 55)
        if z64[:4] != b"PK\x06\x06":
            raise ValueError("ZIP64 end record missing")
        total, cd_size, cd_offset = struct.unpack("<4sQHHIIQQQQ", z64)[7:10]
    if cd_size > MAX_DIRECTORY:
        raise ValueError(f"central directory of {cd_size} bytes is too large")
    cd = read(cd_offset, cd_offset + cd_size - 1)
    names, p = [], 0
    while p + 46 <= len(cd) and cd[p:p + 4] == b"PK\x01\x02":
        flags = struct.unpack("<H", cd[p + 8:p + 10])[0]
        name_len, extra_len, comment_len = struct.unpack("<HHH", cd[p + 28:p + 34])
        raw = cd[p + 46:p + 46 + name_len]
        names.append(raw.decode("utf-8" if flags & 0x800 else "cp437", errors="replace"))
        p += 46 + name_len + extra_len + comment_len
    return names


def run_members(names):
    """The runs among zip entry names: run files, and .d/.raw folders as one run each, by base name."""
    runs = set()
    for name in names:
        parts = PurePosixPath(name).parts
        if not parts or "__MACOSX" in parts or parts[-1].startswith("._"):
            continue
        folder = next((p for p in parts[:-1] if p.lower().endswith(RUN_FOLDER)), None)
        if folder:
            runs.add(folder)
        elif not name.endswith("/") and parts[-1].lower().endswith(RUN_FILE):
            runs.add(parts[-1])
        elif name.endswith("/") and parts[-1].lower().endswith(RUN_FOLDER):
            runs.add(parts[-1])
    return sorted(runs)


def http_opener(url, tries=3):
    """(read, size) for a URL that serves byte ranges, in as few requests as possible (ftp.pride.ebi.ac.uk takes
    ~20 s per request): one suffix request gives the size and the last 64 kB, where the end records are; reads
    inside it are served from memory. Sequential, with a pause and retries on errors such as the 403 that
    ftp.pride.ebi.ac.uk gives under parallel reads."""
    def call(req):
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.headers, r.read()
            except OSError:
                if attempt == tries - 1:
                    raise
                time.sleep(5 * (attempt + 1))

    headers, tail = call(urllib.request.Request(url, headers={"Range": "bytes=-65557"}))
    total = (headers.get("Content-Range") or "").rsplit("/", 1)[-1]
    size = int(total) if total.isdigit() else len(tail)
    tail_start = size - len(tail)

    def read(start, end):
        if start >= tail_start:
            return tail[start - tail_start:end - tail_start + 1]
        return call(urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"}))[1]
    return read, size


def expand(files_json, opener=http_opener):
    with open(files_json) as fh:
        listing = json.load(fh)
    deposited = listing.get("files") or []
    zips = [f for f in deposited if f.lower().endswith(".zip")]
    if not zips:
        return listing
    urls = listing.get("urls") or {}
    files, archives = [], {}
    for name in deposited:
        if name not in zips:
            files.append(name)
            continue
        try:
            if not urls.get(name):
                raise ValueError("no url")
            read, size = opener(urls[name])
            names = zip_names(read, size)
            runs = run_members(names)
            archives[name] = {"url": urls[name], "entries": len(names), "runs": len(runs)}
            files.extend(runs or [name])
        except Exception as e:  # keep the zip itself; the agent can still look inside
            archives[name] = {"url": urls.get(name), "error": f"{type(e).__name__}: {e}"[:300]}
            files.append(name)
    listing.update(files=files, deposited_files=deposited, archives=archives)
    with open(files_json, "w") as fh:
        json.dump(listing, fh, indent=1)
    return listing


if __name__ == "__main__":
    try:
        out = expand(sys.argv[1])
        print(f"{sys.argv[1]}: {len(out.get('files') or [])} run files; archives: {out.get('archives', {})}")
    except Exception as e:
        print(f"archive listing skipped: {type(e).__name__}: {e}")
    sys.exit(0)
