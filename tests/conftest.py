import os

import pytest


@pytest.fixture(autouse=True)
def isolate_kxian_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith("KXIAN_"):
            monkeypatch.delenv(key, raising=False)
