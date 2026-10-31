# Game Master — Spec

Status: M0 built 2026-10-31 (TV lobby, joining, reconnecting, restart-safe database, game library loader, starter list). Planning continues; M1 not started. Replaces the 2019 AWS CodeStar template that was in this repo.

## 1. The pitch

Game Master is an annual party: eight to twenty-some friends, a costume theme, about ten rounds through the night, and one overall winner who takes the trophy (and a dip in the ocean).

This app runs the boring parts so the night stays in the room:

- **The hat.** Draw the next game at random instead of from a real hat.
- **Teams.** Split the room into teams in seconds.
- **Score.** The people who played a game report the result themselves. Nobody keeps track of anyone else.
- **Jeopardy.** Ready-made boards on any topic, so nobody spends an evening hunting for free trivia online (and everyone can play, because nobody has seen the answers).

A laptop plugged into the TV shows the scoreboard. Everyone joins once from their phone with a room code, Jackbox-style, and then mostly puts the phone away. Phones come out to report a result or buzz in, not to play the night on them.

## 2. Goals and non-goals

**Goals**
- Phones stay in pockets most of the night. Every phone screen is one glance and one or two taps.
- Several games can run at the same time (two 1v1s in different rooms while a team game goes on), and the TV keeps them straight.
- Nothing is lost if someone refreshes, a phone locks, the Wi-Fi drops, or the laptop restarts.
- Runs on a MacBook Air with no internet during the party. Starts with a double-click.
- Ends with exactly one individual winner, even though most games are team games: points qualify you for a winner-takes-all final showdown.

**Non-goals (v1)**
- Playing the games on phones. Flip cup, charades, the balloon, the pencil and the poems all happen in person. The app only records who won.
- Showing creative entries on the TV. Poems and stories are read aloud and performed; the room picks the winner and someone taps it in.
- Voting on an MVP each round. Too slow.
- Accounts, cloud hosting, or anything reachable from the internet.
- Drinking-game content. The game library can hold anything, but the starter list leans non-drinking.

## 3. The night, step by step

1. **Set up.** Plug the laptop into the TV and double-click `start.command`. The TV shows a QR code and a room code.
2. **Join.** Everyone scans the QR code and types their name. The TV lobby fills up as people join.
3. **Set up the night.** Someone types in this year's theme (decided at the last minute, as always) and picks the number of rounds (default 10). The TV takes its title from the theme.
4. **Teams.** Two captains draft their teams, snake order, with the picks showing on the TV (§5.3).
5. **Flags.** Teams make their flags by hand while a countdown runs on the TV, then the **flag ceremony** (§5.3).
6. **Rounds.** Every awake player plays exactly one game per round, following the night's setlist (§5.4). Round 1 is team vs team flip cup to get everyone hyped:
   - **Challenges first.** Anyone can call someone out ("Sam challenges Jordan to Flip Cup"). Those players are booked for the round.
   - **The app fills the round.** It draws games from the hat until everyone else has a game, and the TV shows the plan, e.g. *"Round 4: 3v3 Charades · 2v2 Cornhole · 1v1 Pencil Sharpening · Free-for-all Balloon Pop"*. Anyone can re-roll a slot or swap players, then taps **Go**.
   - Phones buzz with each player's game. Everyone plays, several games at once.
   - Players report results on their phones (§5.5). When every game in the round is settled, the scoreboard updates and the next round starts.
7. **Jeopardy.** At some point, a full Jeopardy round from a board made before the trip (§6).
8. **Final showdown.** Everyone still within reach of first faces off; winner takes all (§5.7).
9. **The end.** The TV crowns the Game Master. Trophy, ocean.

## 4. Roles and screens

| Screen | Where | What it shows |
|---|---|---|
| **TV** (`/tv`) | Laptop browser, full screen on the TV | Lobby with QR code, teams, scoreboard, games in progress, hat reveals, Jeopardy board. Display only, no buttons needed. |
| **Phone** (`/`) | Each player's phone | Join, "you're up", report a result, your score and team. Mostly a calm waiting screen. |
| **Party controls** | Every phone, plus the laptop keyboard | Draw, set up teams, start/cancel games, fix scores, settle disputes, run Jeopardy. |

The night is communal, so there's no single host: **everyone** gets the party controls, tucked behind a "Party" tab so the main phone screen stays simple. That's safe because:
- Every action shows on the TV for a moment ("Sam drew Charades", "Jordan fixed a score"), so nothing happens behind anyone's back.
- Anything can be undone, from any phone.
- No phone ever shows a Jeopardy answer. Answers appear only on the TV, after someone taps Reveal.

