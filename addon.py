# -*- coding: utf-8 -*-
"""Kodi entry point for the manual fetcher.

Everything that can be reasoned about without Kodi lives in resources/lib and
is tested on its own. This file is the part that has to talk to Kodi: finding
the game sources, listing them, showing progress, and writing through the
virtual filesystem so that network shares work.

Two entry points:

  plugin://service.manuals.regvault/
      A menu: fetch manuals for a source, or for all of them.

  plugin://service.manuals.regvault/?action=search&system=&hash=&title=
      Returns the manuals found for one game as a directory listing. Nothing
      uses this yet - it is the shape a provider would be called with if Kodi
      grows a manuals dialog, and it costs nothing to answer now.
"""

import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ElementTree

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

sys.path.insert(0, xbmcvfs.translatePath(
    xbmcaddon.Addon().getAddonInfo("path")))

from resources.lib import fetcher  # noqa: E402
from resources.lib import hashing  # noqa: E402
from resources.lib import regvault  # noqa: E402
from resources.lib import systems  # noqa: E402

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1


def log(message, level=xbmc.LOGINFO):
    xbmc.log("%s: %s" % (ADDON_ID, message), level)


def notify(message, time=6000):
    xbmcgui.Dialog().notification(ADDON_NAME, message, xbmcgui.NOTIFICATION_INFO, time)


def setting_bool(name, default=False):
    try:
        return ADDON.getSettingBool(name)
    except (TypeError, ValueError, RuntimeError):
        return default


def setting_int(name, default):
    try:
        value = ADDON.getSettingInt(name)
        return default if value is None else value
    except (TypeError, ValueError, RuntimeError):
        return default


def json_rpc(method, params=None):
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        request["params"] = params

    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except ValueError:
        return {}


def _sources_from_jsonrpc():
    """Game sources as Kodi reports them, or None if it will not report them.

    Files.GetSources only learned about games recently. Older builds reject
    the media type outright, which is what the empty answer here means.
    """
    answer = json_rpc("Files.GetSources", {"media": "games"})

    if "error" in answer:
        return None

    sources = answer.get("result", {}).get("sources", []) or []

    return [(s.get("label") or s.get("file"), s.get("file")) for s in sources
            if s.get("file")]


def _sources_from_file():
    """Game sources read straight out of sources.xml.

    Kodi stores them whether or not JSON-RPC will hand them over, so this is
    what makes the add-on work on a build without that fix.
    """
    path = xbmcvfs.translatePath("special://profile/sources.xml")

    if not xbmcvfs.exists(path):
        return []

    try:
        handle = xbmcvfs.File(path)
        try:
            document = ElementTree.fromstring(handle.readBytes())
        finally:
            handle.close()
    except (ElementTree.ParseError, OSError) as error:
        log("cannot read sources.xml: %s" % error, xbmc.LOGWARNING)
        return []

    games = document.find("games")
    if games is None:
        return []

    found = []
    for source in games.findall("source"):
        name = source.findtext("name") or ""
        for element in source.findall("path"):
            if element.text:
                found.append((name or element.text, element.text))

    return found


def game_sources():
    """The folders Kodi has been told hold games.

    Uses Kodi's own list rather than asking the user to point at a folder, so
    that the add-on works against whatever is already set up.
    """
    sources = _sources_from_jsonrpc()

    if sources is None:
        log("Files.GetSources has no games media type, reading sources.xml")
        sources = _sources_from_file()

    return sources


def list_games(root, limit=0):
    """Every game file under a folder.

    Walks with Kodi's filesystem rather than os.walk, so that shares and
    anything else behind the virtual filesystem are included.
    """
    found = []
    pending = [root]

    while pending:
        folder = pending.pop(0)

        try:
            directories, files = xbmcvfs.listdir(folder)
        except OSError as error:
            log("cannot list %s: %s" % (folder, error), xbmc.LOGWARNING)
            continue

        for name in files:
            path = os.path.join(folder, name)
            if systems.is_probably_game(path):
                found.append(path)

                if limit and len(found) >= limit:
                    return found

        for name in directories:
            # Manuals live in here; there are no games to find
            if name.lower() == fetcher.MANUAL_SUBFOLDER:
                continue
            pending.append(os.path.join(folder, name))

    return found


def vfs_writer(path, data):
    """Store a manual through Kodi's filesystem."""
    folder = os.path.dirname(path)
    if folder and not xbmcvfs.exists(folder + "/"):
        if not xbmcvfs.mkdirs(folder):
            raise OSError("could not create %s" % folder)

    handle = xbmcvfs.File(path, "w")
    try:
        if not handle.write(bytearray(data)):
            raise OSError("could not write %s" % path)
    finally:
        handle.close()


def vfs_exists(path):
    return xbmcvfs.exists(path)


