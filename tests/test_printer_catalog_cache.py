"""Concurrent page reads must share one preset scan and its full cache lifetime."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

from print_prep import printer_catalog


def test_concurrent_catalog_reads_scan_once(tmp_path, monkeypatch):
    monkeypatch.setattr(printer_catalog, "SOURCES", ("orca",))
    monkeypatch.setattr(printer_catalog, "source_root", lambda _: tmp_path)
    monkeypatch.setattr(printer_catalog, "_cache", {})
    ready = Barrier(4)
    scan_started = Event()
    release_scan = Event()
    counter_lock = Lock()
    scans = []

    def scan(root):
        with counter_lock:
            scans.append(root)
        scan_started.set()
        assert release_scan.wait(3)
        return []

    def read():
        ready.wait(timeout=3)
        return printer_catalog.catalog()

    monkeypatch.setattr(printer_catalog, "vendor_roots", scan)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [pool.submit(read) for _ in range(4)]
        assert scan_started.wait(3)
        release_scan.set()
        values = [future.result(timeout=3) for future in results]
    assert len(scans) == 1
    values[0]["printers"].append({"name": "caller-only"})
    assert values[1]["printers"] == []
    assert printer_catalog.catalog()["printers"] == []


def test_cache_lifetime_starts_after_scan_completes(tmp_path, monkeypatch):
    monkeypatch.setattr(printer_catalog, "SOURCES", ("orca",))
    monkeypatch.setattr(printer_catalog, "source_root", lambda _: tmp_path)
    monkeypatch.setattr(printer_catalog, "_cache", {})
    clock = [100.0]
    scans = []
    monkeypatch.setattr(printer_catalog.time, "monotonic", lambda: clock[0])

    def scan(root):
        scans.append(root)
        clock[0] += 35
        return []

    monkeypatch.setattr(printer_catalog, "vendor_roots", scan)
    printer_catalog.catalog()
    printer_catalog.catalog()
    assert len(scans) == 1
    clock[0] += 31
    printer_catalog.catalog()
    assert len(scans) == 2
