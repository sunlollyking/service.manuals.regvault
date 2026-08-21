# -*- coding: utf-8 -*-
"""Finds games that have no manual and fetches the ones the catalogue has.

This is deliberately the same rule Kodi's viewer uses to find a manual, so
that anything written here is picked up without the viewer needing to be told:
the manual takes the game's name, and sits either beside it or in a "manuals"
folder next to it.

No Kodi imports here, so it can be tested on its own. Progress is reported
through a callback rather than a dialog.
"""

import os

from . import hashing
from . import regvault
from . import systems

#: What the viewer looks for, in the order it prefers
MANUAL_EXTENSIONS = (".pdf", ".cbz", ".cbr")

MANUAL_SUBFOLDER = "manuals"


class Result(object):
    """What happened to one game."""

    FETCHED = "fetched"
    HAVE = "have"
    NOT_CATALOGUED = "not catalogued"
    NO_MANUAL = "no manual"
    UNKNOWN_SYSTEM = "unknown system"
    SKIPPED = "skipped"
    FAILED = "failed"

    def __init__(self, path, outcome, detail=""):
        self.path = path
        self.outcome = outcome
        self.detail = detail

    def __repr__(self):
        return "<%s %s %s>" % (os.path.basename(self.path), self.outcome, self.detail)


def stem(path):
    """A game's filename with its extension removed."""
    return os.path.splitext(os.path.basename(path))[0]


def existing_manual(path, exists=os.path.exists):
    """The manual a game already has, or None.

    Mirrors the viewer's own search, so a game it can already show a manual
    for is left alone.
    """
    folder = os.path.dirname(path)
    name = stem(path)

    for directory in (folder, os.path.join(folder, MANUAL_SUBFOLDER)):
        for extension in MANUAL_EXTENSIONS:
            candidate = os.path.join(directory, name + extension)
            if exists(candidate):
                return candidate

    return None


def destination(path, beside_game=False):
    """Where a fetched manual should be written.

    The "manuals" subfolder is the default because it keeps a games folder
    readable, and the viewer looks in both.
    """
    folder = os.path.dirname(path)
    if not beside_game:
        folder = os.path.join(folder, MANUAL_SUBFOLDER)

    return os.path.join(folder, stem(path) + ".pdf")


class Fetcher(object):
    #: Refuse a manual above this. The catalogue holds a few at over a
    #: hundred megabytes, which is not what someone expects a manual to cost.
    DEFAULT_MANUAL_LIMIT = 32 * 1024 * 1024

    def __init__(self, client=None, beside_game=False, size_limit=None,
                 manual_limit=None, writer=None, exists=os.path.exists,
                 opener=None, sizer=None, log=None):
        """
        :param writer: called with (path, data) to store a manual, so that
            Kodi's virtual filesystem can be used in place of plain files
        """
        self._client = client or regvault.Client()
        self._beside_game = beside_game
        self._size_limit = (
            hashing.DEFAULT_SIZE_LIMIT if size_limit is None else size_limit
        )
        self._manual_limit = (
            self.DEFAULT_MANUAL_LIMIT if manual_limit is None else manual_limit
        )
        self._writer = writer or self._write_file
        self._exists = exists
        self._opener = opener
        self._sizer = sizer
        self._log = log or (lambda message: None)

    @staticmethod
    def _write_file(path, data):
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)

        with open(path, "wb") as handle:
            handle.write(data)

    def fetch_one(self, path):
        """Get the manual for one game.

        :return: a Result. Never raises for an ordinary miss - only a rate
            limit stops a run, and that is raised for the caller to handle.
        """
        have = existing_manual(path, self._exists)
        if have:
            return Result(path, Result.HAVE, os.path.basename(have))

        candidate_systems = systems.candidates(path)
        if not candidate_systems:
            return Result(path, Result.UNKNOWN_SYSTEM)

        try:
            rom_hash = hashing.hash_file(path, self._size_limit,
                                         self._opener, self._sizer)
        except hashing.Skipped as reason:
            return Result(path, Result.SKIPPED, str(reason))

        # The folder hint leads, and the extension's guesses follow. A wrong
        # guess is a 404, so trying a couple costs little.
        for system in candidate_systems:
            try:
                game = self._client.lookup(system, rom_hash)
            except regvault.Unavailable as error:
                return Result(path, Result.FAILED, str(error))

            if game is None:
                continue

            if not game.get("has_manual"):
                title = game.get("title_en") or stem(path)
                return Result(path, Result.NO_MANUAL, title)

            try:
                data = self._client.fetch_manual(system, rom_hash, self._manual_limit)
            except regvault.TooLarge as size:
                return Result(path, Result.SKIPPED, "manual is %s" % size)
            except regvault.Unavailable as error:
                return Result(path, Result.FAILED, str(error))

            if not data:
                return Result(path, Result.NO_MANUAL, game.get("title_en") or "")

            target = destination(path, self._beside_game)

            try:
                self._writer(target, data)
            except OSError as error:
                return Result(path, Result.FAILED, "could not write: %s" % error)

            self._log("fetched %s (%s, %d KB)" % (
                os.path.basename(target), system, len(data) // 1024))

            return Result(path, Result.FETCHED, os.path.basename(target))

        return Result(path, Result.NOT_CATALOGUED, ", ".join(candidate_systems))

    def fetch_many(self, paths, progress=None, cancelled=None):
        """Get manuals for a list of games.

        :param progress: called with (index, total, path, result)
        :param cancelled: called before each game; return True to stop
        :return: the list of Results, which may be shorter if it was stopped
        """
        results = []
        total = len(paths)

        for index, path in enumerate(paths):
            if cancelled and cancelled():
                break

            try:
                result = self.fetch_one(path)
            except regvault.RateLimited as error:
                self._log("stopping: %s" % error)
                results.append(Result(path, Result.FAILED, str(error)))
                break

            results.append(result)

            if progress:
                progress(index + 1, total, path, result)

        return results


def summarise(results):
    """Count the outcomes, for a line worth showing at the end."""
    counts = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1

    return counts
