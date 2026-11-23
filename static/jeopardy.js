// Jeopardy on the TV (SPEC §6). The laptop is plugged into the TV and mirrored,
// so this one page is both the big screen and the controls.
//
// Nothing here ever holds a response before it's revealed: the server only
// sends it after Reveal.
//
// Keys:  A = left buzzes   L = right buzzes   Space = reveal
//        R = right   W = wrong   N = no points   Esc = cancel a buzz   U = undo

import { Live, h } from "/static/live.js";

const $ = (id) => document.getElementById(id);
const KEYS = { buzzLeft: "a", buzzRight: "l", reveal: " ", right: "r", wrong: "w", noPoints: "n", clearBuzz: "Escape", undo: "u" };
const DIFFICULTIES = [
  ["easier", "Easier", "Early-round clues"],
  ["mixed", "Mixed", "Half early, half late"],
  ["harder", "Harder", "Late-round clues"],
];

let game = null;        // the latest Jeopardy view from the server
let drawnKey = "";      // what's on screen, so typing in a box isn't wiped by a redraw
let busy = false;
let countdown = null;

// Server calls -----------------------------------------------------------------

async function act(action, extra = {}) {
  if (busy && action !== "buzz") return;
  busy = action === "new";
  if (busy) showToast("Getting a board… (the first time downloads the clues, about a minute)", 60000);
  try {
    const res = await fetch("/api/jeopardy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...extra }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) showToast(body.message || "That didn't work.");
    else if (action === "new") hideToast();
  } catch {
    showToast("Can't reach the server.");
  } finally {
    busy = false;
  }
}

let toastTimer = null;
function showToast(text, ms = 3500) {
  $("toast").textContent = text;
  $("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, ms);
}
function hideToast() {
  $("toast").classList.remove("show");
}

// Sounds (made in the browser, no files) ----------------------------------------

let audio = null;
function beep(freq, seconds, type = "square") {
  try {
    audio = audio || new AudioContext();
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.18, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + seconds);
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + seconds);
  } catch {}
}
const sounds = {
  buzz: () => beep(880, 0.35),
  right: () => { beep(660, 0.15, "triangle"); setTimeout(() => beep(990, 0.3, "triangle"), 150); },
  wrong: () => beep(150, 0.5, "sawtooth"),
  timeUp: () => beep(440, 0.8, "triangle"),
};

// Drawing ----------------------------------------------------------------------

const sideName = (side) => game.sides.find((s) => s.side === side).name;
const money = (n) => (n < 0 ? `−$${Math.abs(n).toLocaleString()}` : `$${n.toLocaleString()}`);

function drawScores() {
  const buzzed = game?.clue?.buzzed;
  $("scores").replaceChildren(
    ...(game
      ? game.sides.map((s) =>
          h("div", { class: `jp-score ${s.side}${buzzed === s.side ? " lit" : ""}` },
            h("div", { class: "jp-score-name" }, s.name),
            h("div", { class: `jp-score-value${s.score < 0 ? " neg" : ""}` }, money(s.score))))
      : []),
  );
  if (game) $("scores").insertBefore(h("div", { class: "jp-logo" }, "Jeopardy!"), $("scores").children[1]);
}

function button(label, onClick, { key, kind = "", disabled = false } = {}) {
  return h("button", { class: `btn ${kind}`, onclick: onClick, disabled },
    label, key ? h("kbd", {}, key === " " ? "Space" : key === "Escape" ? "Esc" : key.toUpperCase()) : null);
}

function viewKey() {
  // Everything that changes what's drawn, minus the countdown.
  return JSON.stringify(game && { ...game, final: game.final && { ...game.final, seconds_left: null } });
}

function draw() {
  drawScores();
  const key = viewKey();
  if (key === drawnKey) return;
  drawnKey = key;
  clearInterval(countdown);

  if (!game) return drawStart();
  if (game.status === "setup") return drawSetup();
  if (game.status === "board" && game.clue) return drawClue();
  if (game.status === "board") return drawBoard();
  if (game.status === "final") return drawFinal();
  return drawWinner();
}

