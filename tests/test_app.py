"""End-to-end through HTTP and real WebSocket connections (SPEC §5.1)."""

import pytest
from fastapi.testclient import TestClient

from gamemaster.app import create_app


def make_client(data_dir):
    return TestClient(create_app(data_dir=data_dir, port=8765))


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def code(client):
    return client.get("/api/info").json()["room_code"]


def join(client, name):
    res = client.post("/api/join", json={"name": name, "code": code(client)})
    assert res.status_code == 200, res.text
    return res.json()


def read_until(ws, kind):
    while True:
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg


def test_pages_and_qr_are_served(client):
    assert "Game Master" in client.get("/tv").text
    assert client.get("/").status_code == 200
    qr = client.get("/qr.svg")
    assert qr.headers["content-type"].startswith("image/svg+xml")
    # Browsers only draw an SVG <img> that declares the SVG namespace.
    assert 'xmlns="http://www.w3.org/2000/svg"' in qr.text
    assert client.get("/static/live.js").status_code == 200


def test_join_needs_the_room_code(client):
    res = client.post("/api/join", json={"name": "Sam", "code": "ZZZZ"})
    assert res.status_code == 400 and res.json()["error"] == "bad_code"


def test_tv_sees_players_join_live(client):
    with client.websocket_connect("/ws") as tv:
        assert read_until(tv, "hello")["you"] is None
        assert read_until(tv, "state")["state"]["players"] == []
        join(client, "Sam")
        state = read_until(tv, "state")["state"]
        assert [p["name"] for p in state["players"]] == ["Sam"]
        assert state["events"][0]["text"] == "Sam joined"


def test_refresh_reconnects_as_the_same_player(client):
    me = join(client, "Jordan")
    for _ in range(3):  # three refreshes
        with client.websocket_connect(f"/ws?token={me['token']}") as phone:
            assert read_until(phone, "hello")["you"] == me["player_id"]


def test_two_tabs_with_the_same_token_both_work(client):
    me = join(client, "Casey")
    with client.websocket_connect(f"/ws?token={me['token']}") as a, \
         client.websocket_connect(f"/ws?token={me['token']}") as b:
        assert read_until(a, "hello")["you"] == read_until(b, "hello")["you"] == me["player_id"]


def test_unknown_token_is_told_to_join_again(client):
    with client.websocket_connect("/ws?token=not-a-real-token") as phone:
        assert phone.receive_json()["type"] == "unknown_token"
        assert read_until(phone, "hello")["you"] is None


def test_name_taken_offers_rejoin(client):
    first = join(client, "Riley")
    res = client.post("/api/join", json={"name": "riley", "code": code(client)})
    assert res.status_code == 409
    assert res.json()["error"] == "name_taken" and res.json()["player_id"] == first["player_id"]


def test_rejoin_signs_out_the_old_phone(client):
    me = join(client, "Taylor")
    with client.websocket_connect(f"/ws?token={me['token']}") as old_phone:
        read_until(old_phone, "state")
        res = client.post("/api/rejoin", json={"player_id": me["player_id"], "code": code(client)})
        assert res.status_code == 200
        assert read_until(old_phone, "signed_out")
    new_token = res.json()["token"]
    with client.websocket_connect(f"/ws?token={new_token}") as new_phone:
        assert read_until(new_phone, "hello")["you"] == me["player_id"]


def test_ping_gets_pong_and_sync_gets_state(client):
    with client.websocket_connect("/ws") as ws:
        read_until(ws, "state")
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_json({"type": "sync"})
        assert ws.receive_json()["type"] == "state"


def test_laptop_restart_keeps_everyone(tmp_path):
    with make_client(tmp_path) as before:
        room = code(before)
        me = join(before, "Morgan")
        join(before, "Drew")

    with make_client(tmp_path) as after:  # same data folder, new server
        assert code(after) == room
        with after.websocket_connect(f"/ws?token={me['token']}") as phone:
            assert read_until(phone, "hello")["you"] == me["player_id"]
            names = [p["name"] for p in read_until(phone, "state")["state"]["players"]]
            assert names == ["Morgan", "Drew"]


def test_starter_games_are_loaded_on_first_start(client):
    with client.websocket_connect("/ws") as ws:
        assert read_until(ws, "state")["state"]["library_size"] >= 10
