"""Tests for the single-instance lock in src/monitor.py.

A second overlapping monitor pass must never fire the same alert twice, so a
held lock means "bail out". flock semantics are per open-file-description:
two separate open() calls in the same process conflict with each other, so
this is fully testable without spawning subprocesses.
"""
import os

from src.monitor import LOCK_PATH, acquire_singleton_lock


def test_second_acquire_fails_while_first_held(tmp_path):
    lock_file = tmp_path / "monitor.lock"
    first = acquire_singleton_lock(lock_file)
    assert first is not None
    try:
        assert acquire_singleton_lock(lock_file) is None
    finally:
        first.close()


def test_lock_releases_on_close(tmp_path):
    lock_file = tmp_path / "monitor.lock"
    first = acquire_singleton_lock(lock_file)
    assert first is not None
    first.close()
    second = acquire_singleton_lock(lock_file)
    assert second is not None
    second.close()


def test_lock_file_created_at_expected_path(tmp_path, monkeypatch):
    custom = tmp_path / "custom.lock"
    monkeypatch.setattr("src.monitor.LOCK_PATH", custom)
    fh = acquire_singleton_lock()
    assert fh is not None
    fh.close()
    assert custom.exists()


def test_default_lock_path_lives_in_repo_root():
    # The lock must sit next to state.json so every checkout of the repo
    # guards itself, whatever directory the process runs from.
    assert LOCK_PATH.name == "monitor.lock"
    assert os.path.isabs(str(LOCK_PATH))