function drawStart() {
  $("main").replaceChildren(
    h("div", { class: "jp-center" },
      h("h1", { class: "jp-big-title" }, "Jeopardy!"),
      h("p", { class: "jp-muted" }, "Real clues, six random categories. Two sides, buzzers on your phones."),
      difficultyPicker(game?.difficulty || "mixed", (d) => act("new", { difficulty: d }), "Pick a difficulty to make a board")),
  );
  $("controls").replaceChildren();
}

function difficultyPicker(current, onPick, label) {
  return h("div", { class: "jp-difficulty" },
    h("div", { class: "jp-label" }, label),
    h("div", { class: "jp-seg" },
      ...DIFFICULTIES.map(([value, name, hint]) =>
        h("button", { class: value === current ? "on" : "", onclick: () => onPick(value) },
          h("b", {}, name), h("small", {}, hint)))));
}

function drawSetup() {
  const nameBox = (side) =>
    h("label", { class: `jp-name-box ${side}` }, side === "left" ? "Left side" : "Right side",
      h("input", {
        value: sideName(side), maxlength: 16, "data-side": side,
        onchange: (e) => act("options", { [`${side}_name`]: e.target.value }),
        onkeydown: (e) => e.key === "Enter" && e.target.blur(),
      }));

  $("main").replaceChildren(
    h("div", { class: "jp-setup" },
      h("div", { class: "jp-setup-cats" },
        h("div", { class: "jp-label" }, "Categories (no clues are shown, so whoever sets up can play)"),
        h("div", { class: "jp-cat-list" },
          ...game.categories.map((c) =>
            h("div", { class: "jp-cat-row" },
              h("div", {}, h("div", { class: "jp-cat-name" }, c.name), c.note ? h("div", { class: "jp-cat-note" }, c.note) : null),
              h("button", { class: "btn ghost small", onclick: () => act("reroll", { col: c.col }), title: "Swap this category" }, "↻ Swap")))),
        difficultyPicker(game.difficulty, (d) => d !== game.difficulty && act("options", { difficulty: d }), "Difficulty (changing it makes a new board)")),
      h("div", { class: "jp-setup-side" },
        h("div", { class: "jp-names" }, nameBox("left"), nameBox("right")),
        h("div", { class: "jp-buzz-join" },
          h("div", { class: "qr" }, h("img", { src: "/qr.svg?to=buzz", alt: "QR code for the phone buzzer" })),
          h("div", {},
            h("div", { class: "jp-label" }, "Phone buzzers"),
            h("div", { class: "jp-buzz-url", id: "buzz-url" }, ""),
            h("p", { class: "jp-muted" }, "Or the laptop keys: A for left, L for right."))))),
  );
  loadBuzzUrl();
  $("controls").replaceChildren(
    button("New board", () => act("new", { difficulty: game.difficulty }), { kind: "ghost" }),
    h("div", { class: "spacer" }),
    button("Start the game", () => act("start")),
  );
}

