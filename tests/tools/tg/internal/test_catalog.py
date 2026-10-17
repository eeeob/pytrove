from __future__ import annotations as _annotations

import subprocess
import sys

LAZY_PROBE = """
import pytrove
from pytrove.tg_tools._internal import catalog
assert catalog._catalog.cache_info().currsize == 0
pytrove.rand_tg_device(unique_id="probe")
assert catalog._catalog.cache_info().currsize == 1
"""


def test_bundled_catalogs_are_read_on_first_use_and_not_at_import() -> None:
    subprocess.run([sys.executable, "-c", LAZY_PROBE], check=True)
