# Game Master

Runs an annual party night from a laptop plugged into the TV. Everyone joins from their phone by scanning a QR code, Jackbox-style, and then mostly puts the phone away. The app handles the slow parts of the night: drawing games from the hat, picking teams, and keeping score. It works with no internet.

The full plan is in [SPEC.md](SPEC.md).

## Status

**M0 is built:** the TV lobby with a QR code and room code, joining from phones, and staying connected through refreshes, locked phones, Wi-Fi drops and laptop restarts. The game library loads from a YAML file. Next is M1: the draft, rounds, the hat and scoring (SPEC §9).

## Running it (Mac)

1. Get the folder onto the Mac (`git clone`, or download the ZIP).
2. Double-click **`start.command`**. The first run needs internet: it installs [uv](https://docs.astral.sh/uv/), Python and the libraries. After that, no internet is needed.
3. The TV page opens in the browser. Drag it to the TV and go full screen (⌃⌘F).
4. If macOS asks whether to allow incoming connections, say **Allow**, or phones can't join.
5. Phones on the same Wi-Fi scan the QR code.

The Mac stays awake while the window is open. Close the window to stop. Everything is saved as it happens, so starting again picks up where the party left off.

If macOS won't open `start.command` ("unidentified developer"), right-click it, choose **Open**, and confirm once.

**Rental Wi-Fi:** some routers stop devices from reaching each other. If phones can't load the page, bring a cheap travel router and put the laptop and phones on it (SPEC §7).

## Your own games

The repo ships a generic starter list in [`games/starter.yaml`](games/starter.yaml). Put your group's own list in `data/games.yaml` (same format). It's used instead of the starter list on first start and is never committed. Check a file with:

```sh
uv run python -m gamemaster.library check data/games.yaml
```

## Development

```sh
uv sync                                   # install
GM_PORT=8765 uv run python -m gamemaster  # run (TV at /tv, phones at /)
uv run pytest                             # unit + API + WebSocket tests
uv run python tools/smoke.py              # two phones in headless Chromium
```

- **Server:** Python, FastAPI, WebSockets. The SQLite database (`data/gamemaster.db`) is the source of truth. Every action is one transaction, then every screen gets a fresh snapshot.
- **Pages:** plain HTML, CSS and JavaScript in `static/`. No build step, no web fonts, nothing loaded from the internet.
- **Settings (environment):** `GM_PORT` (default 8000), `GM_DATA` (default `./data`), `GM_PUBLIC_URL` to override the address in the QR code.

## Privacy

Everything about a real party (names, scores, your own game list) lives in `data/`, which is gitignored. Examples and tests use made-up names.

## License

MIT
