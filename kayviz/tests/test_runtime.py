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

        def recv_until(ws, pred, timeout=5.0):
            end = time.time() + timeout
            while time.time() < end:
                msg = json.loads(ws.recv(timeout=max(0.1, end - time.time())))
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
