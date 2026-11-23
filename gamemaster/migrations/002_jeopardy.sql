-- Jeopardy, standalone: two sides, one board at a time (SPEC §6).
-- The clues themselves are copied in from data/clues.db when a board is made,
-- so a game in progress never depends on that file again.

CREATE TABLE jeopardy_game (
    id              INTEGER PRIMARY KEY,
    party_id        INTEGER NOT NULL REFERENCES party(id),
    -- setup: picking categories and names; board: playing clues;
    -- final: Final Jeopardy; done: winner on screen
    status          TEXT NOT NULL DEFAULT 'setup'
                    CHECK (status IN ('setup', 'board', 'final', 'done')),
    difficulty      TEXT NOT NULL DEFAULT 'mixed'
                    CHECK (difficulty IN ('easier', 'mixed', 'harder')),
    left_name       TEXT NOT NULL DEFAULT 'Left',
    right_name      TEXT NOT NULL DEFAULT 'Right',
    -- The clue on screen, if any, and where it is:
    -- open (buzzers live), buzzed (a side is answering), revealed (response shown)
    clue_id         INTEGER REFERENCES jeopardy_clue(id),
    clue_phase      TEXT CHECK (clue_phase IN ('open', 'buzzed', 'revealed')),
    buzzed_side     TEXT CHECK (buzzed_side IN ('left', 'right')),
    -- Final Jeopardy: category (wagers on paper), clue (timer running), revealed
    final_key       TEXT,
    final_category  TEXT,
    final_text      TEXT,
    final_response  TEXT,
    final_phase     TEXT CHECK (final_phase IN ('category', 'clue', 'revealed')),
    final_clue_at   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE jeopardy_category (
    id          INTEGER PRIMARY KEY,
    game_id     INTEGER NOT NULL REFERENCES jeopardy_game(id) ON DELETE CASCADE,
    col         INTEGER NOT NULL,
    source_key  TEXT NOT NULL,       -- which real category it came from, so it never repeats
    level       TEXT NOT NULL CHECK (level IN ('single', 'double')),
    name        TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    UNIQUE (game_id, col)
);

CREATE TABLE jeopardy_clue (
    id           INTEGER PRIMARY KEY,
    category_id  INTEGER NOT NULL REFERENCES jeopardy_category(id) ON DELETE CASCADE,
    row          INTEGER NOT NULL,
    value        INTEGER NOT NULL,
    text         TEXT NOT NULL,
    response     TEXT NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0,
    UNIQUE (category_id, row)
);

-- Every change to a score. Scores are the sum of the rows not undone.
CREATE TABLE jeopardy_score (
    id        INTEGER PRIMARY KEY,
    game_id   INTEGER NOT NULL REFERENCES jeopardy_game(id) ON DELETE CASCADE,
    side      TEXT NOT NULL CHECK (side IN ('left', 'right')),
    delta     INTEGER NOT NULL,
    clue_id   INTEGER REFERENCES jeopardy_clue(id),   -- NULL for Final Jeopardy
    undone    INTEGER NOT NULL DEFAULT 0,
    at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX jeopardy_game_party ON jeopardy_game(party_id);
CREATE INDEX jeopardy_score_game ON jeopardy_score(game_id);
