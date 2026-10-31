// Shared by the TV and the phones: a WebSocket that never gives up (SPEC §5.1).
//
// - Reconnects by itself with backoff (0.5 s, 1 s, 2 s ... max 5 s).
// - Reconnects at once when the phone wakes up or the Wi-Fi comes back.
// - Pings every 10 s; a connection that stays silent for 25 s is treated as
//   dead and replaced, which catches Wi-Fi switches the browser misses.
// - Ignores snapshots older than the one on screen.

export class Live {
  constructor({ token = null, onMessage, onStatus }) {
    this.token = token;
    this.onMessage = onMessage;
    this.onStatus = onStatus || (() => {});
    this.version = -1;
    this.attempt = 0;
    this.ws = null;
    this.timer = null;
    this.heartbeat = null;
    this.lastHeard = 0;
  }

  start() {
    this.open();
    const wake = () => {
      const connecting = this.ws && this.ws.readyState === WebSocket.CONNECTING;
      if (document.visibilityState === "visible" && !this.isOpen() && !connecting) this.reconnectNow();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", () => this.reconnectNow());
    window.addEventListener("pageshow", wake);
  }

  isOpen() {
    return this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  setToken(token) {
    this.token = token;
    this.version = -1;
    this.reconnectNow();
  }

  reconnectNow() {
    clearTimeout(this.timer);
    this.attempt = 0;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
    }
    this.open();
  }

  open() {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const query = this.token ? `?token=${encodeURIComponent(this.token)}` : "";
    const ws = new WebSocket(`${scheme}//${location.host}/ws${query}`);
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.lastHeard = Date.now();
      this.onStatus("online");
      clearInterval(this.heartbeat);
      this.heartbeat = setInterval(() => this.beat(), 10000);
    };
    ws.onmessage = (e) => {
      this.lastHeard = Date.now();
      const msg = JSON.parse(e.data);
      if (msg.type === "pong") return;
      if (msg.type === "state") {
        if (msg.state.version < this.version) return;
        this.version = msg.state.version;
      }
      this.onMessage(msg);
    };
    ws.onclose = () => {
      clearInterval(this.heartbeat);
      if (this.ws !== ws) return;
      this.onStatus("offline");
      const wait = Math.min(5000, 500 * 2 ** this.attempt++) + Math.random() * 250;
      this.timer = setTimeout(() => this.open(), wait);
    };
  }

  beat() {
    if (!this.isOpen()) return;
    if (Date.now() - this.lastHeard > 25000) {
      this.ws.close(); // onclose schedules the reconnect
      return;
    }
    this.ws.send(JSON.stringify({ type: "ping" }));
  }
}

// Tiny DOM helper. Text always goes in as text, never as HTML, because names
// come from players' phones.
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "class") el.className = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}
