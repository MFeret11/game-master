// The TV: display only, nothing to tap (SPEC §4). M0 shows the lobby.

import { Live, h } from "/static/live.js";

const $ = (id) => document.getElementById(id);
const seen = new Set(); // player ids already on screen, so only new ones pop
let firstDraw = true;

async function loadJoinInfo() {
  try {
    const info = await (await fetch("/api/info", { cache: "no-store" })).json();
    $("qr").src = `/qr.svg?code=${info.room_code}`;
    $("join-url").textContent = info.join_url.replace(/^https?:\/\//, "").replace(/\?.*$/, "");
    $("room-code").replaceChildren(...[...info.room_code].map((c) => h("span", {}, c)));
  } catch {
    // The live connection will retry; the next "online" reloads this.
  }
}

function draw(state) {
  const { party, players, events } = state;
  $("title").textContent = party.theme || "Game Master";
  document.title = `${party.theme || "Game Master"} · TV`;

  const awake = players.filter((p) => p.status === "awake").length;
  $("count").textContent = players.length ? `· ${awake}` : "";
  $("chips").replaceChildren(
    ...(players.length
      ? players.map((p) => {
          const isNew = !firstDraw && !seen.has(p.id);
          seen.add(p.id);
          return h("div", { class: `chip${isNew ? " new" : ""}${p.status === "out" ? " out" : ""}` },
            p.status === "out" ? `💤 ${p.name}` : p.name);
        })
      : [h("div", { class: "empty" }, "Nobody yet. Be the first!")]),
  );
  firstDraw = false;

  $("ticker").replaceChildren(
    ...events.slice(0, 4).flatMap((e, i) => [
      ...(i ? [h("span", { class: "sep" }, "•")] : []),
      h("span", { class: i === 0 ? "latest" : "" }, e.text),
    ]),
  );
}

const live = new Live({
  onMessage: (msg) => {
    if (msg.type === "state") draw(msg.state);
  },
  onStatus: (status) => {
    $("banner").classList.toggle("show", status === "offline");
    if (status === "online") loadJoinInfo();
  },
});
live.start();
