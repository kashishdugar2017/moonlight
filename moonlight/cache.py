"""Cache: saved results, kept in memory and on disk.

    save(kind, version, key, value)   remember a value
    load(kind, version, key)          the value, or None if it is not saved
    forget_memory()                   empty the memory; the disk is kept

It works like a notebook with one section per Open Targets data version.
An entry is found again only with the same kind, the same version and the
same key. When Open Targets releases new data the version changes, so the
old section is simply never opened again. Nothing here deletes files.

The notebook lives in the folder named by the environment variable
MOONLIGHT_CACHE_DIR (default ".moonlight-cache"). If the folder cannot be
written or a file cannot be read, Moonlight carries on from memory.

This module never talks to the network. Values must be plain JSON.
"""

import hashlib
import json
import os
import pathlib
import re
import threading
from typing import Any, Dict, Optional, Tuple

FOLDER_VARIABLE = "MOONLIGHT_CACHE_DIR"
DEFAULT_FOLDER = ".moonlight-cache"

_memory: Dict[Tuple[str, str, str, str], Any] = {}
_lock = threading.Lock()


def folder() -> pathlib.Path:
    """Where the saved results are kept on disk."""
    return pathlib.Path(os.environ.get(FOLDER_VARIABLE) or DEFAULT_FOLDER)


def forget_memory() -> None:
    """Empty the memory. Files on disk stay where they are."""
    with _lock:
        _memory.clear()


def _key_text(key: Any) -> str:
    return json.dumps(key, sort_keys=True)


def _safe(name: str) -> str:
    """A version or kind as a folder name that cannot leave the cache folder."""
    return "v-" + re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _file(kind: str, version: str, key_text: str) -> pathlib.Path:
    digest = hashlib.sha256(key_text.encode("utf-8")).hexdigest()
    return folder() / _safe(version) / _safe(kind) / (digest + ".json")


def load(kind: str, version: str, key: Any) -> Optional[Any]:
    """The saved value, or None. Memory is looked in first, then the disk."""
    key_text = _key_text(key)
    place = (str(folder()), version, kind, key_text)
    with _lock:
        if place in _memory:
            return _memory[place]
    try:
        entry = json.loads(_file(kind, version, key_text).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # not saved, or the file is damaged
    # The file says what it holds. If that is not what was asked for, it
    # is not used.
    if not isinstance(entry, dict) or "value" not in entry:
        return None
    if (entry.get("kind"), entry.get("version"), entry.get("key")) != (kind, version, key_text):
        return None
    with _lock:
        _memory[place] = entry["value"]
    return entry["value"]


def save(kind: str, version: str, key: Any, value: Any) -> None:
    """Remember the value in memory and write it to disk."""
    key_text = _key_text(key)
    with _lock:
        _memory[(str(folder()), version, kind, key_text)] = value
    file = _file(kind, version, key_text)
    entry = {"kind": kind, "version": version, "key": key_text, "value": value}
    # Written under another name first and then renamed, so a file is never
    # read half written.
    part = file.with_name(f"{file.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        part.write_text(json.dumps(entry), encoding="utf-8")
        os.replace(part, file)
    except OSError:
        pass  # the disk is a bonus; memory still has it
