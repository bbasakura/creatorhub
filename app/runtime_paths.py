"""Canonical paths for transient CreatorHub runtime artifacts.

Persistent business data, browser profiles, media and credentials remain under
``data/``.  Transient logs/diagnostics/temp files belong under ``data/runtime``.
"""
from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"


def runtime_root(configured: str | Path | None = None) -> Path:
    raw = os.environ.get("CREATORHUB_RUNTIME_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
    elif configured:
        path = Path(configured).expanduser()
    else:
        path = DEFAULT_RUNTIME_DIR
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def runtime_subdir(*parts: str, configured: str | Path | None = None,
                   create: bool = True) -> Path:
    path = runtime_root(configured)
    for part in parts:
        clean = str(part or "").strip().replace("\\", "/").strip("/")
        if not clean or clean in {".", ".."} or "/../" in f"/{clean}/":
            raise ValueError("invalid runtime path component")
        path /= clean
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _move_legacy_files(source: Path, destination: Path) -> int:
    """Move only files whose destination does not exist; never overwrite."""
    if not source.is_dir():
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    moved = 0
    for item in source.iterdir():
        if not item.is_file():
            continue
        target = destination / item.name
        if target.exists():
            continue
        try:
            item.replace(target)
            moved += 1
        except OSError:
            # Open files / cross-device layouts remain readable at the legacy path.
            continue
    try:
        source.rmdir()
    except OSError:
        pass
    return moved


def ensure_runtime_layout(configured: str | Path | None = None, *,
                          migrate_legacy: bool = True) -> dict[str, Path | int]:
    root = runtime_root(configured)
    logs = runtime_subdir("logs", configured=root)
    diagnostics = runtime_subdir("diagnostics", configured=root)
    temp = runtime_subdir("temp", configured=root)

    # CreatorHub historically owned this directory for Douyin publish dumps.
    legacy_debug = PROJECT_ROOT / "data" / "debug"
    douyin_debug = runtime_subdir("diagnostics", "douyin", configured=root)
    migrated = (_move_legacy_files(legacy_debug, douyin_debug)
                if migrate_legacy else 0)
    return {
        "root": root,
        "logs": logs,
        "diagnostics": diagnostics,
        "temp": temp,
        "migrated_debug_files": migrated,
    }
