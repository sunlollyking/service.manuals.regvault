# Game Manuals (REG-Vault)

Fetches game manuals from the [REG-Vault](https://regvault.org) catalogue so
that Kodi's manual viewer can show them.

Games are matched by an MD5 of the ROM itself, so a manual is either the right
one or it is not offered. A ROM that is a different dump, region or revision to
anything catalogued is a miss rather than a wrong answer.

Manuals are written where the viewer already looks: a `manuals` folder beside
the games, or next to each game if you prefer. Nothing in Kodi needs changing.

## Limits worth knowing

- The catalogue holds no manual for every game. Homebrew, hacks and aftermarket
  releases are mostly absent.
- Large disc images are skipped by default: hashing one takes minutes and those
  systems are rarely keyed by it.
- The free tier allows 1,000 lookups a day per address. Requests are paced, and
  a rate limit stops the run rather than being retried around.

Manuals remain the copyright of their publishers. REG-Vault catalogues them as
a preservation archive.
