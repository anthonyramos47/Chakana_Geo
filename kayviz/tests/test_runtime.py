"""
End-to-end tests for the in-process viewer (kayviz.init / set_user_callback /
register_app / show). A websocket client stands in for the browser.

The scripting module keeps process-global state, so each test runs its
scenario in a fresh Python subprocess.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest


def _run(body: str, timeout: float = 60.0) -> dict:
    code = textwrap.dedent('''
        import json, threading, time
        import numpy as np
        import requests
        from websockets.sync.client import connect
        import kayviz as kv

        from kayviz.webscope.wire import decode

        def recv_until(ws, pred, timeout=5.0):
            end = time.time() + timeout
            while time.time() < end:
                msg = decode(ws.recv(timeout=max(0.1, end - time.time())))
                if pred(msg):
                    return msg
            raise TimeoutError("message not received")

        out = {}
    ''') + textwrap.dedent(body) + "\nprint('RESULT' + json.dumps(out))\n"
    env = dict(os.environ, KAYVIZ_NO_BROWSER="1", KAYVIZ_PORT="18700")
    env.pop("KAYVIZ_URL", None)
    env.pop("WEBSCOPE_URL", None)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=timeout, env=env)
    assert proc.returncode == 0, proc.stderr
    line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULT"))
    return json.loads(line[len("RESULT"):])


def test_init_starts_private_server_and_pushes_live():
    out = _run('''
        kv.init()
        base = kv.url()
        out["ping"] = requests.get(base + "/api/script/ping").json()
        out["info"] = requests.get(base + "/api/_info").json()
        with connect(base.replace("http", "ws") + "/api/script/ws") as ws:
            kv.register_point_cloud("P", np.zeros((3, 3)))
            msg = recv_until(ws, lambda m: m.get("action") == "scene_update")
            out["pushed"] = [o["name"] for o in msg["objects"]]
            kv.remove("P")
            out["removed"] = recv_until(ws, lambda m: m.get("action") == "remove")["name"]
    ''')
    assert out["ping"]["kayviz"] and out["ping"]["shared"] is False
    assert out["info"]["default"] == "script"
    assert out["pushed"] == ["P"]
    assert out["removed"] == "P"


def test_callback_app_registered_after_start():
    out = _run('''
        kv.init()
        state = {"r": 1.0}
        def gui():
            kv.imgui.slider_float("Radius", state, "r", 0.1, 5.0)
            if kv.imgui.button("Make"):
                kv.register_point_cloud("Made", np.ones((2, 3)) * state["r"])
        kv.set_user_callback(gui, app_name="demo")

        base = kv.url()
        out["info"] = requests.get(base + "/api/_info").json()
        schema = requests.get(base + "/api/demo/schema").json()
        out["widgets"] = [w.get("label") for w in schema["state"]]
        out["panel"] = schema["panel"]
        with connect(base.replace("http", "ws") + "/api/demo/ws") as ws:
            ws.send(json.dumps({"action": "_callback", "trigger": "Make",
                                "state": {"r": 2.0}}))
            msg = recv_until(ws, lambda m: m.get("action") == "scene_update")
            out["made"] = msg["objects"][0]["name"]
    ''')
    assert out["info"]["default"] == "demo"
    assert out["widgets"] == ["Radius", "Make"]
    assert out["panel"] is False
    assert out["made"] == "Made"


def test_register_app_with_custom_panel(tmp_path):
    panel = tmp_path / "my_panel.js"
    panel.write_text("export default class P {}")
    out = _run(f'''
        from dataclasses import dataclass
        class App(kv.GUIApp):
            name = "custom"
            @kv.gui_state
            @dataclass
            class state_cls:
                n: kv.int_slider(1, 9, 1, "N") = 3
            def register_actions(self):
                self.action("ping", lambda state, data: {{"action": "pong", "n": state.n}})

        kv.register_app(App(), panel_js={str(panel)!r})
        kv.init()
        base = kv.url()
        out["default"] = requests.get(base + "/api/_info").json()["default"]
        schema = requests.get(base + "/api/custom/schema").json()
        out["panel"] = schema["panel"]
        out["panel_src"] = requests.get(base + "/api/custom/panel.js").text
        with connect(base.replace("http", "ws") + "/api/custom/ws") as ws:
            ws.send(json.dumps({{"action": "ping"}}))
            out["reply"] = recv_until(ws, lambda m: m.get("action") == "pong")["n"]
    ''')
    assert out["default"] == "custom"      # registered before the server started
    assert out["panel"] is True
    assert "class P" in out["panel_src"]
    assert out["reply"] == 3


def test_show_blocks_until_tab_closes():
    out = _run('''
        kv.init()
        ws_url = kv.url().replace("http", "ws") + "/api/script/ws"
        def browser():
            time.sleep(0.5)
            with connect(ws_url):
                time.sleep(1.0)          # tab open for a second, then closed
        threading.Thread(target=browser, daemon=True).start()
        t0 = time.time()
        kv.show(block=True)
        out["elapsed"] = time.time() - t0
    ''')
    # 0.5 s before the tab opens + 1 s open + 3 s reload grace
    assert 4.0 < out["elapsed"] < 15.0


def test_attach_to_shared_viewer():
    port = "18750"
    server = subprocess.Popen([sys.executable, "-m", "kayviz", "--port", port],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        out = _run(f'''
            import os
            for _ in range(100):
                try:
                    requests.get("http://127.0.0.1:{port}/api/script/ping", timeout=0.2); break
                except Exception:
                    time.sleep(0.1)
            kv.init(url="http://127.0.0.1:{port}")
            out["mode"] = kv.script._mode
            kv.register_point_cloud("Remote", np.zeros((1, 3)))
            out["objects"] = requests.get("http://127.0.0.1:{port}/api/script/ping").json()["objects"]
            try:
                kv.set_user_callback(lambda: None)
                out["refused"] = False
            except RuntimeError:
                out["refused"] = True
        ''')
    finally:
        server.terminate()
        server.wait(5)
    assert out["mode"] == "attached"
    assert out["objects"] == 1
    assert out["refused"] is True


def test_gui_script_gets_own_viewer_even_if_shared_one_runs():
    port = "18760"
    server = subprocess.Popen([sys.executable, "-m", "kayviz", "--port", port],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        out = _run(f'''
            import os
            os.environ["KAYVIZ_PORT"] = "{port}"
            kv.script._DEFAULT_PORT = {port}
            for _ in range(100):
                try:
                    requests.get("http://127.0.0.1:{port}/api/script/ping", timeout=0.2); break
                except Exception:
                    time.sleep(0.1)
            kv.set_user_callback(lambda: None, app_name="mine")
            kv.init()
            out["mode"] = kv.script._mode
            out["port"] = kv.url().rsplit(":", 1)[1]
            out["apps"] = requests.get(kv.url() + "/api/_info").json()["apps"]
        ''')
    finally:
        server.terminate()
        server.wait(5)
    assert out["mode"] == "local"
    assert out["port"] != port
    assert "mine" in out["apps"]



def test_slow_callback_does_not_block_server_and_reaches_every_tab():
    # The callback runs in a worker thread: the server keeps answering while it
    # runs, and its result goes to every tab of the app.
    out = _run('''
        kv.init()
        state = {"r": 1.0}
        def gui():
            if kv.imgui.button("Slow"):
                time.sleep(1.5)
                kv.register_point_cloud("Slow", np.zeros((2, 3)))
        kv.set_user_callback(gui, app_name="slow")
        base = kv.url()
        wsurl = base.replace("http", "ws") + "/api/slow/ws"
        with connect(wsurl) as a, connect(wsurl) as b:
            a.send(json.dumps({"action": "_callback", "trigger": "Slow", "state": {}}))
            time.sleep(0.3)
            t = time.time()
            requests.get(base + "/api/script/ping", timeout=5)
            out["ping_s"] = time.time() - t
            out["a"] = recv_until(a, lambda m: m.get("action") == "scene_update")["objects"][0]["name"]
            out["b"] = recv_until(b, lambda m: m.get("action") == "scene_update")["objects"][0]["name"]
    ''')
    assert out["ping_s"] < 0.5
    assert out["a"] == out["b"] == "Slow"


def test_slider_events_coalesce_while_callback_runs():
    # Ten quick values of one slider behind a slow callback: queued older values
    # are replaced, so far fewer runs happen and the last one sees the last value.
    out = _run('''
        kv.init()
        state = {"r": 0.0}
        seen = []
        def gui():
            changed, r = kv.imgui.slider_float("R", state, "r", 0.0, 10.0)
            if changed:
                seen.append(r)
                time.sleep(0.3)
                kv.register_point_cloud("P", np.ones((1, 3)) * r)
        kv.set_user_callback(gui, app_name="co")
        with connect(kv.url().replace("http", "ws") + "/api/co/ws") as ws:
            for i in range(1, 11):
                ws.send(json.dumps({"action": "_callback", "trigger": "r",
                                    "state": {"r": float(i)}}))
            recv_until(ws, lambda m: m.get("action") == "scene_update"
                       and m["objects"][0]["points"][0] == 10.0, timeout=10)
        out["seen"] = seen
    ''')
    assert out["seen"][-1] == 10.0
    assert len(out["seen"]) <= 3


def test_pushes_from_main_thread_are_not_captured_by_a_running_callback():
    out = _run('''
        kv.init()
        def gui():
            if kv.imgui.button("Go"):
                time.sleep(1.0)
                kv.register_point_cloud("FromCallback", np.zeros((1, 3)))
        kv.set_user_callback(gui, app_name="tl")
        base = kv.url()
        with connect(base.replace("http", "ws") + "/api/tl/ws") as app_ws, \\
             connect(base.replace("http", "ws") + "/api/script/ws") as script_ws:
            app_ws.send(json.dumps({"action": "_callback", "trigger": "Go", "state": {}}))
            time.sleep(0.3)
            kv.register_point_cloud("FromMain", np.zeros((1, 3)))     # while it runs
            msg = recv_until(script_ws, lambda m: m.get("action") == "scene_update")
            out["script"] = [o["name"] for o in msg["objects"]]
            msg = recv_until(app_ws, lambda m: m.get("action") == "scene_update")
            out["app"] = [o["name"] for o in msg["objects"]]
    ''')
    assert out["script"] == ["FromMain"]
    assert out["app"] == ["FromCallback"]


def test_stop_reaches_a_running_streaming_action():
    # A "stop" sent while an async (streaming) action runs is handled at once.
    out = _run('''
        import asyncio
        from dataclasses import dataclass
        class App(kv.GUIApp):
            name = "opt"
            @kv.gui_state
            @dataclass
            class state_cls:
                running: bool = False
            def register_actions(self):
                self.action("run", self._run)
                self.action("stop", self._stop)
            async def _run(self, state, data, ws):
                state.running = True
                n = 0
                while state.running and n < 200:
                    n += 1
                    await asyncio.sleep(0.05)
                await ws.send_json({"action": "done", "steps": n})
            def _stop(self, state, data):
                state.running = False
                return {"action": "stopped"}
        kv.register_app(App())
        kv.init()
        with connect(kv.url().replace("http", "ws") + "/api/opt/ws") as ws:
            ws.send(json.dumps({"action": "run"}))
            time.sleep(0.3)
            ws.send(json.dumps({"action": "stop"}))
            out["steps"] = recv_until(ws, lambda m: m.get("action") == "done")["steps"]
    ''')
    assert out["steps"] < 50


def test_free_port_survives_time_wait_but_skips_live_server():
    # A re-run must get the port back (the old tabs reconnect there), while a
    # running server keeps its port to itself.
    import socket
    from kayviz.server import find_free_port
    port = 18950
    live = socket.socket()
    live.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    live.bind(("127.0.0.1", port))
    live.listen()
    assert find_free_port(port) == port + 1
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = live.accept()
    conn.close()                    # server side closes first -> TIME_WAIT
    client.close()
    live.close()
    assert find_free_port(port) == port


def test_info_reports_a_server_instance():
    out = _run('''
        kv.init()
        out["instance"] = requests.get(kv.url() + "/api/_info").json().get("instance")
    ''')
    assert isinstance(out["instance"], str) and len(out["instance"]) == 32


def test_quantities_are_checked_against_their_target():
    out = _run('''
        kv.init()
        kv.register_surface_mesh("M", np.zeros((4, 3)), [[0, 1, 2], [0, 2, 3]])
        kv.register_point_cloud("P", np.zeros((5, 3)))
        errors = {}
        for label, call in [
            ("typo", lambda: kv.add_scalar_quantity("Mesh", "s", np.zeros(4))),
            ("length", lambda: kv.add_scalar_quantity("M", "s", np.zeros(3))),
            ("faces", lambda: kv.add_scalar_quantity("M", "s", np.zeros(4), defined_on="faces")),
            ("on points", lambda: kv.add_scalar_quantity("P", "s", np.zeros(5))),
            ("vector length", lambda: kv.add_vector_quantity("P", "v", np.zeros((4, 3)))),
        ]:
            try:
                call(); errors[label] = None
            except ValueError as e:
                errors[label] = str(e)
        kv.add_scalar_quantity("M", "ok", np.zeros(4))
        kv.add_scalar_quantity("M", "okf", np.zeros(2), defined_on="faces")
        kv.add_vector_quantity("P", "v", np.ones((5, 3)))
        kv.remove("M")
        try:
            kv.add_scalar_quantity("M", "s", np.zeros(4)); errors["removed"] = None
        except ValueError as e:
            errors["removed"] = str(e)
        try:
            kv.show(app="typo", block=False); errors["app"] = None
        except ValueError as e:
            errors["app"] = str(e)
        out["errors"] = errors
    ''')
    e = out["errors"]
    assert "no structure named 'Mesh'" in e["typo"] and "registered: M, P" in e["typo"]
    assert "has 4 vertices, got 3" in e["length"]
    assert "has 2 faces, got 4" in e["faces"]
    assert "is a point_cloud" in e["on points"]
    assert "has 5 vertices, got 4" in e["vector length"]
    assert "no structure named 'M'" in e["removed"]
    assert "no app named 'typo'" in e["app"]


def test_buffer_matches_the_viewer_after_remove_and_reregister():
    out = _run('''
        kv.init()
        base = kv.url()
        load = lambda: [o.get("name") if not o.get("target") else o["target"] + "::" + o["name"]
                        for o in requests.post(base + "/api/script/load").json()["objects"]]
        kv.register_surface_mesh("M", np.zeros((3, 3)), [[0, 1, 2]])
        kv.add_scalar_quantity("M", "s", np.zeros(3))
        kv.register_surface_mesh("M", np.zeros((4, 3)), [[0, 1, 2], [0, 2, 3]])   # replaces
        out["after_reregister"] = load()
        kv.add_scalar_quantity("M", "s", np.zeros(4))
        kv.remove("M")
        out["after_remove"] = load()
    ''')
    assert out["after_reregister"] == ["M"]
    assert out["after_remove"] == []


def test_remove_and_clear_inside_a_callback_survive_reload():
    out = _run('''
        kv.init()
        kv.register_point_cloud("Top", np.zeros((1, 3)))             # main thread
        def gui():
            kv.register_point_cloud("Always", np.zeros((1, 3)))   # outside any button
            if kv.imgui.button("Make"):
                kv.register_point_cloud("A", np.zeros((1, 3)))
                kv.register_point_cloud("B", np.zeros((1, 3)))
                kv.remove("A")
            if kv.imgui.button("Clear"):
                kv.clear()
        kv.set_user_callback(gui, app_name="cb")
        base = kv.url()
        names = lambda app: [o["name"] for o in requests.post(
            base + f"/api/{app}/load").json()["objects"]]
        out["script_after_register"] = names("script")
        with connect(base.replace("http", "ws") + "/api/cb/ws") as ws:
            ws.send(json.dumps({"action": "_callback", "trigger": "Make", "state": {}}))
            recv_until(ws, lambda m: m.get("action") == "scene_update")
            out["cb_after_make"] = names("cb")
            ws.send(json.dumps({"action": "_callback", "trigger": "Clear", "state": {}}))
            recv_until(ws, lambda m: m.get("action") == "scene_update")
        out["after_clear"] = names("cb") + names("script")
    ''')
    assert out["script_after_register"] == ["Top"]          # schema capture pushed nothing
    assert "A" not in out["cb_after_make"] and "B" in out["cb_after_make"]
    assert out["after_clear"] == []


def test_one_streaming_run_per_action_and_locked_set_state():
    out = _run('''
        import asyncio
        from dataclasses import dataclass
        running = {"now": 0, "peak": 0}
        class App(kv.GUIApp):
            name = "opt2"
            @kv.gui_state
            @dataclass
            class state_cls:
                n: kv.int_slider(0, 100, 1, "N") = 1
                go: bool = False
            def register_actions(self):
                self.action("run", self._run)
                self.action("stop", self._stop)
                self.action("read", self._read)
            async def _run(self, state, data, ws):
                running["now"] += 1; running["peak"] = max(running["peak"], running["now"])
                state.go = True
                while state.go:
                    await asyncio.sleep(0.05)
                running["now"] -= 1
                await ws.send_json({"action": "done"})
            def _stop(self, state, data):
                state.go = False
                return {"action": "stopped"}
            def _read(self, state, data):
                before = state.n
                time.sleep(0.6)
                return {"action": "read", "before": before, "after": state.n}
        kv.register_app(App())
        kv.init()
        url = kv.url().replace("http", "ws") + "/api/opt2/ws"
        with connect(url) as a, connect(url) as b:
            a.send(json.dumps({"action": "run"}))
            a.send(json.dumps({"action": "run"}))
            out["second"] = recv_until(a, lambda m: m.get("action") == "error")["message"]
            a.send(json.dumps({"action": "stop"}))
            recv_until(a, lambda m: m.get("action") == "done")
            a.send(json.dumps({"action": "read"}))
            time.sleep(0.2)
            b.send(json.dumps({"action": "_set_state", "state": {"n": 42}}))
            msg = recv_until(a, lambda m: m.get("action") == "read")
            out["read"] = [msg["before"], msg["after"]]
        out["peak"] = running["peak"]
    ''')
    assert "already running" in out["second"]
    assert out["peak"] == 1
    assert out["read"] == [1, 1]            # the other tab's change waited for the handler


def test_restart_in_the_same_process():
    out = _run('''
        kv.init()
        kv.register_point_cloud("P", np.zeros((1, 3)))
        with connect(kv.url().replace("http", "ws") + "/api/script/ws") as ws:
            recv_until(ws, lambda m: m.get("action") == "scene_update")
            # binds the app's asyncio primitives to this server's loop
            requests.get(kv.url() + "/api/script/wait", params={"timeout": 0.3})
        kv.kill_servers(ports=range(18700, 18710))
        kv.register_point_cloud("Q", np.zeros((1, 3)))          # starts a new server
        base = kv.url()
        with connect(base.replace("http", "ws") + "/api/script/ws") as ws:
            msg = recv_until(ws, lambda m: m.get("action") == "scene_update")
            out["names"] = [o["name"] for o in msg["objects"]]
            r = requests.get(base + "/api/script/wait", params={"timeout": 0.3})
            out["wait"] = r.status_code
    ''')
    assert out["names"] == ["Q"]
    assert out["wait"] == 200


def test_closing_a_tab_mid_callback_does_not_run_two_callbacks_at_once():
    out = _run('''
        live = {"now": 0, "peak": 0}
        def gui():
            if kv.imgui.button("Slow"):
                live["now"] += 1; live["peak"] = max(live["peak"], live["now"])
                time.sleep(1.0)
                live["now"] -= 1
                kv.register_point_cloud("Done", np.zeros((1, 3)))
        kv.set_user_callback(gui, app_name="cancel")
        kv.init()
        url = kv.url().replace("http", "ws") + "/api/cancel/ws"
        a = connect(url)
        a.send(json.dumps({"action": "_callback", "trigger": "Slow", "state": {}}))
        time.sleep(0.2)
        a.close()                                   # tab goes away mid-callback
        with connect(url) as b:
            b.send(json.dumps({"action": "_callback", "trigger": "Slow", "state": {}}))
            recv_until(b, lambda m: m.get("action") == "scene_update", timeout=6)
        out["peak"] = live["peak"]
    ''')
    assert out["peak"] == 1


def test_pushes_from_a_streaming_handler_keep_their_order():
    out = _run('''
        from dataclasses import dataclass
        class App(kv.GUIApp):
            name = "order"
            @kv.gui_state
            @dataclass
            class state_cls:
                x: int = 0
            def register_actions(self):
                self.action("go", self._go)
            async def _go(self, state, data, ws):
                kv.clear()
                kv.register_surface_mesh("Big", np.random.rand(200000, 3),
                                         np.random.randint(0, 200000, (200000, 3)))
                kv.add_scalar_quantity("Big", "s", np.zeros(200000))
                kv.register_point_cloud("Small", np.zeros((1, 3)))
                await ws.send_json({"action": "went"})
        kv.register_app(App())
        kv.init()
        base = kv.url().replace("http", "ws")
        with connect(base + "/api/script/ws", max_size=None) as s, connect(base + "/api/order/ws") as a:
            a.send(json.dumps({"action": "go"}))
            seq = []
            while len(seq) < 4:
                m = decode(s.recv(timeout=10))
                if m.get("action") == "clear":
                    seq.append("clear")
                for o in m.get("objects", []):
                    seq.append(o["name"])
            out["seq"] = seq
    ''')
    assert out["seq"] == ["clear", "Big", "s", "Small"]


def test_a_tab_that_stops_reading_does_not_stall_pushes():
    out = _run('''
        import socket, base64, os
        kv.init()
        host, port = kv.url().split("//")[1].split(":")
        raw = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        raw.sendall((f"GET /api/script/ws HTTP/1.1\\r\\nHost: {host}:{port}\\r\\n"
                     f"Upgrade: websocket\\r\\nConnection: Upgrade\\r\\n"
                     f"Sec-WebSocket-Key: {key}\\r\\nSec-WebSocket-Version: 13\\r\\n\\r\\n").encode())
        raw.recv(1024)                              # handshake answer, then never read
        big = np.random.rand(1_000_000, 3)
        times = []
        for i in range(6):
            t = time.time()
            kv.register_point_cloud(f"P{i}", big)
            times.append(time.time() - t)
        out["max_push_s"] = max(times)
        raw.close()
    ''')
    assert out["max_push_s"] < 3.0


def test_other_web_pages_cannot_reach_the_viewer():
    out = _run('''
        kv.init()
        kv.register_point_cloud("Secret", np.zeros((2, 3)))
        base = kv.url()
        host = base.split("//")[1]
        ws_url = base.replace("http", "ws") + "/api/script/ws"
        def ws_ok(**kw):
            try:
                with connect(ws_url, **kw) as ws:
                    return recv_until(ws, lambda m: True, timeout=2).get("action")
            except Exception as e:
                return type(e).__name__
        out["ws_foreign"] = ws_ok(origin="https://evil.example")
        out["ws_own"] = ws_ok(origin=f"http://{host}")
        out["ws_python"] = ws_ok()
        out["shutdown_csrf"] = requests.post(base + "/api/_shutdown", data="x",
            headers={"Origin": "https://evil.example", "Content-Type": "text/plain"}).status_code
        out["rebinding"] = requests.get(base + "/api/script/load",
            headers={"Host": "attacker.example:" + host.split(":")[1]}).status_code
        out["no_cors_get"] = requests.get(base + "/api/script/screenshot/pending",
            headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}).status_code
        out["link_from_jupyter"] = requests.get(base + "/",
            headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate"}).status_code
        out["alive"] = requests.get(base + "/api/script/ping").status_code
        r = requests.post(base + "/api/script/screenshot/request",
                          json={"views": [{"live": True}], "width": 20000, "height": 20000})
        out["huge_shot"] = r.json()
    ''')
    assert out["ws_foreign"] != "scene_update"
    assert out["ws_own"] == "scene_update" and out["ws_python"] == "scene_update"
    assert out["shutdown_csrf"] == 403 and out["alive"] == 200
    assert out["rebinding"] == 403 and out["no_cors_get"] == 403
    assert out["link_from_jupyter"] == 200


def test_network_serving_needs_an_explicit_flag():
    proc = subprocess.run([sys.executable, "-m", "kayviz", "--host", "0.0.0.0",
                           "--port", "18799"], capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0 and "--allow-network" in proc.stderr


def test_widget_state_round_trip():
    out = _run('''
        state = {"a": 1.0, "b": 1.0, "mode": 1, "adv": False, "k": 0.5}
        seen = []
        def gui():
            ca, a = kv.imgui.slider_float("A", state, "a", 0, 10)
            cb, b = kv.imgui.slider_float("B", state, "b", 0, 10)
            cm, m = kv.imgui.dropdown("Mode", state, "mode", [1, 2, 3])
            kv.imgui.checkbox("Advanced", state, "adv")
            if state["adv"]:
                kv.imgui.slider_float("K", state, "k", 0, 1)
            if kv.imgui.button("a"):            # same text as slider key "a"
                seen.append("button a")
            if kv.imgui.button("Reset"):
                state["a"] = 0.0
            if ca or cb or cm:
                seen.append((a, b, m, type(m).__name__))
        kv.set_user_callback(gui, app_name="w")
        kv.init()
        with connect(kv.url().replace("http", "ws") + "/api/w/ws") as ws:
            def event(trigger, changed, button=False, **state_):
                ws.send(json.dumps({"action": "_callback", "trigger": trigger, "button": button,
                                    "changed": changed, "state": {**state, **state_}}))
                return recv_until(ws, lambda m: m.get("action") == "gui_state")
            event("b", ["a", "b"], a=5.0, b=2.0)           # A edited, then B, one message
            event("mode", ["mode"], mode="2")              # browsers send strings
            event("a", ["a"], a=6.0)                       # slider "a" is not button "a"
            out["reset"] = event("Reset", [], button=True)["values"]["a"]
            g = event("adv", ["adv"], adv=True)
            out["schema_keys"] = [w["key"] for w in g.get("schema", [])]
        out["seen"] = seen
        out["state"] = state
    ''')
    assert out["seen"][0] == [5.0, 2.0, 1, "int"]
    assert out["seen"][1] == [5.0, 2.0, 2, "int"]
    assert "button a" not in out["seen"]
    assert out["reset"] == 0.0
    assert "k" in out["schema_keys"]


def test_old_pages_without_the_button_flag_still_click_buttons():
    out = _run('''
        hits = []
        def gui():
            if kv.imgui.button("Go"):
                hits.append(1)
                kv.register_point_cloud("G", np.zeros((1, 3)))
        kv.set_user_callback(gui, app_name="old")
        kv.init()
        with connect(kv.url().replace("http", "ws") + "/api/old/ws") as ws:
            ws.send(json.dumps({"action": "_callback", "trigger": "Go", "state": {}}))
            recv_until(ws, lambda m: m.get("action") == "scene_update")
        out["hits"] = len(hits)
    ''')
    assert out["hits"] == 1