## 5. Features

### 5.1 Joining and reconnecting

The hard requirement: **refreshing never breaks anything.**

- On join, the server gives the phone a random player token. The phone keeps it in `localStorage` and a cookie.
- The server holds all game state. A phone holds nothing but its token; on every (re)connect it gets a full snapshot and draws the right screen from it.
- WebSocket connections reconnect automatically with backoff. While disconnected, the phone shows a small "Reconnecting…" banner, not an error page.
- If the token is lost (new browser, cleared data), the player taps their name in a "Rejoin as…" list. The TV shows "Sam rejoined", so a mix-up is visible. Anyone can undo it.
- Opening the app in a second tab is fine: both stay in sync, and taps from either count once.
- A phone that locks or goes quiet stays in the game. Players are never dropped for being offline; going to bed is a separate, deliberate step (§5.8).
- The TV page reconnects the same way. Closing and reopening it loses nothing.
- **Laptop restart:** the server writes state to a small SQLite file on every change (a few writes per round, nothing chatty). On restart, everything comes back: players, teams, scores, games in progress.
- `start.command` runs the server under `caffeinate` so the Mac doesn't sleep and drop everyone.

### 5.2 The hat (game library)

- A game is: name, one-line rules reminder, how the winner is decided (§5.6), the formats it allows, its rule versions, and optional notes.
- **Formats.** The kinds of matchup:
  - **NvN:** 1v1, 2v2, 3v3, and so on, any size.
  - **Room split:** everyone splits into two (or more) sides, e.g. 8v8 flip cup with 16 people. Side size comes from whoever's free.
  - **Team vs team:** two of the night's teams; **all teams:** every team at once.
  - **Free-for-all:** every player for themselves.
  - **Creative:** everyone or each team enters; the winner is voted on or picked by the room (§5.6).
- **Each game lists the formats it allows,** with optional limits. Examples:

  | Game | Allowed formats | Limits |
  |---|---|---|
  | Flip cup | 1v1, 2v2, 3v3, team vs team, room split | none |
  | Balloon pop | free-for-all, 1v1 | max 8 at once (balloons) |
  | Charades | team vs team | at least 3 per side |
  | Pencil sharpening | 1v1, free-for-all | max 6 (pencils) |
  | Short story | creative | none |

  The round filler only picks an allowed format, and at review anyone can switch between that game's allowed formats ("make it 3v3"), never to one it doesn't allow.
- **Rule versions.** A game can have more than one set of rules, e.g. Duel *Classic* and Duel *No beer*. The TV shows which version is being played, and anyone can switch it at review. Each game has a default version; for drinking games the default is the non-drinking one.
- **Every game leaves the hat once it's drawn,** so the night has variety. Anyone can re-draw (the rejected game goes back in), put a game back, or add a new one on the spot.
- A typical library is 15–30 games. Ten rounds at one to three games each fits that, which is why the round filler favors big games (§5.4).
- If the hat runs out, the TV announces it and the hat refills with every game. Games still repeat only after all of them have been played.
- A challenge can name any game in the library, in the hat or not. A challenged game doesn't leave the hat.
- The library is a plain file (`data/games.yaml`) you can edit before the party, plus add/edit in the party controls.
- The repo ships a starter library of generic party games. Your group's own games live in `data/`, which isn't committed.

### 5.3 Teams: the captains' draft

The party usually has **two teams**, picked by a captains' draft. (More teams are allowed; the draft works the same way.)

1. **Captains.** Anyone taps two names. A **Random** button picks two with a reveal, and if the app knows last year's winner and runner-up, it offers them as a suggestion.
2. **Coin flip.** The TV flips a coin to decide who picks first.
3. **Snake draft:** A, B, B, A, A, B… The second captain gets two picks in a row to make up for not going first.
4. **Each pick:** the captain whose turn it is gets the list of remaining players on their phone. They call the name out loud, then tap it. The TV adds the name to their team and moves the arrow to the other captain. Anyone can tap for a captain whose phone is dead.
5. **Undo** the last pick if someone mis-taps.
6. **Names and colors.** Each captain names their team and picks a color.

