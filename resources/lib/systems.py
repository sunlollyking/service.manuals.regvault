# -*- coding: utf-8 -*-
"""Works out which REG-Vault system a game file belongs to.

The catalogue is keyed by system slug plus ROM hash, so a lookup needs both.
Nothing in a ROM file reliably says which machine it is for, so two hints are
used instead: the folder the game sits in, which in most collections is named
after the system, and the file extension.

Neither is certain, so this returns a list of candidates in order of
confidence rather than one answer. Looking a hash up is one cheap request and
a wrong guess simply misses, so trying two or three is better than refusing to
guess at all.

No Kodi imports here, so it can be tested on its own.
"""

import os
import re

# Every system slug the catalogue knows, as returned by /api/v1/systems.
# Kept so that a mapping entry that stops matching anything can be spotted.
KNOWN_SYSTEMS = {
    "3do", "3ds", "amiga", "amigacd32", "amigacdtv", "amstradcpc", "apple2",
    "atari2600", "atari5200", "atari7800", "atari800", "atarist", "atomiswave",
    "c64", "cdi", "channelf", "colecovision", "creativision", "dos",
    "dreamcast", "famicomdisk", "fbneo", "gamecom", "gamecube", "gamegear",
    "gb", "gba", "gbc", "gx4000", "intellivision", "jaguar", "jaguarcd",
    "leapster", "lynx", "mame", "mastersystem", "megadrive", "msx", "msx2",
    "n64", "naomi", "nds", "neogeo", "neogeocd", "nes", "ngp", "ngpc",
    "odyssey2", "palmos", "pc98", "pcengine", "pcenginecd", "pcfx", "pokemini",
    "ps2", "ps3", "psp", "psvita", "psx", "satellaview", "saturn", "sega32x",
    "segacd", "segapico", "sg1000", "sharpx1", "snes", "studio2", "sufami",
    "supergrafx", "supervision", "thomson", "vc4000", "vectrex", "vic20",
    "virtualboy", "vsmile", "wii", "wiiu", "wonderswan", "wonderswancolor",
    "x68000", "xbox", "xbox360", "zxspectrum",
}

