// The phone buzzer (SPEC §6.3). Pick your side once, then one big button.
//
// A buzz goes over the open WebSocket (the fastest path). The server takes the
// first side in and ignores the rest. The phone never sees a clue or an answer.

import { Live, h } from "/static/live.js";

const app = document.getElementById("app");
const SIDE_KEY = "gm_buzz_side";

let game = null;
// A link can pick the side, e.g. /buzz?side=left. Otherwise the phone remembers it.
const fromUrl = new URLSearchParams(location.search).get("side");
let side = ["left", "right"].includes(fromUrl) ? fromUrl : load();
if (fromUrl === side) {
  try { localStorage.setItem(SIDE_KEY, side); } catch {}
}

function load() {
  try { return localStorage.getItem(SIDE_KEY); } catch { return null; }
}
function save(value) {
  side = value;
  try {
    if (value) localStorage.setItem(SIDE_KEY, value);
    else localStorage.removeItem(SIDE_KEY);
  } catch {}
  draw();
}

const names = () => Object.fromEntries((game?.sides || [{ side: "left", name: "Left" }, { side: "right", name: "Right" }])
  .map((s) => [s.side, s.name]));

function draw() {
  if (!side) return drawPick();
  const clue = game?.status === "board" ? game.clue : null;
  const phase = clue?.phase;
  const mine = clue?.buzzed === side;

  let label = "Wait for a clue";
  let state = "idle";
  if (phase === "open") { label = "BUZZ"; state = "live"; }
  else if (phase === "buzzed" && mine) { label = "You're in! Answer out loud"; state = "mine"; }
  else if (phase === "buzzed") { label = `${names()[clue.buzzed]} buzzed first`; state = "theirs"; }
  else if (phase === "revealed") { label = "Answer's up on the TV"; }
  else if (game?.status === "final") { label = "Final Jeopardy: write it on paper"; }

  app.replaceChildren(
    h("div", { class: `buzz-side ${side}` }, names()[side],
      h("button", { class: "link", onclick: () => save(null) }, "switch side")),
    h("button", { class: `buzz-button ${side} ${state}`, onpointerdown: press }, label),
  );
}

function drawPick() {
  app.replaceChildren(
    h("h1", { class: "brand" }, "Buzzer"),
    h("p", { class: "lede" }, "Which side are you on?"),
    ...Object.entries(names()).map(([value, name]) =>
      h("button", { class: `buzz-pick ${value}`, onclick: () => save(value) }, name)),
  );
}

function press(e) {
  e.preventDefault();
  if (game?.clue?.phase !== "open") return;
  if (live.send({ type: "buzz", side })) {
    try { navigator.vibrate?.(60); } catch {}
  }
}

const live = new Live({
  onMessage: (msg) => {
    if (msg.type !== "state") return;
    game = msg.state.jeopardy;
    draw();
  },
  onStatus: (status) => document.getElementById("banner").classList.toggle("show", status === "offline"),
});
draw();
live.start();
