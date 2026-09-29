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