# Folder names, reduced by _normalise(), to the system they mean. Collections
# name their folders after the machine far more consistently than they name
# anything else, so this is the stronger of the two hints.
FOLDER_HINTS = {
    "nintendo entertainment system": "nes",
    "nes": "nes",
    "famicom": "nes",
    "famicom disk system": "famicomdisk",
    "super nintendo entertainment system": "snes",
    "super nintendo": "snes",
    "snes": "snes",
    "super famicom": "snes",
    "nintendo 64": "n64",
    "n64": "n64",
    "nintendo gamecube": "gamecube",
    "gamecube": "gamecube",
    "nintendo wii": "wii",
    "wii": "wii",
    "nintendo wii u": "wiiu",
    "wii u": "wiiu",
    "game boy": "gb",
    "gameboy": "gb",
    "game boy color": "gbc",
    "gameboy color": "gbc",
    "game boy advance": "gba",
    "gameboy advance": "gba",
    "nintendo ds": "nds",
    "nintendo 3ds": "3ds",
    "virtual boy": "virtualboy",
    "sega genesis": "megadrive",
    "genesis": "megadrive",
    "sega mega drive": "megadrive",
    "mega drive": "megadrive",
    "megadrive": "megadrive",
    "sega master system": "mastersystem",
    "master system": "mastersystem",
    "sega game gear": "gamegear",
    "game gear": "gamegear",
    "sega cd": "segacd",
    "mega cd": "segacd",
    "sega 32x": "sega32x",
    "32x": "sega32x",
    "sega saturn": "saturn",
    "saturn": "saturn",
    "sega dreamcast": "dreamcast",
    "dreamcast": "dreamcast",
    "sega sg 1000": "sg1000",
    "sony playstation": "psx",
    "playstation": "psx",
    "psx": "psx",
    "ps1": "psx",
    "sony playstation 2": "ps2",
    "playstation 2": "ps2",
    "ps2": "ps2",
    "sony playstation 3": "ps3",
    "playstation 3": "ps3",
    "sony playstation portable": "psp",
    "playstation portable": "psp",
    "psp": "psp",
    "playstation vita": "psvita",
    "microsoft xbox": "xbox",
    "xbox": "xbox",
    "xbox 360": "xbox360",
    "atari 2600": "atari2600",
    "atari 5200": "atari5200",
    "atari 7800": "atari7800",
    "atari 800": "atari800",
    "atari st": "atarist",
    "atari jaguar": "jaguar",
    "atari lynx": "lynx",
    "lynx": "lynx",
    "nec pc engine": "pcengine",
    "pc engine": "pcengine",
    "turbografx 16": "pcengine",
    "turbografx": "pcengine",
    "pc engine cd": "pcenginecd",
    "supergrafx": "supergrafx",
    "pc fx": "pcfx",
    "snk neo geo": "neogeo",
    "neo geo": "neogeo",
    "neogeo": "neogeo",
    "neo geo cd": "neogeocd",
    "neo geo pocket": "ngp",
    "neo geo pocket color": "ngpc",
    "bandai wonderswan": "wonderswan",
    "wonderswan": "wonderswan",
    "wonderswan color": "wonderswancolor",
    "commodore 64": "c64",
    "c64": "c64",
    "commodore amiga": "amiga",
    "amiga": "amiga",
    "commodore vic 20": "vic20",
    "vic 20": "vic20",
    "amstrad cpc": "amstradcpc",
    "sinclair zx spectrum": "zxspectrum",
    "zx spectrum": "zxspectrum",
    "spectrum": "zxspectrum",
    "msx": "msx",
    "msx2": "msx2",
    "sharp x68000": "x68000",
    "x68000": "x68000",
    "nec pc 98": "pc98",
    "pc 98": "pc98",
    "apple ii": "apple2",
    "coleco colecovision": "colecovision",
    "colecovision": "colecovision",
    "mattel intellivision": "intellivision",
    "intellivision": "intellivision",
    "magnavox odyssey 2": "odyssey2",
    "odyssey 2": "odyssey2",
    "gce vectrex": "vectrex",
    "vectrex": "vectrex",
    "fairchild channel f": "channelf",
    "channel f": "channelf",
    "panasonic 3do": "3do",
    "3do": "3do",
    "philips cd i": "cdi",
    "cd i": "cdi",
    "ms dos": "dos",
    "dos": "dos",
    "arcade": "mame",
    "mame": "mame",
    "final burn neo": "fbneo",
    "fbneo": "fbneo",
    "naomi": "naomi",
    "atomiswave": "atomiswave",
    "pokemon mini": "pokemini",
    "watara supervision": "supervision",
    "supervision": "supervision",
}

