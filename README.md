# Game Master

Runs an annual party night from a laptop plugged into the TV. Everyone joins from their phone by scanning a QR code, Jackbox-style, and then mostly puts the phone away. The app handles the slow parts of the night: drawing games from the hat, picking teams, and keeping score. First up: a Jeopardy game with real clues and phone buzzers.

The full plan is in [SPEC.md](SPEC.md).

## Status

**Jeopardy is built** (SPEC §6): two sides, a board of six random real categories, phone buzzers that lock out the slower side, the laptop running the board, and Final Jeopardy with wagers. The rest of the night runs by hand this year.

**M0 is built:** the TV lobby with a QR code and room code, joining from phones, and staying connected through refreshes, locked phones, Wi-Fi drops and laptop restarts. The game library loads from a YAML file. M1 (the draft, rounds, the hat and scoring) comes later (SPEC §9).

## Playing Jeopardy

The laptop is plugged into the TV with the screen mirrored, so the Jeopardy page is both the big screen and the controls.

1. Open `/jeopardy` (start.command opens it for you). Pick a difficulty: **Easier** (early-round clues), **Mixed** (the default: half early, half late) or **Harder**.
2. The setup screen shows the six category names only, never clues, so whoever sets up can still play. **Swap** any category nobody would enjoy. Name the two sides.
3. Each side scans the QR code to open the buzzer on their phones (or uses the laptop keys: **A** for left, **L** for right). **Start the game.**
4. Click a value. The clue goes up and the buzzers open. The first side in gets **one** answer, out loud.
5. **Reveal** (Space) shows the correct response. Then **Right** (R, +value) or **Wrong** (W, −value). If nobody buzzed, **No points** (N). **Esc** cancels an accidental buzz; **U** undoes the last score.
6. **Final Jeopardy** whenever you like (parties run late): each side writes a wager on paper, the clue gets 30 seconds, then enter each side's wager and whether they got it.

The clues are real *Jeopardy!* clues from a public dataset ([jwolle1/jeopardy_clue_dataset](https://github.com/jwolle1/jeopardy_clue_dataset)): regular episodes since 2015, full categories only, nothing that needs a picture or video. They're downloaded the first time (about 80 MB, kept as `data/clues.db`) and never committed. To get them ahead of time:

```sh
uv run python -m gamemaster.clues
```

Categories never repeat from one board to the next.

## Running it (Mac)

1. Get the folder onto the Mac (`git clone`, or download the ZIP).
2. Double-click **`start.command`**. The first run needs internet: it installs [uv](https://docs.astral.sh/uv/), Python and the libraries, and downloads the Jeopardy clues. After that, no internet is needed.
3. The Jeopardy page opens in the browser. Mirror the screen to the TV and go full screen (⌃⌘F).
4. If macOS asks whether to allow incoming connections, say **Allow**, or phones can't join.
5. Phones on the same Wi-Fi scan the QR code.

The Mac stays awake while the window is open. Close the window to stop. Everything is saved as it happens, so starting again picks up where the party left off.

If macOS won't open `start.command` ("unidentified developer"), right-click it, choose **Open**, and confirm once.

**Wi-Fi:** some routers stop devices from reaching each other. If phones can't load the page, turn on a phone's hotspot and put the laptop and the other phones on it (SPEC §7).

## Your own games

The repo ships a generic starter list in [`games/starter.yaml`](games/starter.yaml). Put your group's own list in `data/games.yaml` (same format). It's used instead of the starter list on first start and is never committed. Check a file with:

```sh
uv run python -m gamemaster.library check data/games.yaml
```

## Development

```sh
uv sync                                   # install
GM_PORT=8765 uv run python -m gamemaster  # run (Jeopardy at /jeopardy, buzzers at /buzz, lobby at /tv)
uv run pytest                             # unit + API + WebSocket tests
uv run python tools/smoke.py              # two phones in headless Chromium
```

- **Server:** Python, FastAPI, WebSockets. The SQLite database (`data/gamemaster.db`) is the source of truth. Every action is one transaction, then every screen gets a fresh snapshot.
- **Pages:** plain HTML, CSS and JavaScript in `static/`. No build step, no web fonts, nothing loaded from the internet.
- **Settings (environment):** `GM_PORT` (default 8000), `GM_DATA` (default `./data`), `GM_PUBLIC_URL` to override the address in the QR code.

## Privacy

Everything about a real party (names, scores, your own game list) and the downloaded Jeopardy clues live in `data/`, which is gitignored. Examples and tests use made-up names.

## License

MIT