async function loadBuzzUrl() {
  try {
    const info = await (await fetch("/api/info", { cache: "no-store" })).json();
    const el = $("buzz-url");
    if (el) el.textContent = info.buzz_url.replace(/^https?:\/\//, "");
  } catch {}
}

function drawBoard() {
  const cells = [];
  for (const c of game.categories) {
    cells.push(h("div", { class: "jp-cell head", style: `grid-column:${c.col + 1};grid-row:1` },
      h("span", {}, c.name)));
    c.clues.forEach((clue, i) => {
      cells.push(clue.done
        ? h("div", { class: "jp-cell done", style: `grid-column:${c.col + 1};grid-row:${i + 2}` })
        : h("button", { class: "jp-cell value", style: `grid-column:${c.col + 1};grid-row:${i + 2}`,
            onclick: () => act("open", { clue_id: clue.id }) }, money(clue.value)));
    });
  }
  $("main").replaceChildren(h("div", { class: "jp-board" }, ...cells));
  $("controls").replaceChildren(
    button("Undo last score", () => act("undo"), { key: KEYS.undo, kind: "ghost", disabled: !game.can_undo }),
    h("div", { class: "jp-hint" }, game.clues_left ? `${game.clues_left} clues left · click one` : "Board cleared!"),
    h("div", { class: "spacer" }),
    button("New board", () => confirm("Throw away this board and the scores?") && act("new", { difficulty: game.difficulty }), { kind: "ghost" }),
    button("Final Jeopardy", () => (game.clues_left === 0 || confirm(`Skip the ${game.clues_left} clues left and go to Final Jeopardy?`)) && act("final"),
      { kind: game.clues_left ? "ghost" : "" }),
  );
}

function drawClue() {
  const c = game.clue;
  const status =
    c.phase === "open" ? h("div", { class: "jp-status open" }, "Buzzers open!", h("small", {}, "phones, or A / L")) :
    c.phase === "buzzed" ? h("div", { class: `jp-status buzzed ${c.buzzed}` }, `${sideName(c.buzzed)} buzzed!`, h("small", {}, "one answer, out loud")) :
    h("div", { class: "jp-response" }, h("div", { class: "jp-label" }, "Correct response"), h("div", { class: "jp-response-text" }, c.response));

  $("main").replaceChildren(
    h("div", { class: "jp-clue" },
      h("div", { class: "jp-clue-head" }, h("span", {}, c.category), h("span", { class: "jp-clue-value" }, money(c.value))),
      c.note ? h("div", { class: "jp-cat-note" }, c.note) : null,
      h("div", { class: `jp-clue-text${c.text.length > 160 ? " long" : ""}` }, c.text),
      status),
  );

  const controls = [];
  if (c.phase === "open") {
    controls.push(button("Reveal (nobody knows)", () => act("reveal"), { key: KEYS.reveal, kind: "ghost" }));
  } else if (c.phase === "buzzed") {
    controls.push(button("Cancel buzz", () => act("clear_buzz"), { key: KEYS.clearBuzz, kind: "ghost" }),
      h("div", { class: "spacer" }), button("Reveal", () => act("reveal"), { key: KEYS.reveal }));
  } else if (c.buzzed) {
    controls.push(h("div", { class: "jp-hint" }, `Was ${sideName(c.buzzed)} right?`), h("div", { class: "spacer" }),
      button(`Wrong  −${money(c.value)}`, () => act("judge", { right: false }), { key: KEYS.wrong, kind: "bad" }),
      button(`Right  +${money(c.value)}`, () => act("judge", { right: true }), { key: KEYS.right, kind: "good" }));
  } else {
    controls.push(h("div", { class: "spacer" }), button("No points, back to the board", () => act("no_points"), { key: KEYS.noPoints }));
  }
  $("controls").replaceChildren(...controls);
}

function drawFinal() {
  const f = game.final;
  const parts = [h("div", { class: "jp-label center" }, "Final Jeopardy"), h("div", { class: "jp-final-cat" }, f.category)];
  const controls = [];
  if (f.phase === "category") {
    parts.push(h("p", { class: "jp-final-tip" }, "Each side writes a wager on paper, from $0 up to its score."),
      h("div", { class: "jp-final-limits" }, ...game.sides.map((s) => h("div", { class: s.side }, `${s.name}: up to ${money(f.max_wager[s.side])}`))));
    controls.push(h("div", { class: "spacer" }), button("Show the clue", () => act("final_clue")));
  } else {
    parts.push(h("div", { class: `jp-clue-text${f.text.length > 160 || f.phase === "revealed" ? " long" : ""}` }, f.text));
    if (f.phase === "clue") {
      parts.push(h("div", { class: "jp-timer", id: "timer" }));
      startCountdown(f.seconds_left, f.seconds);
      controls.push(h("div", { class: "jp-hint" }, "Write your answer on paper."), h("div", { class: "spacer" }),
        button("Reveal", () => act("final_reveal"), { key: KEYS.reveal }));
    } else {
      parts.push(h("div", { class: "jp-response" }, h("div", { class: "jp-label" }, "Correct response"), h("div", { class: "jp-response-text" }, f.response)),
        h("div", { class: "jp-final-entry" }, ...game.sides.map((s) => finalEntry(s, f))));
      controls.push(button("Undo last score", () => act("undo"), { kind: "ghost", disabled: !game.can_undo }));
    }
  }
  $("main").replaceChildren(h("div", { class: "jp-clue final" }, ...parts));
  $("controls").replaceChildren(...controls);
}

function finalEntry(s, f) {
  if (f.scored[s.side]) return h("div", { class: `jp-final-side ${s.side}` }, h("b", {}, s.name), h("span", {}, "scored ✓"));
  const input = h("input", { type: "number", min: 0, max: f.max_wager[s.side], step: 100, placeholder: "Wager", inputmode: "numeric" });
  const send = (right) => {
    const wager = Number(input.value || 0);
    if (!Number.isInteger(wager) || wager < 0) return showToast("Type the wager as a whole number.");
    act("final_score", { side: s.side, wager, right });
  };
  return h("div", { class: `jp-final-side ${s.side}` },
    h("b", {}, s.name), h("small", {}, `up to ${money(f.max_wager[s.side])}`), input,
    button("Wrong", () => send(false), { kind: "bad small" }), button("Right", () => send(true), { kind: "good small" }));
}

function startCountdown(secondsLeft, total) {
  const deadline = Date.now() + secondsLeft * 1000;
  const tick = () => {
    const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    const el = $("timer");
    if (!el) return clearInterval(countdown);
    el.textContent = left ? `${left}` : "Time!";
    el.style.setProperty("--done", `${(1 - left / total) * 100}%`);
    el.classList.toggle("up", left === 0);
    if (left === 0) {
      clearInterval(countdown);
      if (secondsLeft > 0) sounds.timeUp();
    }
  };
  tick();
  countdown = setInterval(tick, 250);
}

function drawWinner() {
  const [a, b] = game.sides;
  const tie = a.score === b.score;
  const winner = a.score > b.score ? a : b;
  $("main").replaceChildren(
    h("div", { class: "jp-center" },
      h("div", { class: "jp-label" }, tie ? "It's a tie!" : "Jeopardy champions"),
      h("h1", { class: `jp-big-title ${tie ? "" : winner.side}` }, tie ? `${a.name} & ${b.name}` : winner.name),
      h("p", { class: "jp-muted big" }, `${a.name} ${money(a.score)} · ${b.name} ${money(b.score)}`)),
  );
  $("controls").replaceChildren(
    button("Undo last score", () => act("undo"), { kind: "ghost", disabled: !game.can_undo }),
    h("div", { class: "spacer" }),
    button("New board", () => act("new", { difficulty: game.difficulty })),
  );
}

// Sounds on changes ------------------------------------------------------------

function playChanges(before, after) {
  if (!before || !after || before.id !== after.id) return;
  const was = before.clue, now = after.clue;
  if (now && now.phase === "buzzed" && was?.phase !== "buzzed") sounds.buzz();
  const total = (g) => g.sides.map((s) => s.score);
  const [b0, b1] = total(before), [a0, a1] = total(after);
  if (a0 > b0 || a1 > b1) sounds.right();
  else if (a0 < b0 || a1 < b1) sounds.wrong();
}

// Keys -------------------------------------------------------------------------

document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea") || e.metaKey || e.ctrlKey || e.altKey || !game) return;
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  const c = game.clue;
  const onBoard = game.status === "board";
  const press = {
    [KEYS.buzzLeft]: () => c?.phase === "open" && act("buzz", { side: "left" }),
    [KEYS.buzzRight]: () => c?.phase === "open" && act("buzz", { side: "right" }),
    [KEYS.reveal]: () => (onBoard && c && c.phase !== "revealed" ? act("reveal")
      : game.final?.phase === "clue" ? act("final_reveal") : null),
    [KEYS.right]: () => c?.phase === "revealed" && c.buzzed && act("judge", { right: true }),
    [KEYS.wrong]: () => c?.phase === "revealed" && c.buzzed && act("judge", { right: false }),
    [KEYS.noPoints]: () => c?.phase === "revealed" && !c.buzzed && act("no_points"),
    [KEYS.clearBuzz]: () => c?.phase === "buzzed" && act("clear_buzz"),
    [KEYS.undo]: () => onBoard && !c && game.can_undo && act("undo"),
  }[k];
  if (press) {
    e.preventDefault();
    press();
  }
});

// Live updates -----------------------------------------------------------------

const live = new Live({
  onMessage: (msg) => {
    if (msg.type !== "state") return;
    const before = game;
    game = msg.state.jeopardy;
    playChanges(before, game);
    draw();
  },
  onStatus: (status) => $("banner").classList.toggle("show", status === "offline"),
});
live.start();