# File extensions to the systems they can mean, best first. An extension that
# several machines share lists them all; the folder hint usually settles it,
# and if it does not then each is simply tried.
EXTENSION_HINTS = {
    ".nes": ["nes"],
    ".unf": ["nes"],
    ".unif": ["nes"],
    ".fds": ["famicomdisk"],
    ".sfc": ["snes"],
    ".smc": ["snes"],
    ".swc": ["snes"],
    ".fig": ["snes"],
    ".bs": ["satellaview"],
    ".st": ["sufami"],
    ".n64": ["n64"],
    ".z64": ["n64"],
    ".v64": ["n64"],
    ".gcm": ["gamecube"],
    ".rvz": ["gamecube", "wii"],
    ".gcz": ["gamecube", "wii"],
    ".wbfs": ["wii"],
    ".wad": ["wii"],
    ".gb": ["gb"],
    ".gbc": ["gbc"],
    ".gba": ["gba"],
    ".nds": ["nds"],
    ".3ds": ["3ds"],
    ".cia": ["3ds"],
    ".vb": ["virtualboy"],
    ".md": ["megadrive"],
    ".gen": ["megadrive"],
    ".smd": ["megadrive"],
    ".32x": ["sega32x"],
    ".sms": ["mastersystem"],
    ".gg": ["gamegear"],
    ".sg": ["sg1000"],
    ".pce": ["pcengine"],
    ".sgx": ["supergrafx"],
    ".ws": ["wonderswan"],
    ".wsc": ["wonderswancolor"],
    ".ngp": ["ngp"],
    ".ngc": ["ngpc"],
    ".a26": ["atari2600"],
    ".a52": ["atari5200"],
    ".a78": ["atari7800"],
    ".lnx": ["lynx"],
    ".jag": ["jaguar"],
    ".j64": ["jaguar"],
    ".int": ["intellivision"],
    ".col": ["colecovision"],
    ".vec": ["vectrex"],
    ".min": ["pokemini"],
    ".sv": ["supervision"],
    ".d64": ["c64"],
    ".t64": ["c64"],
    ".prg": ["c64"],
    ".adf": ["amiga"],
    ".ipf": ["amiga"],
    ".tap": ["zxspectrum", "c64"],
    ".tzx": ["zxspectrum"],
    ".sna": ["zxspectrum", "amstradcpc"],
    ".z80": ["zxspectrum"],
    ".dsk": ["amstradcpc", "apple2", "pc98"],
    ".rom": ["msx", "colecovision"],
    ".cas": ["msx"],
    ".exe": ["dos"],
    ".cso": ["psp"],
    ".pbp": ["psp"],
    # Disc images say nothing about the machine on their own, so these lean
    # entirely on the folder hint and are only guessed at as a last resort
    ".iso": ["ps2", "psx", "gamecube", "wii", "dreamcast", "psp", "xbox"],
    ".chd": ["psx", "ps2", "saturn", "segacd", "dreamcast", "pcenginecd"],
    ".cue": ["psx", "segacd", "saturn", "pcenginecd", "3do"],
    ".gdi": ["dreamcast"],
    ".cdi": ["dreamcast"],
}

#: Extensions that hold a ROM inside an archive rather than being one
ARCHIVE_EXTENSIONS = {".zip", ".7z"}


def _normalise(name):
    """Reduce a folder name so that spelling and punctuation stop mattering."""
    name = name.lower()
    # Drop anything bracketed, the way collections tag folders
    name = re.sub(r"[\(\[].*?[\)\]]", " ", name)
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return " ".join(name.split())


def from_folder(path):
    """The system a game's folder name suggests, or None.

    Walks upwards, because a game may sit in a subfolder of the one that
    carries the system's name.
    """
    folder = os.path.dirname(path.rstrip("/\\"))

    for _ in range(3):
        if not folder:
            break

        name = _normalise(os.path.basename(folder.rstrip("/\\")))
        if name in FOLDER_HINTS:
            return FOLDER_HINTS[name]

        parent = os.path.dirname(folder.rstrip("/\\"))
        if parent == folder:
            break
        folder = parent

    return None


def from_extension(path):
    """The systems a game's extension can mean, best first."""
    extension = os.path.splitext(path)[1].lower()
    return list(EXTENSION_HINTS.get(extension, []))


def candidates(path, limit=3):
    """The systems to try for a game, best first.

    The folder hint leads when there is one, because it is the more reliable
    of the two, and the extension fills in behind it.
    """
    ordered = []

    folder = from_folder(path)
    if folder:
        ordered.append(folder)

    for system in from_extension(path):
        if system not in ordered:
            ordered.append(system)

    # A slug the catalogue has never heard of can only waste a request
    ordered = [s for s in ordered if s in KNOWN_SYSTEMS]

    return ordered[:limit]


def stem(path):
    """A game's filename with its extension removed."""
    return os.path.splitext(os.path.basename(path))[0]


def is_archive(path):
    return os.path.splitext(path)[1].lower() in ARCHIVE_EXTENSIONS


def is_probably_game(path):
    """Whether a file looks like a game rather than something beside one."""
    extension = os.path.splitext(path)[1].lower()
    return extension in EXTENSION_HINTS or extension in ARCHIVE_EXTENSIONS
