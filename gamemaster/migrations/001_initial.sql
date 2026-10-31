-- Game Master schema, version 1. See SPEC.md §7.1.
-- "Across years" tables have no party_id; everything else belongs to one party.

-- Across years ---------------------------------------------------------------

CREATE TABLE person (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE game (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    rules       TEXT NOT NULL DEFAULT '',
    decided_by  TEXT NOT NULL DEFAULT 'played'
                CHECK (decided_by IN ('played', 'judged', 'room')),
    notes       TEXT NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1
);

-- Each format a game allows, with its limits.
-- kind: nvn | split | team | all_teams | ffa | creative
CREATE TABLE game_format (
    id              INTEGER PRIMARY KEY,
    game_id         INTEGER NOT NULL REFERENCES game(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL
                    CHECK (kind IN ('nvn', 'split', 'team', 'all_teams', 'ffa', 'creative')),
    min_per_side    INTEGER,
    max_per_side    INTEGER,
    min_players     INTEGER,
    max_players     INTEGER,
    UNIQUE (game_id, kind)
);

CREATE TABLE game_tag (
    game_id     INTEGER PRIMARY KEY REFERENCES game(id) ON DELETE CASCADE,
    energy      TEXT NOT NULL CHECK (energy IN ('hype', 'medium', 'chill')),
    size        TEXT NOT NULL CHECK (size IN ('big', 'small')),
    showdown    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE game_version (
    id          INTEGER PRIMARY KEY,
    game_id     INTEGER NOT NULL REFERENCES game(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    rules       TEXT NOT NULL DEFAULT '',
    is_default  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (game_id, name)
);

-- Per party ------------------------------------------------------------------

CREATE TABLE party (
    id              INTEGER PRIMARY KEY,
    room_code       TEXT NOT NULL,
    theme           TEXT NOT NULL DEFAULT '',
    rounds_planned  INTEGER NOT NULL DEFAULT 10,
    points_win      INTEGER NOT NULL DEFAULT 3,
    points_tie      INTEGER NOT NULL DEFAULT 1,
    picks_enabled   INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'lobby',
    -- Bumped on every change, so screens can tell old updates from new.
    version         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE team (
    id          INTEGER PRIMARY KEY,
    party_id    INTEGER NOT NULL REFERENCES party(id),
    name        TEXT NOT NULL,
    color       TEXT NOT NULL,
    captain_id  INTEGER REFERENCES player(id)
);

CREATE TABLE player (
    id          INTEGER PRIMARY KEY,
    party_id    INTEGER NOT NULL REFERENCES party(id),
    person_id   INTEGER NOT NULL REFERENCES person(id),
    -- sha256 of the phone's token. The token itself is never stored.
    token_hash  TEXT NOT NULL UNIQUE,
    team_id     INTEGER REFERENCES team(id),
    status      TEXT NOT NULL DEFAULT 'awake' CHECK (status IN ('awake', 'out')),
    joined_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (party_id, person_id)
);

CREATE TABLE draft_pick (
    id          INTEGER PRIMARY KEY,
    party_id    INTEGER NOT NULL REFERENCES party(id),
    pick_no     INTEGER NOT NULL,
    team_id     INTEGER NOT NULL REFERENCES team(id),
    player_id   INTEGER NOT NULL REFERENCES player(id),
    UNIQUE (party_id, pick_no)
);

CREATE TABLE hat (
    party_id        INTEGER NOT NULL REFERENCES party(id),
    game_id         INTEGER NOT NULL REFERENCES game(id),
    drawn_round_id  INTEGER REFERENCES round(id),
    refills         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (party_id, game_id)
);

CREATE TABLE round (
    id              INTEGER PRIMARY KEY,
    party_id        INTEGER NOT NULL REFERENCES party(id),
    number          INTEGER NOT NULL,
    slot_energy     TEXT,
    slot_size       TEXT,
    pinned_game_id  INTEGER REFERENCES game(id),
    status          TEXT NOT NULL DEFAULT 'challenges'
                    CHECK (status IN ('challenges', 'review', 'playing', 'showcase', 'done')),
    started_at      TEXT,
    ended_at        TEXT,
    UNIQUE (party_id, number)
);

CREATE TABLE challenge (
    id              INTEGER PRIMARY KEY,
    round_id        INTEGER NOT NULL REFERENCES round(id),
    challenger_id   INTEGER NOT NULL REFERENCES player(id),
    game_id         INTEGER NOT NULL REFERENCES game(id),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'declined', 'cancelled'))
);

CREATE TABLE challenge_target (
    challenge_id    INTEGER NOT NULL REFERENCES challenge(id) ON DELETE CASCADE,
    player_id       INTEGER NOT NULL REFERENCES player(id),
    PRIMARY KEY (challenge_id, player_id)
);

CREATE TABLE match (
    id              INTEGER PRIMARY KEY,
    round_id        INTEGER NOT NULL REFERENCES round(id),
    game_id         INTEGER NOT NULL REFERENCES game(id),
    format_kind     TEXT NOT NULL,
    version_id      INTEGER REFERENCES game_version(id),
    source          TEXT NOT NULL DEFAULT 'drawn' CHECK (source IN ('drawn', 'challenge', 'showdown')),
    status          TEXT NOT NULL DEFAULT 'playing'
                    CHECK (status IN ('playing', 'reporting', 'disputed', 'voting', 'settled', 'cancelled')),
    started_at      TEXT,
    ended_at        TEXT
);

CREATE TABLE match_side (
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER NOT NULL REFERENCES match(id) ON DELETE CASCADE,
    side_no     INTEGER NOT NULL,
    team_id     INTEGER REFERENCES team(id),
    UNIQUE (match_id, side_no)
);

CREATE TABLE match_player (
    side_id     INTEGER NOT NULL REFERENCES match_side(id) ON DELETE CASCADE,
    player_id   INTEGER NOT NULL REFERENCES player(id),
    PRIMARY KEY (side_id, player_id)
);

CREATE TABLE pick (
    match_id    INTEGER NOT NULL REFERENCES match(id),
    player_id   INTEGER NOT NULL REFERENCES player(id),
    side_id     INTEGER NOT NULL REFERENCES match_side(id),
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE report (
    match_id        INTEGER NOT NULL REFERENCES match(id),
    player_id       INTEGER NOT NULL REFERENCES player(id),
    winner_side_id  INTEGER REFERENCES match_side(id),   -- NULL means "tie"
    at              TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (match_id, player_id)
);

-- One pick per voter in the usual vote; one row per entry for star ratings.
CREATE TABLE vote (
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER NOT NULL REFERENCES match(id),
    voter_id    INTEGER NOT NULL REFERENCES player(id),
    side_id     INTEGER NOT NULL REFERENCES match_side(id),
    stars       INTEGER CHECK (stars BETWEEN 1 AND 5),
    UNIQUE (match_id, voter_id, side_id)
);

CREATE TABLE result (
    match_id        INTEGER PRIMARY KEY REFERENCES match(id),
    winner_side_id  INTEGER REFERENCES match_side(id),   -- NULL means "tie"
    settled_by      INTEGER REFERENCES player(id),       -- NULL when everyone agreed
    at              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every action. Feeds the TV ticker and powers undo.
CREATE TABLE event (
    id          INTEGER PRIMARY KEY,
    party_id    INTEGER NOT NULL REFERENCES party(id),
    at          TEXT NOT NULL DEFAULT (datetime('now')),
    player_id   INTEGER REFERENCES player(id),
    kind        TEXT NOT NULL,
    text        TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '{}',
    undone      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX event_party ON event (party_id, id);
CREATE INDEX player_party ON player (party_id);
