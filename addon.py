# -*- coding: utf-8 -*-
"""Answers Kodi's find-a-manual dialog from the REG-Vault catalogue.

Kodi calls this the way it calls a subtitle service - as a plugin, with a
directory listing for an answer:

  plugin://service.manuals.regvault/?action=search&path=<game>&title=<name>

The dialog hands over the game's path and leaves the matching to us, so the
ROM is hashed here rather than in Kodi. Each result's path is the manual
itself, which Kodi copies to wherever it wants it.

Everything that can be reasoned about without Kodi lives in resources/lib and
is tested on its own. This file is only the part that has to talk to Kodi.
"""

import sys
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

sys.path.insert(0, xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("path")))

from resources.lib import hashing  # noqa: E402
from resources.lib import regvault  # noqa: E402
from resources.lib import systems  # noqa: E402

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1


def log(message, level=xbmc.LOGINFO):
    xbmc.log("%s: %s" % (ADDON_ID, message), level)


def setting_int(name, default):
    try:
        value = ADDON.getSettingInt(name)
        return default if value is None else value
    except (TypeError, ValueError, RuntimeError):
        return default


class VfsStream(object):
    """A readable, seekable view of a file through Kodi's filesystem.

    Games commonly live on a share, which plain open() cannot reach. This is
    enough of a file object for hashing, and for zipfile to read a zipped ROM.
    """

    def __init__(self, path):
        self._file = xbmcvfs.File(path)
        self._position = 0

    def read(self, size=-1):
        data = bytes(
            self._file.readBytes(size) if size and size > 0 else self._file.readBytes()
        )
        self._position += len(data)
        return data

    def seek(self, offset, whence=0):
        self._position = self._file.seek(offset, whence)
        return self._position

    def tell(self):
        return self._position

    def close(self):
        self._file.close()

    def seekable(self):
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
        return False


def vfs_open(path):
    return VfsStream(path)


def vfs_size(path):
    handle = xbmcvfs.File(path)
    try:
        return handle.size()
    finally:
        handle.close()


def search(params):
    """List whatever manuals the catalogue holds for one game."""
    path = params.get("path", "")

    if not path:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    try:
        rom_hash = hashing.hash_file(
            path,
            setting_int("rom_size_limit", 512) * 1024 * 1024,
            opener=vfs_open,
            sizer=vfs_size,
        )
    except hashing.Skipped as reason:
        log("not searching for %s: %s" % (path, reason))
        xbmcplugin.endOfDirectory(HANDLE)
        return

    client = regvault.Client()

    # The folder name is the better hint at which machine a game is for, and
    # the extension follows it. A wrong guess is only a 404, so each is tried.
    for system in systems.candidates(path):
        try:
            game = client.lookup(system, rom_hash)
        except (regvault.Unavailable, regvault.RateLimited) as error:
            log("search failed: %s" % error, xbmc.LOGWARNING)
            break

        if not game:
            continue

        if not game.get("has_manual"):
            # The game is catalogued but has no manual, so the remaining
            # candidate systems cannot help either
            break

        item = xbmcgui.ListItem(label=game.get("title_en") or systems.stem(path))
        item.setLabel2(str(game.get("year") or system))

        # The endpoint answers with the document, so Kodi can copy from it
        url = "%s/game/%s/%s/manual" % (regvault.BASE_URL, system, rom_hash)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, False)
        break

    xbmcplugin.endOfDirectory(HANDLE)


def main():
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}

    if params.get("action") == "search":
        search(params)
        return

    # There is nothing to browse: this add-on exists to answer Kodi, not to be
    # opened on its own
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


if __name__ == "__main__":
    main()