class VfsStream(object):
    """A readable, seekable view of a file through Kodi's filesystem.

    Games commonly live on a share, which plain open() cannot reach. This is
    enough of a file object for hashing and for zipfile to read an archive.
    """

    def __init__(self, path):
        self._file = xbmcvfs.File(path)
        self._position = 0

    def read(self, size=-1):
        data = bytes(self._file.readBytes(size) if size and size > 0
                     else self._file.readBytes())
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


def build_fetcher():
    return fetcher.Fetcher(
        beside_game=setting_bool("beside_game"),
        size_limit=setting_int("rom_size_limit", 512) * 1024 * 1024,
        manual_limit=setting_int("manual_size_limit", 32) * 1024 * 1024,
        writer=vfs_writer,
        exists=vfs_exists,
        opener=vfs_open,
        sizer=vfs_size,
        log=log,
    )


def run_scan(roots):
    """Fetch manuals for every game under the given folders."""
    progress = xbmcgui.DialogProgress()
    # "Game Manuals", "Looking for games…"
    progress.create(ADDON_NAME, ADDON.getLocalizedString(32010))

    games = []
    for root in roots:
        if progress.iscanceled():
            break
        games.extend(list_games(root))

    if not games:
        progress.close()
        # "No games found in your sources"
        notify(ADDON.getLocalizedString(32011))
        return

    log("scanning %d game(s)" % len(games))

    counts = {}

    def on_progress(index, total, path, result):
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
        percent = int(index * 100 / total) if total else 0

        progress.update(
            percent,
            "%s\n%s: %s" % (os.path.basename(path), result.outcome, result.detail),
        )

    results = build_fetcher().fetch_many(
        games,
        progress=on_progress,
        cancelled=progress.iscanceled,
    )

    progress.close()

    fetched = counts.get(fetcher.Result.FETCHED, 0)
    # "{0} manuals downloaded, {1} games checked"
    notify(ADDON.getLocalizedString(32012).format(fetched, len(results)))

    log("finished: %s" % fetcher.summarise(results))


def menu():
    """The add-on's own listing."""
    sources = game_sources()

    if sources:
        # "Fetch manuals for all game sources"
        add_action(ADDON.getLocalizedString(32001), {"action": "scan"})

        for label, path in sources:
            add_action(
                # "Fetch manuals for {0}"
                ADDON.getLocalizedString(32002).format(label),
                {"action": "scan", "path": path},
            )
    else:
        # "No game sources are set up in Kodi"
        add_action(ADDON.getLocalizedString(32003), {"action": "none"})

    xbmcplugin.endOfDirectory(HANDLE)


def add_action(label, params, is_folder=False):
    url = "plugin://%s/?%s" % (ADDON_ID, urllib.parse.urlencode(params))
    item = xbmcgui.ListItem(label=label)
    item.setArt({"icon": "DefaultAddonProgram.png"})
    xbmcplugin.addDirectoryItem(HANDLE, url, item, is_folder)


def search(params):
    """Answer a per-game search with whatever manuals were found.

    This is how Kodi's find-a-manual dialog calls a provider. It hands over
    the game's path and leaves the matching to us, which is what lets this
    add-on match on the ROM's hash while another might only compare titles.

    Each result's path is something Kodi can copy from, so the dialog does not
    need to know anything about this service.
    """
    path = params.get("path", "")
    rom_hash = params.get("hash", "")
    system = params.get("system", "")

    if path and not rom_hash:
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

    if not rom_hash:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    candidates = [system] if system else systems.candidates(path)

    client = regvault.Client()

    for candidate in candidates:
        try:
            game = client.lookup(candidate, rom_hash)
        except (regvault.Unavailable, regvault.RateLimited) as error:
            log("search failed: %s" % error, xbmc.LOGWARNING)
            break

        if not game:
            continue

        if not game.get("has_manual"):
            # The game is known but has no manual, so the other candidate
            # systems cannot help either
            break

        title = game.get("title_en") or fetcher.stem(path)
        year = game.get("year")

        item = xbmcgui.ListItem(label=title)
        item.setLabel2(str(year) if year else candidate)
        item.setProperty("system", candidate)
        item.setProperty("hash", rom_hash)

        # The endpoint answers with the document itself, so Kodi can copy
        # straight from it
        url = "%s/game/%s/%s/manual" % (regvault.BASE_URL, candidate, rom_hash)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, False)
        break

    xbmcplugin.endOfDirectory(HANDLE)


def main():
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    action = params.get("action")

    if action == "scan":
        path = params.get("path")
        roots = [path] if path else [p for _, p in game_sources()]
        run_scan(roots)

        # The scan is an action, not a listing, so nothing is returned
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False, updateListing=False)
        return

    if action == "search":
        search(params)
        return

    if action == "none":
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    menu()


if __name__ == "__main__":
    main()
