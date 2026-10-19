"""A populated workbench loads settings, thumbnails and parts concurrently."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def test_page_load_burst_does_not_reset_connections(studio_env):
    ready = Barrier(24)

    def read(_):
        ready.wait(timeout=5)
        status, body = studio_env["client"].get("/api/shapes")
        assert status == 200 and body["ok"]

    with ThreadPoolExecutor(max_workers=24) as pool:
        list(pool.map(read, range(48)))
