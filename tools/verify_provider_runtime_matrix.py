"""Verify the frozen provider runtime isolation matrix."""

from __future__ import annotations

import json

from maskfactory.providers.runtime_matrix import verify_runtime_matrix

if __name__ == "__main__":
    print(json.dumps(verify_runtime_matrix(), indent=2, sort_keys=True))
