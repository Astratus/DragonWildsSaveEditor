"""Shared fixtures: work on a temp copy of the synthetic sample save, never the original.

tests/fixtures/sample_character.json is a synthetic character (name "SampleHero",
random GUIDs) built by tests/make_fixture.py; it sits at Black Knight's Fortress step 7.
tests/fixtures/sample_character_v83.json is an older (save Version 83) sample.
tests/fixtures/catalog/ is a small subset of the item catalog (tests/make_catalog_fixture.py).

Isolation: before the package is imported, LOCALAPPDATA is pointed at a temporary folder for
the whole test run. The editor's user-data folder (catalog, snapshots, logs) and the game's
save folders therefore resolve inside it, so no test reads or writes the real
%LOCALAPPDATA%. The fixture catalog is copied to <temp>/DragonwildsSaveEditor/catalog, where it
acts as a user-built catalog and takes precedence over the bundled one (data/catalog/); tests
that need the bundled catalog point the user folder elsewhere (catalog.set_user_data_dir).
REAL_LOCALAPPDATA keeps the original value (tests that opt in via DW_TEST_WORLD use explicit
paths instead).
"""

import atexit
import contextlib
import glob
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
FIXTURE_CATALOG = os.path.join(FIXTURES, "catalog")

REAL_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
if not os.environ.get("DW_TESTS_LOCALAPPDATA"):
    _SESSION_DIR = tempfile.mkdtemp(prefix="dw-tests-")
    atexit.register(shutil.rmtree, _SESSION_DIR, True)
    os.environ["LOCALAPPDATA"] = os.environ["DW_TESTS_LOCALAPPDATA"] = _SESSION_DIR
    shutil.copytree(FIXTURE_CATALOG, os.path.join(_SESSION_DIR, "DragonwildsSaveEditor", "catalog"))
TEST_LOCALAPPDATA = os.environ["DW_TESTS_LOCALAPPDATA"]

from dragonwilds_save_editor import save as dw_save  # noqa: E402

SAVE_NAME = "sample_character.json"
SAMPLE_SAVE = os.path.join(FIXTURES, SAVE_NAME)
SAMPLE_V83 = os.path.join(FIXTURES, "sample_character_v83.json")

_GAME = None


def game_data():
    global _GAME
    if _GAME is None:
        _GAME = dw_save.GameData()
    return _GAME


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class TempSaveCase(unittest.TestCase):
    """Copies the sample save into a temp dir; patches game_is_running -> False."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, SAVE_NAME)
        shutil.copyfile(SAMPLE_SAVE, self.path)
        self.orig_bytes = read_bytes(self.path)
        patcher = mock.patch.object(dw_save, "game_is_running", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.game = game_data()

    def open(self):
        return dw_save.SaveFile(self.path, self.game)

    def backups(self):
        return sorted(glob.glob(glob.escape(self.path) + ".*.pyedit.bak"))

    def quiet_save(self, s, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return s.save(**kw)


def test_worlds():
    """World saves named by DW_TEST_WORLD, sorted: a .sav file, a folder of .sav files, or
    several of either separated by os.pathsep. [] when unset, so real-world tests skip.
    Tests only ever read these paths and work on temporary copies."""
    out = []
    for part in (os.environ.get("DW_TEST_WORLD") or "").split(os.pathsep):
        part = part.strip().strip('"')
        if not part:
            continue
        if os.path.isdir(part):
            out += [p for p in glob.glob(os.path.join(glob.escape(part), "*.sav")) if os.path.isfile(p)]
        elif os.path.isfile(part):
            out.append(part)
    return sorted(set(os.path.abspath(p) for p in out))
