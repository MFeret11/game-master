"""Browser smoke test: two phones in a real (headless) Chromium (SPEC §8).

Starts its own server on a spare port with a throwaway data folder, then:
  1. Phone A joins by name.
  2. Phone A refreshes and is still in.
  3. The server dies: phone A shows "Reconnecting...". The server restarts:
     phone A recovers by itself, still the same player.
  4. Phone B tries the same name and is offered "Is that you?".
  5. Phone B rejoins as that player: phone A is signed out.

Usage:  uv run python tools/smoke.py [path/to/chromium]
Needs Chromium (or Chrome) installed. Not part of `pytest` for that reason.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import ExitStack
from itertools import count
from pathlib import Path

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(fn, what: str, timeout: float = 20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            value = fn()
            if value:
                return value
        except Exception:
            pass
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for: {what}")


class Server:
    def __init__(self, port: int, data: Path):
        self.port, self.data, self.proc = port, data, None

    def start(self):
        env = {**os.environ, "GM_PORT": str(self.port), "GM_DATA": str(self.data)}
        self.proc = subprocess.Popen([sys.executable, "-m", "gamemaster"], cwd=ROOT, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(lambda: urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/info"), "server up")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(10)
            self.proc = None


class Browser:
    """Just enough of the Chrome DevTools Protocol to drive a page."""

    def __init__(self, chromium: str, port: int, workdir: Path):
        self.proc = subprocess.Popen(
            [chromium, "--headless=new", "--no-first-run", "--disable-gpu",
             f"--remote-debugging-port={port}", f"--user-data-dir={workdir / 'profile'}", "about:blank"],
            env={**os.environ, "TMPDIR": str(workdir)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        info = wait_for(lambda: json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version")),
                        "chromium up")
        self.stack = ExitStack()
        self.ws = self.stack.enter_context(connect(info["webSocketDebuggerUrl"], max_size=None))
        self.ids = count(1)

    def call(self, method, session=None, **params):
        msg_id = next(self.ids)
        msg = {"id": msg_id, "method": method, "params": params}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == msg_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def new_phone(self, url: str) -> "Phone":
        # Each phone gets its own browser context: separate storage, like separate devices.
        context = self.call("Target.createBrowserContext")["browserContextId"]
        target = self.call("Target.createTarget", url="about:blank", browserContextId=context)["targetId"]
        session = self.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", session, width=390, height=844,
                  deviceScaleFactor=1, mobile=True)
        phone = Phone(self, session)
        phone.goto(url)
        return phone

    def close(self):
        try:
            self.stack.close()
        finally:
            self.proc.terminate()
            self.proc.wait(10)


class Phone:
    def __init__(self, browser: Browser, session: str):
        self.b, self.session = browser, session

    def js(self, expression: str):
        result = self.b.call("Runtime.evaluate", self.session, expression=expression,
                             awaitPromise=True, returnByValue=True)
        return result.get("result", {}).get("value")

    def goto(self, url: str):
        self.b.call("Page.navigate", self.session, url=url)

    def reload(self):
        self.b.call("Page.reload", self.session)

    def text(self) -> str:
        return self.js("document.body ? document.body.innerText : ''") or ""

    def wait_text(self, *needles: str, timeout: float = 20) -> str:
        return wait_for(lambda: all(n in self.text() for n in needles) and self.text(),
                        f"page to show {needles!r}", timeout)

    def banner_shown(self) -> bool:
        return bool(self.js("document.getElementById('banner').classList.contains('show')"))

    def type_name_and_join(self, name: str):
        self.wait_text("Join the party")
        self.js(f"""(() => {{
            const input = document.querySelector('input[name=name]');
            input.value = {json.dumps(name)};
            document.querySelector('form').requestSubmit();
        }})()""")

    def tap(self, label: str):
        found = self.js(f"""(() => {{
            const b = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === {json.dumps(label)});
            if (b) b.click();
            return !!b;
        }})()""")
        assert found, f"no button labelled {label!r}"


def main() -> int:
    chromium = (sys.argv[1] if len(sys.argv) > 1 else None) or next(
        (c for c in ("chromium", "chromium-browser", "google-chrome") if shutil.which(c)), None)
    if not chromium:
        print("Chromium not found. Pass its path: tools/smoke.py /path/to/chromium")
        return 2

    work = Path(tempfile.mkdtemp(prefix="gm-smoke-"))
    server = Server(free_port(), work / "data")
    browser = None
    try:
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        code = json.load(urllib.request.urlopen(f"{base}/api/info"))["room_code"]
        browser = Browser(chromium, free_port(), work)

        a = browser.new_phone(f"{base}/?code={code}")
        a.type_name_and_join("Avery")
        a.wait_text("You're in", "Avery")
        print("ok  phone A joined")

        a.reload()
        a.wait_text("You're in", "Avery")
        print("ok  refresh keeps phone A in")

        server.stop()
        wait_for(a.banner_shown, "the Reconnecting banner")
        print("ok  server down: phone A shows Reconnecting")
        server.start()
        wait_for(lambda: not a.banner_shown(), "phone A to reconnect", timeout=30)
        a.wait_text("You're in", "Avery")
        print("ok  server back: phone A reconnected by itself as Avery")

        b = browser.new_phone(f"{base}/?code={code}")
        b.type_name_and_join("avery")
        b.wait_text("is already here. Is that you?")
        print("ok  phone B with the same name is asked 'Is that you?'")

        b.tap("Yes, that's me")
        b.wait_text("You're in", "Avery")
        a.wait_text("Signed out")
        print("ok  phone B rejoined as Avery; phone A was signed out")

        print("\nAll good.")
        return 0
    except AssertionError as err:
        print(f"FAIL  {err}")
        return 1
    finally:
        if browser:
            browser.close()
        server.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