**Flags and the flag ceremony** (just ceremony, no points):
- Teams make their flags by hand, like always, while the TV runs a countdown (length set by anyone, can be extended).
- **Ceremony mode:** the TV announces each team in turn with its name and color. The team presents its flag to the room.
- Someone snaps a photo of the flag from a phone, and it becomes the team's banner on the scoreboard for the rest of the night.
- Each team can have a walk-out song. It plays only when someone taps it.
- Then Round 1.

The TV during the draft:

```
   ┌─ RED (Captain Sam) ─┐   ┌─ BLUE (Captain Jordan) ─┐
   │ Alex                │   │ Casey                   │
   │ Morgan              │   │                         │
   └─────────────────────┘   └─────────────────────────┘
          Still available: Riley · Taylor · Drew · ...
                 ▶ Jordan's pick
```

**After the draft:**
- With two teams, every NvN game is Red vs Blue, so team pride rides on every match.
- **Late arrivals** go to the smaller team. If the teams are even, the captain who picked second gets them.
- Anyone can move a player between teams (shown on the TV, undoable). Points belong to people, so a move doesn't change anyone's score.
- For a single game, the room can still be split differently (e.g. a big free-for-all) without changing the teams.

### 5.4 Rounds

- The number of rounds is set at the start (default 10). Rounds can be added or dropped during the night. The TV always shows "Round 4 of 10". The final showdown comes after the last round (§5.7).

