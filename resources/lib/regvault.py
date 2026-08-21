# -*- coding: utf-8 -*-
"""A small client for the REG-Vault catalogue.

Only the two calls the manual fetcher needs are implemented: look a game up by
system and ROM hash, and fetch its manual.

The service publishes a free tier of 1,000 metadata requests a day per address
and asks that it not be scraped in bulk, so requests are paced and a rate
limit response stops the run rather than being retried around.

No Kodi imports here, so it can be tested on its own.
"""

import json
import time
import urllib.error
import urllib.request

BASE_URL = "https://api.regvault.org/api/v1"

#: Identifies the caller, so the service can see what its traffic is
USER_AGENT = "kodi-service.manuals.regvault/0.1.0 (+https://kodi.tv)"

#: The documented burst allowance is 100 requests a minute. Staying under it
#: by a wide margin keeps a large library scan from looking like a scrape.
MIN_SECONDS_BETWEEN_REQUESTS = 1.0

DEFAULT_TIMEOUT = 30


class RateLimited(Exception):
    """The service asked us to stop. Not something to retry around."""


class Unavailable(Exception):
    """The service could not be reached, or answered with something unusable."""


class TooLarge(Exception):
    """The manual is bigger than the caller is willing to store."""

    def __init__(self, size):
        Exception.__init__(self, "%d MB" % (size // (1024 * 1024)))
        self.size = size


class Client(object):
    def __init__(self, timeout=DEFAULT_TIMEOUT, pace=MIN_SECONDS_BETWEEN_REQUESTS):
        self._timeout = timeout
        self._pace = pace
        self._last_request = 0.0

    def _wait_turn(self):
        elapsed = time.time() - self._last_request
        if elapsed < self._pace:
            time.sleep(self._pace - elapsed)
        self._last_request = time.time()

    def _open(self, url):
        self._wait_turn()

        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            return urllib.request.urlopen(request, timeout=self._timeout)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:
                raise RateLimited("the service is rate limiting this address")
            raise Unavailable("HTTP %d" % error.code)
        except (urllib.error.URLError, OSError) as error:
            raise Unavailable(str(error))

    def lookup(self, system, rom_hash):
        """The catalogue entry for a game, or None if it is not known.

        :param system: a REG-Vault system slug
        :param rom_hash: the MD5 of the ROM
        """
        url = "%s/game/%s/%s" % (BASE_URL, system, rom_hash)

        response = self._open(url)
        if response is None:
            return None

        try:
            with response:
                return json.loads(response.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise Unavailable("unreadable answer: %s" % error)

    def fetch_manual(self, system, rom_hash, max_bytes=0):
        """The bytes of a game's manual, or None if there is none.

        The endpoint answers with the document itself, following whatever
        redirect it uses internally.

        :param max_bytes: refuse a manual larger than this, or 0 for no limit.
            Scans are mostly a few megabytes, but the catalogue holds some at
            over a hundred, which is not what someone expects to have pulled
            down on their behalf.
        :raises TooLarge: when the document is above the limit
        """
        url = "%s/game/%s/%s/manual" % (BASE_URL, system, rom_hash)

        response = self._open(url)
        if response is None:
            return None

        with response:
            content_type = (response.headers.get("Content-Type") or "").lower()

            if max_bytes:
                # Checked before reading where the length is declared, so an
                # oversized manual costs nothing to refuse
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise TooLarge(int(declared))

                # Read one byte past the limit, so going over is detectable
                # even when no length was declared
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise TooLarge(len(data))
            else:
                data = response.read()

        if not data:
            return None

        # The catalogue serves manuals as PDFs. Checking rather than trusting
        # the header means an error page cannot be written out as a manual.
        if not data.startswith(b"%PDF"):
            raise Unavailable("expected a PDF, got %s" % (content_type or "no type"))

        return data
