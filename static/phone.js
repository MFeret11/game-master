// A player's phone (SPEC §4, §5.1). M0: join, rejoin, and a calm waiting screen.
//
// The phone keeps only its token (localStorage, with a cookie as backup).
// Everything it shows comes from the server's snapshot, so refreshing,
// locking the phone or losing Wi-Fi puts it right back where it was.

import { Live, h } from "/static/live.js";

const app = document.getElementById("app");
const banner = document.getElementById("banner");

// Storage -----------------------------------------------------------------

const KEY = "gm_token";
const store = {
  get() {
    try {
      const t = localStorage.getItem(KEY);
      if (t) return t;
    } catch {}
    const m = document.cookie.match(/(?:^|; )gm_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  },
  set(token) {
    try { localStorage.setItem(KEY, token); } catch {}
    document.cookie = `${KEY}=${encodeURIComponent(token)}; max-age=${60 * 60 * 48}; path=/; samesite=lax`;
  },
  clear() {
    try { localStorage.removeItem(KEY); } catch {}
    document.cookie = `${KEY}=; max-age=0; path=/`;
  },
};

function roomCode() {
  const fromUrl = new URLSearchParams(location.search).get("code");
  if (fromUrl) {
    try { localStorage.setItem("gm_code", fromUrl.toUpperCase()); } catch {}
    return fromUrl.toUpperCase();
  }
  try { return localStorage.getItem("gm_code") || ""; } catch { return ""; }
}

// State -------------------------------------------------------------------

let snapshot = null;
let me = null;           // my player id, once the server confirms the token
let view = "loading";    // loading | join | taken | confirm | in | signed_out
let pending = null;      // the player a "taken" or "confirm" view is about
let error = "";

const live = new Live({
  token: store.get(),
  onMessage(msg) {
    if (msg.type === "hello") {
      me = msg.you;
      if (me != null) setView("in");
    } else if (msg.type === "unknown_token") {
      store.clear();
      live.token = null;
      me = null;
      setView("join");
    } else if (msg.type === "signed_out") {
      store.clear();
      live.token = null;
      me = null;
      setView("signed_out");
    } else if (msg.type === "state") {
      snapshot = msg.state;
      if (view === "loading") setView(me != null ? "in" : "join");
      else draw();
    }
  },
  onStatus: (() => {
    let t;
    return (status) => {
      clearTimeout(t);
      // Brief blips (a phone waking up) shouldn't flash a red banner.
      if (status === "offline") t = setTimeout(() => banner.classList.add("show"), 1500);
      else banner.classList.remove("show");
    };
  })(),
});
live.start();

function setView(next) {
  if (next !== view) error = "";
  view = next;
  draw(true);
}

// Actions -----------------------------------------------------------------

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

function signedIn({ token, player_id }) {
  store.set(token);
  me = player_id;
  live.setToken(token);
  setView("in");
}

async function join(name, code) {
  try {
    const { ok, data } = await post("/api/join", { name, code });
    if (ok) return signedIn(data);
    if (data.error === "name_taken") {
      pending = { id: data.player_id, name: name.trim() };
      return setView("taken");
    }
    error = data.message || "Couldn't join. Try again.";
  } catch {
    error = "Can't reach the party. Are you on the house Wi-Fi?";
  }
  draw(true);
}

async function rejoin(playerId) {
  try {
    const { ok, data } = await post("/api/rejoin", { player_id: playerId, code: roomCode() });
    if (ok) return signedIn(data);
    error = data.message || "Couldn't rejoin. Try again.";
  } catch {
    error = "Can't reach the party. Are you on the house Wi-Fi?";
  }
  draw(true);
}

// Views -------------------------------------------------------------------

const players = () => (snapshot ? snapshot.players : []);
const nameOf = (id) => players().find((p) => p.id === id)?.name ?? "";

function rejoinList() {
  const list = players();
  if (!list.length) return null;
  return h("div", { class: "stack", id: "rejoin" },
    h("hr"),
    h("p", { class: "note" }, "Already joined on another phone or browser? Tap your name."),
    h("div", { class: "names" },
      list.map((p) => h("button", { type: "button", onclick: () => { pending = p; setView("confirm"); } }, p.name))),
  );
}

const views = {
  loading: () => [h("h1", { class: "brand" }, "Game Master"), h("p", { class: "lede" }, "Connecting…")],

  join() {
    const code = roomCode();
    const name = h("input", { name: "name", autocomplete: "nickname", maxlength: 20, required: true, placeholder: "Your name", autofocus: true });
    const codeInput = h("input", { name: "code", class: "code", maxlength: 4, required: true, value: code, placeholder: "ABCD", autocapitalize: "characters" });
    const button = h("button", { class: "btn", type: "submit" }, "Join the party");
    const form = h("form", {
      onsubmit: async (e) => {
        e.preventDefault();
        button.disabled = true;
        await join(name.value, codeInput.value);
        button.disabled = false;
      },
    },
      h("label", {}, "Name", name),
      code ? null : h("label", {}, "Room code (on the TV)", codeInput),
      error ? h("p", { class: "error" }, error) : null,
      button,
    );
    if (code) {
      codeInput.type = "hidden"; // the QR code filled it in
      form.append(codeInput);
    }
    return [
      h("h1", { class: "brand" }, snapshot?.party.theme || "Game Master"),
      h("p", { class: "lede" }, "Type your name to join. Then you can put your phone away."),
      form,
      rejoinList(),
    ];
  },

  taken: () => [
    h("h1", { class: "brand" }, "Game Master"),
    h("div", { class: "hero" }, h("div", { class: "big" }, nameOf(pending.id) || pending.name), h("div", { class: "muted" }, "is already here. Is that you?")),
    error ? h("p", { class: "error" }, error) : null,
    h("button", { class: "btn", onclick: () => rejoin(pending.id) }, "Yes, that's me"),
    h("button", { class: "btn ghost", onclick: () => setView("join") }, "No, I'll use another name"),
  ],

  confirm: () => [
    h("h1", { class: "brand" }, "Game Master"),
    h("div", { class: "hero" }, h("div", { class: "muted" }, "Rejoin as"), h("div", { class: "big" }, pending.name)),
    h("p", { class: "note" }, "Your other phone or browser will be signed out, and the TV will show that you rejoined."),
    error ? h("p", { class: "error" }, error) : null,
    h("button", { class: "btn", onclick: () => rejoin(pending.id) }, `Yes, I'm ${pending.name}`),
    h("button", { class: "btn ghost", onclick: () => setView("join") }, "Back"),
  ],

  signed_out: () => [
    h("h1", { class: "brand" }, "Game Master"),
    h("div", { class: "hero" }, h("div", { class: "big" }, "Signed out"), h("div", { class: "muted" }, "Someone rejoined as you from another phone.")),
    h("p", { class: "note" }, "If that wasn't you, tap your name to take it back, and tell the room."),
    h("button", { class: "btn", onclick: () => setView("join") }, "OK"),
  ],

  in() {
    const mine = players().find((p) => p.id === me);
    const team = mine && snapshot.teams.find((t) => t.id === mine.team_id);
    const count = players().length;
    return [
      h("h1", { class: "brand" }, snapshot?.party.theme || "Game Master"),
      h("div", { class: "hero" },
        h("div", { class: "muted" }, "You're in"),
        h("div", { class: "big" }, mine ? mine.name : ""),
        h("div", { class: "muted" }, team ? `Team ${team.name}` : "Teams get picked once everyone's here."),
      ),
      h("p", { class: "lede" }, `${count} ${count === 1 ? "person" : "people"} here so far. Phone down, party on. It'll buzz when you're needed.`),
      h("button", { class: "link", onclick: () => { store.clear(); me = null; live.setToken(null); setView("join"); } }, "Not you?"),
    ];
  },
};

function draw(full = false) {
  // While someone types their name, only refresh the rejoin list, so typing isn't lost.
  if (!full && view === "join" && app.querySelector("form")) {
    const old = document.getElementById("rejoin");
    const next = rejoinList();
    if (old && next) old.replaceWith(next);
    else if (old) old.remove();
    else if (next) app.append(next);
    return;
  }
  app.replaceChildren(...views[view]().filter(Boolean));
}

draw(true);
