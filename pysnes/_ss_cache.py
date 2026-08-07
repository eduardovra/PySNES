"""On-disk cache with file-lock coordination for SingleStepTests collection.

Both pysnes/cpu/test_cpu.py and pysnes/apu/test_spc700.py parse large JSON
suites during collection. Under pytest-xdist each worker re-collects
independently, so without caching the parse cost and peak memory multiply by
worker count. This module caches the parsed (file_path, index) parameter list
to disk; workers after the first read a pickle instead of re-parsing.

Coordination: fcntl.flock on a sidecar .lock file. First caller builds and
writes atomically via tmp+rename; others block on the lock, re-check, and
then just read. POSIX-only (fine: the project is Linux-only).
"""

import fcntl
import hashlib
import os
import pickle


CACHE_DIR = ".pytest_cache"


def _dir_fingerprint(tests_path):
    entries = []
    for name in sorted(os.listdir(tests_path)):
        if not name.lower().endswith(".json"):
            continue
        st = os.stat(os.path.join(tests_path, name))
        entries.append((name, st.st_mtime_ns, st.st_size))
    return entries


def _cache_key(suite_name, tests_path, filter_args):
    blob = repr(
        (suite_name, filter_args, _dir_fingerprint(tests_path))
    ).encode()
    return hashlib.sha1(blob).hexdigest()[:16]


def _cache_path(suite_name, key):
    return os.path.join(CACHE_DIR, f"ss_{suite_name}_{key}.pickle")


def _valid(path, key):
    try:
        with open(path, "rb") as f:
            stored_key, _, _ = pickle.load(f)
    except (FileNotFoundError, EOFError, pickle.UnpicklingError, ValueError):
        return False
    return stored_key == key


def _read(path):
    with open(path, "rb") as f:
        _, params, ids = pickle.load(f)
    return params, ids


def _atomic_write(path, key, params, ids):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump((key, params, ids), f, protocol=pickle.HIGHEST_PROTOCOL)
    os.rename(tmp, path)


def get_or_build(suite_name, tests_path, filter_args, parse_fn):
    """Return (params, ids). params is [(file_path, index), ...]; ids are pytest IDs.

    On cache hit: read pickle, return.
    On cache miss: acquire exclusive flock, re-check, call parse_fn(), write, return.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(suite_name, tests_path, filter_args)
    path = _cache_path(suite_name, key)

    if _valid(path, key):
        return _read(path)

    lock_path = path + ".lock"
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if _valid(path, key):
            return _read(path)
        params, ids = parse_fn()
        _atomic_write(path, key, params, ids)
    return params, ids