**The setlist (the night's cadence).** The hat isn't pure random: each round has a slot, and the hat draws only games that fit it.
- Every game is tagged with an **energy** (🔥 hype, ⚡ medium, 🌙 chill) and a **size** (**big**: team vs team or room split; **small**: 1v1, 2v2, groups, free-for-all).
- Each round's slot is an energy plus a size. Default for 10 rounds:

  | Round | Slot | Notes |
  |---|---|---|
  | 1 | 🔥 big | **Opener, pinned:** team vs team flip cup |
  | 2 | 🔥 big | Another big team game, to feel out the teams |
  | 3 | 🌙 small | |
  | 4 | 🔥 small | |
  | 5 | ⚡ big | |
  | 6 | 🌙 small | |
  | 7 | 🔥 big | |
  | 8 | ⚡ small | |
  | 9 | 🌙 big | A good spot for Jeopardy |
  | 10 | 🔥 big | Last regular round, then the showdown |

- A game can be **pinned** to a round (flip cup to round 1). Pinned games skip the draw.
- The setlist is suggested at setup and editable anytime, including mid-night ("we're dragging, make the next one hype").
- If no game left in the hat fits a slot, the hat takes the closest fit and the TV says so.
- **One game per player per round.** That makes it fair: everyone gets exactly one shot at points each round, whether their game was 1v1 or 8v8.
- **Round steps:**
  1. **Challenge window.** Anyone can challenge from their phone: pick an opponent (or opponents, for a 2v2) and a game. The challenged phones get a prompt to accept or decline. Accepted challenges book those players. The window stays open until someone taps **Fill the round**.
  2. **Fill.** The app draws games for everyone who isn't booked:
     - It only draws games that fit the round's slot. Within a slot, while many players are left, it prefers games that take a lot of people (room splits, team vs team, free-for-all). That keeps rounds to one to three games and makes the hat last.
     - For NvN games it picks players who've had the fewest small games, and, when the night has teams, takes each side from a different team.
     - It only draws a game in a format that game allows and that fits the players left (respecting its limits). A 1v1 is never drawn for 5 people unless something else covers the other 3.
     - **Leftovers:** if one or two players can't be placed, they join a side in another game of the round (a 2v1 or a 3v2 is fine at a party) or are added to a free-for-all. Nobody sits out.
  3. **Review.** The TV shows the plan. Anyone can re-roll one game, swap players, switch to another allowed format, or change the rule version. Picks open now (§5.9). Then **Go**.
  4. **Play and report.** Games run at the same time; results come in as each finishes (§5.5).
  5. **Showcase**, if the round has judged games: everyone gathers, entries are performed, the room votes (§5.6).
  6. **Round over** when every game is settled. The TV shows the round's results and the new standings, then opens the next challenge window.
- A game can be cancelled (equipment broke, nobody can find the pencil). Its players get a quick re-draw or join another game.
- **Jeopardy counts as a round:** everyone plays it, by team.

### 5.5 Games in progress and reporting results

- Each game in a round is a **match**, with its players split into sides.
- Several matches can run at once. A player is in exactly one per round.
- The TV has a **"Now playing"** panel listing every running match: game, players or teams, and how long it's been going.
- When a match ends, every player in it gets a phone prompt: **"Who won?"** with each side as a button (and "Tie" where it makes sense).
  - **Everyone agrees:** points are added and the TV celebrates.
  - **Not everyone agrees:** the TV flags "Disputed: Sam vs Jordan". The room argues, then anyone taps the final answer.
  - **Big games (3+ per side):** one tap per side is enough. Once every side has answered and they agree, it's settled.
  - **Judged games** (short story, poem, portrait) skip this prompt and go to the end-of-round showcase and vote instead (§5.6).
  - If not everyone has answered after a minute, anyone can confirm from the answers that are in.
- If someone has to drop out mid-game, their side plays on short, someone swaps in, or the side forfeits.
- Every result can be undone or changed from any phone. The scoreboard is always rebuilt from the list of results, so fixing one fixes everything.

### 5.6 Judged games and voting

Each game says how its winner is decided:

| Type | Examples | How |
|---|---|---|
| **Played out** | Pencil sharpening, coin flip, flip cup | The players report the winner (§5.5). |
| **Judged** | Short story, poem, self-portrait, freestyle rap | Performed live at the end-of-round showcase, then voted on phones. |
| **Room decides** | Quick, low-stakes creative games | The room shouts it out; anyone taps the winner. |

**Judged games, the usual way** (how the party has always done it):
- A judged game is a normal match, e.g. a 1v1 short story or a 2v2 poem. The competitors create it during the round, like any other game.
- **End-of-round showcase.** Once the round's other games are settled, the TV calls everyone together. The entries are performed live, one after another.
- **Everyone else votes:** each person who isn't competing in that match picks **one** winner on their phone. Competitors don't vote in their own match.
- **Votes are secret.** The TV shows only the result, never who voted for whom.
- **Most votes wins.** A tie goes back to the room (shout-off, applause), and anyone taps the winner.
- Voting closes when everyone has voted, or when anyone taps **Close voting** (people who are out don't hold it up).
- With most of the room voting, one person voting against a rival barely moves the result.
- The round ends after the showcase.

**Backup: everyone enters.** For a rare round where everyone (or every team) enters, there's no neutral audience, so the vote changes:
- Each person rates every other entry **1 to 5 stars**. No rating your own entry, or your own team's.
- For each entry, the highest and lowest ratings are dropped and the rest averaged (with 5+ ratings). One spiteful or buddy vote can't decide it.
- Highest trimmed average wins; ties go to the room.

### 5.7 Scoring and the final showdown

Confirmed 2026-10-31:

- Everyone has their own score. Points decide **who makes the final showdown**; the showdown decides the Game Master.
- A team win gives **every member** of the winning team points.
- In any other game, every player on the winning side gets the points (so a 2v2 win scores for both winners). A free-for-all or creative win scores for the individual.
- Every game is worth the same (default 3 for a win, 1 for a tie), because everyone plays one game per round. The values are set once for the party.
- Team totals are shown too, for bragging rights.

**The final showdown** (after the last round):
- **Who's in:** everyone still within reach of first, meaning within one win's worth of points of the leader (default 3). Always at least the top two. The TV builds suspense over the last rounds with a "showdown line" on the scoreboard.
- **The game:** the finalists decide among themselves, like always. Their phones show the library as a helper, and someone taps the pick. If they can't agree, **Draw for us** picks a showdown-worthy game. Format follows the number of finalists (1v1, or a free-for-all for 3+).
- **Winner takes all.** The showdown winner is the Game Master, whatever the points say. Everyone else watches and cheers (the one-game-per-round rule doesn't apply).
- A tie in the showdown means another showdown between the tied players.

### 5.8 Going to bed

- A player taps **I'm out** on their phone, or anyone marks them out from the party controls. The TV shows a 💤 next to their name.
- Out players aren't drawn or challenged, and **keep their points**. They stay on the scoreboard and can still win if nobody passes them.
- One tap brings them back in for the next round.
- If a player is out mid-game, their match handles it as in §5.5.
- If a team gets thin, a **rebalance teams** button moves people between teams (shown on the TV, undoable). Points belong to people, so moving teams doesn't change anyone's score.

### 5.9 Picks (bragging rights)

- During a round's review step, each phone can show an optional card: **"Call it"** with the round's other matches. One tap per match picks a winner. You can't pick your own match. Skipping is fine and nothing nags.
- Picks lock a short moment after **Go**, before games start.
- Correct picks go on a separate **Best guesser** leaderboard, shown at the end of each round and at the end of the night. They **never** count toward the Game Master.
- Can be turned off for the whole party at setup.

### 5.10 The TV scoreboard

- Always on screen: the round number, the scoreboard, the games in progress, and a ticker of recent actions.
- Big type, readable from across the room. Light text on dark.
- Clear moments with an animation: game drawn, result in, dispute, lead change, the final crown.
- Sound only after someone turns it on, never automatically.
- **Later (M3):** the Mario Party look. Points move each player's piece along a board path instead of filling a table.

## 6. Jeopardy

### 6.1 Making boards (at home, before the trip)

- `tools/make_board.py "<topic>"` asks Claude for a full board: 6 categories × 5 clues, plus a Final Jeopardy clue, as JSON. It runs on any computer with internet and an Anthropic API key in `.env` (never committed).
- A second pass asks Claude to check each clue: is the answer correct, unambiguous, and not given away by the category? Doubtful clues get replaced or flagged.
- Boards are saved as JSON in `data/boards/`, readable and hand-editable. Hand-written boards use the same format.
- The output is checked against a schema so a bad response can't break the party.
- Since the theme is decided late, make a few general boards ahead of time, and generate a theme board on site if the Wi-Fi allows.

### 6.2 Playing

- The TV shows the board. The team in control calls out a clue and anyone taps it.
- The clue appears on the TV. Teams answer out loud, the way you do now. (Phone buzzers that pick who rang in first are a later option, §9.)
- Someone taps **Reveal**, then marks right or wrong, and points go to the team (and its members).
- Phones show only the category and value, never the clue text or answer. Those appear on the TV.
- Daily Double and Final Jeopardy with wagers come in M2.

## 7. Tech

- **Server:** Python 3, FastAPI, Uvicorn, WebSockets. One process. The database (§7.1) is the source of truth: every action is one transaction, then the new state goes out to the screens.
- **Pages:** plain HTML, CSS and JavaScript. No build step, no framework.
- **One state, many views:** every change goes through the server, which bumps a version number and sends the new state (or a small update) to every screen. A screen that misses updates simply asks for a full snapshot.
- **Running on the Mac:** `start.command` (double-click) uses [uv](https://docs.astral.sh/uv/) to set up Python and the dependencies the first time (at home, with internet), then starts the server under `caffeinate` and opens `/tv` in the browser. After that first run, no internet is needed.
- **Joining:** the TV shows a QR code with the laptop's local address (e.g. `http://192.168.1.23:8000`). The QR code is generated locally, no web service.
- **Rental Wi-Fi backup:** some rental routers block devices from reaching each other. A MacBook Air can't share its own Wi-Fi as a hotspot, so the backup is a small travel router (about $25) that the laptop and phones all join. No internet needed. Test the house Wi-Fi on arrival.
- **Privacy:** the repo is public. Real names, scores, past winners, your own game list and photos all live in `data/`, which is gitignored. Examples and tests use made-up names.

### 7.1 Data model

SQLite, one file on the laptop (`data/gamemaster.db`, gitignored). Schema changes go in numbered migration files.

| Table | Holds | Lives |
|---|---|---|
| `person` | A friend's name | Across years |
| `game` | The library: name, rules reminder, how the winner is decided (played out / judged / room decides), notes, active flag | Across years |
| `game_format` | Each format a game allows, with its limits (sides, players per side, min/max players) | Across years |
| `game_tag` | Energy (hype / medium / chill), size (big / small), showdown-worthy | Across years |
| `game_version` | A game's rule versions (name, rules text), and which is the default | Across years |
| `party` | One night: theme, rounds planned, points for a win and a tie, status | Per party |
| `player` | A person at this party: phone token (hashed), team, awake/out | Per party |
| `team` | Name, color, captain | Per party |
| `draft_pick` | Draft order: pick number, team, player (for undo and the TV) | Per party |
| `hat` | Each game's state this party: in the hat, or drawn in which round; how many refills | Per party |
| `round` | Number, setlist slot (energy, size, pinned game), status (challenges / review / playing / done), start and end times | Per party |
| `challenge` | Who challenged whom, which game, accepted/declined | Per party |
| `match` | A game in a round: which game, format and rule version, drawn or challenged, status (playing / reporting / disputed / settled / cancelled) | Per party |
| `match_side`, `match_player` | Sides and who's on each | Per party |
| `pick` | A player's "call it" pick for a match (bragging rights only) | Per party |
| `vote` | A vote: voter, match, chosen side (or star rating per entry for everyone-enters rounds). Never shown per person. | Per party |
| `report` | Each player's "who won?" tap | Per party |
| `result` | The settled outcome: winning side or tie, who settled it | Per party |
| `event` | Every action, who did it, when, and how to undo it. Feeds the TV ticker. | Per party |

- **Scores are never stored.** They're added up from `result` every time, so undoing or fixing one result fixes everything.
- **Undo** reverses the event's change and marks the event undone. The ticker shows that too.
- Keeping `person` and `game` across years means next year starts with the game list ready, and the draft can suggest last year's winner and runner-up as captains.

## 8. Testing

- Unit tests for scoring, the hat (no repeats, refills), the snake draft and late arrivals, the round filler (everyone placed exactly once, leftovers, challenges respected), voting (competitors can't vote in their own match, most votes, ties, star trimming for everyone-enters), and the reporting rules (agree / dispute / timeout).
- A **simulated party** test: a script opens a TV plus 16 fake phones, joins, makes teams, plays ten rounds with challenges, sends players to bed and back, refreshes phones at random moments, restarts the server mid-match, and checks that the final scores come out right.
- `tools/smoke.py`: two phones in headless Chromium join, refresh, ride out a server restart, and hand off with "Rejoin as…".
- A real-phone check at home before the trip: your phone, a partner's phone, the MacBook on the home Wi-Fi.

## 9. Milestones

| # | What | Done when |
|---|---|---|
| **M0** | Skeleton: server, TV lobby with QR code, phones join, reconnect after refresh, state survives a restart. `start.command` works on the Mac. | You can join from your phone, refresh, restart the laptop, and still be in. |
| **M1** | The core night: draft, flag ceremony, setlist and rounds (challenges, fill, review), final showdown, hat, teams, games at the same time, phone reporting with disputes, voting on judged games, going to bed, scoring, TV scoreboard, party controls, the final crown. | A full fake party (§8) runs clean, and a short real test with a few phones works. |
| **M2** | Jeopardy: board maker, checker, TV board, play flow, Daily Double, Final Jeopardy. | Two generated boards played end to end. |
| **M3** | Polish: picks and the Best guesser board, Mario Party board look for the scoreboard, theme colors, sounds. | It looks like a party, not a spreadsheet. |
| **M4** | Portfolio: README with screenshots, a demo mode with simulated players for mferet.com, CI. | Recruiters can see it working without a party. |
| **Later** | Phone buzzers for Jeopardy (first-in with lockout), other trivia formats, a bracket for 1v1 tournaments. | |

**For this year's party** (date not set yet): M0 + M1 are the must-haves. M2 if time allows. M3 can grow every year.

## 10. Decisions

Settled 2026-10-31:
- **No single host.** Everyone has the party controls; actions show on the TV and can be undone.
- **Formats:** any NvN, room splits, team vs team, all teams, free-for-all, creative.
- **Scoring:** every player on the winning side gets the points. Points qualify for the final showdown (everyone within one win of first); the showdown winner takes all. Finalists pick the showdown game.
- **Cadence:** a setlist of energy + size slots per round; flip cup opener pinned to round 1.
- **Flag ceremony:** after the draft and flag-making; ceremony only, no points; the flag photo becomes the team banner.
- **Opponents:** both. The app can pick who plays, and players can challenge each other.
- **Teams:** usually two, made by a captains' draft in snake order; captains chosen by the room, at random, or from last year's top two.
- **Rounds:** number set at the start; every awake player plays one game per round; challenges first, then the app fills the rest.
- **Hat:** each game leaves once drawn; refills only when empty. Library is usually 15–30 games.
- **Leftovers** join another game in the round; nobody sits out.
- **Going to bed:** out players keep their points and can come back.
- **Game variants:** each game lists its allowed formats (with limits) and rule versions; non-drinking is the default where there's a choice.
- **Judging:** each game is played out, judged, or room decides. Judged games are performed at an end-of-round showcase; everyone not competing secretly picks one winner, most votes wins. Star ratings with trimming only for rounds where everyone enters.
- **Betting:** optional picks before each round's games start, bragging rights only, never counted toward the Game Master.
- **Database:** SQLite tables as in §7.1; scores always computed from results.
- **No hall of fame.** Past champions are already on the trophy.
- **Party date:** not known yet, so M0 + M1 come first regardless.
