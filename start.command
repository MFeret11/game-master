#!/bin/bash
# Game Master: double-click this on the Mac to start the party.
#
# First run (at home, with internet): installs uv, Python and the libraries,
# and downloads the Jeopardy clues.
# After that it needs no internet. Keeps the Mac awake while it runs.
# Close this window to stop.

cd "$(dirname "$0")" || exit 1

export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "First run: installing uv (needs internet, takes a minute)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh || {
    echo "Couldn't install uv. Check the internet connection and try again."
    read -r -p "Press Return to close."
    exit 1
  }
fi

PORT="${GM_PORT:-8000}"

# First run: get the Jeopardy clues now, while there's internet (about 80 MB).
if [ ! -f data/clues.db ]; then
  uv run --no-dev --frozen python -m gamemaster.clues || echo "Skipped the clue download. Jeopardy will try again when you make a board."
fi

# Open the Jeopardy page once the server is up.
(
  for _ in $(seq 1 60); do
    if curl -s "http://localhost:$PORT/api/info" >/dev/null 2>&1; then
      open "http://localhost:$PORT/jeopardy"
      exit 0
    fi
    sleep 1
  done
) &

# caffeinate: no display sleep (-d), no idle sleep (-i), no system sleep on power (-s).
# Without it, a sleeping Mac would drop every phone.
GM_PORT="$PORT" caffeinate -dis uv run --no-dev --frozen python -m gamemaster
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "Game Master stopped with an error (code $status)."
  read -r -p "Press Return to close."
fi
