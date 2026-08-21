# -*- coding: utf-8 -*-
"""Produces the ROM hash the catalogue is keyed by.

REG-Vault keys games on an MD5 of the ROM file itself. That makes a match
exact: either the file is the dump the catalogue knows, or it is not, and
there is no chance of being handed a different game's manual.

The cost is that the hash is per dump. A different region, revision or hack
hashes differently and simply will not be found, which is a miss rather than
a wrong answer.

No Kodi imports here, so it can be tested on its own.
"""

import hashlib
import os
import zipfile

from . import systems

#: Read in chunks so that a large disc image does not have to be held whole
CHUNK_SIZE = 1024 * 1024

#: Hashing a multi-gigabyte disc image costs minutes and, for those systems,
#: rarely matches anything, so files above this are skipped by default
DEFAULT_SIZE_LIMIT = 512 * 1024 * 1024


class Skipped(Exception):
    """Raised when a file will not be hashed, with a reason worth logging."""


def _hash_stream(stream):
    digest = hashlib.md5()

    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)

    return digest.hexdigest()


def _default_open(path):
    return open(path, "rb")


def _default_size(path):
    return os.path.getsize(path)


def _inner_rom(archive):
    """The entry inside a zip that is the game.

    A ROM archive normally holds exactly one game, sometimes beside a text
    file. The largest entry that looks like a game is taken, which is right
    for both the single-entry case and the case with a readme alongside.
    """
    best = None

    for info in archive.infolist():
        if info.is_dir():
            continue

        if not systems.is_probably_game(info.filename):
            continue

        if best is None or info.file_size > best.file_size:
            best = info

    return best


def hash_file(path, size_limit=DEFAULT_SIZE_LIMIT, opener=None, sizer=None):
    """The MD5 of a game, reaching inside a zip when it is one.

    :param opener: called with the path, returning a readable file object.
        Games often live on a share, which plain open() cannot reach, so the
        caller supplies something that can.
    :param sizer: called with the path, returning its size in bytes

    :raises Skipped: when the file will not be hashed, with a reason
    """
    opener = opener or _default_open
    sizer = sizer or _default_size

    try:
        size = sizer(path)
    except OSError as error:
        raise Skipped("cannot be read: %s" % error)

    if size == 0:
        raise Skipped("is empty")

    try:
        stream = opener(path)
    except OSError as error:
        raise Skipped("cannot be read: %s" % error)

    try:
        is_archive = zipfile.is_zipfile(stream)
        stream.seek(0)
    except (OSError, ValueError, AttributeError):
        # Something that cannot be seeked is not an archive we can read
        is_archive = False

    if not is_archive:
        if size_limit and size > size_limit:
            stream.close()
            raise Skipped("is %d MB, above the size limit" % (size // (1024 * 1024)))

        try:
            with stream:
                return _hash_stream(stream)
        except OSError as error:
            raise Skipped("cannot be read: %s" % error)

    # A zipped ROM is catalogued by the hash of the game inside it, not of the
    # archive, so the entry is hashed as it is decompressed
    try:
        with zipfile.ZipFile(stream) as archive:
            entry = _inner_rom(archive)
            if entry is None:
                raise Skipped("holds no recognisable game")

            if size_limit and entry.file_size > size_limit:
                raise Skipped(
                    "holds a %d MB game, above the size limit"
                    % (entry.file_size // (1024 * 1024))
                )

            with archive.open(entry) as inner:
                return _hash_stream(inner)
    except Skipped:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        # RuntimeError is what a password protected entry raises
        raise Skipped("cannot be read: %s" % error)
    finally:
        stream.close()
