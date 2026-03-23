from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def copy_artifact(source: Path, artifacts_dir: Path, kind: str) -> dict[str, str]:
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Artifact not found: {source}")

    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    destination_name = f"{kind}_{digest}_{source.name}"
    destination = artifacts_dir / destination_name
    shutil.copy2(source, destination)

    return {
        "kind": kind,
        "source_path": str(source),
        "stored_path": str(destination),
        "filename": destination_name,
        "sha256_prefix": digest,
    }
