"""Small, self-contained workloads used by the demo suite (made up, nothing external)."""

from __future__ import annotations

import hashlib
import json

_DATA = [(i * 7919) % 10007 for i in range(5000)]
_BLOB = bytes(range(256)) * 1024
_DOC = {"items": [{"id": i, "name": f"item-{i}", "tags": ["a", "b"]} for i in range(200)]}


def sort_numbers() -> None:
    sorted(_DATA)


def hash_blob() -> None:
    hashlib.sha256(_BLOB).hexdigest()


def json_roundtrip() -> None:
    json.loads(json.dumps(_DOC))
