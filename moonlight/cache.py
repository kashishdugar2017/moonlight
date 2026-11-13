"""Cache: saved results, kept in memory and on disk.

    save(kind, version, key, value)   remember a value, and when it was saved
    load(kind, version, key)          the value, or None if it is not saved
    load(kind, version, key, max_age_seconds=...)
                                      the same, but None if it was saved
                                      longer ago than that
    forget_memory()                   empty the memory; the disk is kept

It works like a notebook with one section per Open Targets data version.
An entry is found again only with the same kind, the same version and the
same key. When Open Targets releases new data the version changes, so the
old section is simply never opened again. Nothing here deletes files.

Every entry records when it was saved ("saved_at", seconds on the clock).
The cache does not decide how old is too old. The caller does, with
max_age_seconds. An entry past that age is not handed back, and the fresh
answer saved afterwards takes its place.

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
import time
from typing import Any, Dict, Optional, Tuple

FOLDER_VARIABLE = "MOONLIGHT_CACHE_DIR"
DEFAULT_FOLDER = ".moonlight-cache"

# place -> (value, when it was saved)
_memory: Dict[Tuple[str, str, str, str], Tuple[Any, Any]] = {}
_lock = threading.Lock()


def folder() -> pathlib.Path:
    """Where the saved results are kept on disk."""
    return pathlib.Path(os.environ.get(FOLDER_VARIABLE) or DEFAULT_FOLDER)


def forget_memory() -> None:
    """Empty the memory. Files on disk stay where they are."""
    with _lock:
        _memory.clear()


def _now() -> float:
    """The time on the clock, in seconds. Tests replace this."""
    return time.time()


def _in_date(saved_at: Any, max_age_seconds: Optional[float]) -> bool:
    """Is an entry saved at that time still good to use?

    With no max_age_seconds there is no use-by date, so yes. Otherwise no
    if it is too old, if it has no date, or if its date is in the future
    (the clock was wrong, so the age cannot be trusted).
    """
    if max_age_seconds is None:
        return True
    if isinstance(saved_at, bool) or not isinstance(saved_at, (int, float)):
        return False
    return 0 <= _now() - saved_at <= max_age_seconds


def _key_text(key: Any) -> str:
    return json.dumps(key, sort_keys=True)


def _safe(name: str) -> str:
    """A version or kind as a folder name that cannot leave the cache folder."""
    return "v-" + re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _file(kind: str, version: str, key_text: str) -> pathlib.Path:
    digest = hashlib.sha256(key_text.encode("utf-8")).hexdigest()
    return folder() / _safe(version) / _safe(kind) / (digest + ".json")


def load(kind: str, version: str, key: Any,
         max_age_seconds: Optional[float] = None) -> Optional[Any]:
    """The saved value, or None. Memory is looked in first, then the disk.

    max_age_seconds: the use-by date. A value saved longer ago than this
    counts as not saved. Left out, a value is good however old it is.
    """
    key_text = _key_text(key)
    place = (str(folder()), version, kind, key_text)
    with _lock:
        found = _memory.get(place)
    if found is not None:
        value, saved_at = found
        return value if _in_date(saved_at, max_age_seconds) else None
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
    saved_at = entry.get("saved_at")  # files from before ticket 6.3 have none
    with _lock:
        _memory[place] = (entry["value"], saved_at)
    return entry["value"] if _in_date(saved_at, max_age_seconds) else None


def save(kind: str, version: str, key: Any, value: Any) -> None:
    """Remember the value, and when it was saved, in memory and on disk."""
    key_text = _key_text(key)
    saved_at = _now()
    with _lock:
        _memory[(str(folder()), version, kind, key_text)] = (value, saved_at)
    file = _file(kind, version, key_text)
    entry = {"kind": kind, "version": version, "key": key_text,
             "saved_at": saved_at, "value": value}
    # Written under another name first and then renamed, so a file is never
    # read half written.
    part = file.with_name(f"{file.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        part.write_text(json.dumps(entry), encoding="utf-8")
        os.replace(part, file)
    except OSError:
        pass  # the disk is a bonus; memory still has it
