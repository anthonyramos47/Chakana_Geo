"""
Robustness suite for kayviz.evaluate: bad input, bad messages, tabs that come and
go, and memory that must not grow.

Every check runs in a fresh Python process (``python -m
kayviz.evaluate.robustness <check>``): kayviz keeps process-global state, and a
crash then counts as a failure instead of ending the suite. A check prints one
line ``ROBUST:{"pass": bool, "detail": ...}``. The result rows have value 1
(pass) or 0 (fail).

    fuzz-serializers   2,000 seeded random kv.register_* / kv.add_* calls with
                       broken input: each succeeds or raises ValueError naming the
                       object; the scene buffer holds only what succeeded and
                       still encodes
    fuzz-protocol      garbage, truncated, oversized and unknown messages and a
                       burst on the WebSockets: the server keeps answering and a
                       well-behaved tab keeps receiving
    lifecycle-*        bursts in order, two tabs, a slow tab dropped and
                       recovering, a tab closing mid-callback, a stopped server
                       restarting, a notebook cell re-run 50 times
    leak-push-clear    200 x (push 10 meshes, clear) with a tab reading: Python
                       memory levels off

NaN and infinite coordinates are accepted (with a warning): they draw nothing,
and refusing them would break scripts plotting partial results.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import warnings

import numpy as np

CHECKS = ["fuzz-serializers", "fuzz-protocol", "lifecycle-push-burst",
          "lifecycle-two-tabs", "lifecycle-slow-tab-dropped",
          "lifecycle-tab-closes-in-callback", "lifecycle-server-restart",
          "lifecycle-cell-rerun", "leak-push-clear"]
SLOW = {"fuzz-serializers", "lifecycle-slow-tab-dropped", "leak-push-clear"}


# ── Running checks ────────────────────────────────────────────────────────────

def run_check(name: str, timeout: float = 300.0) -> dict:
    """Run one check in a fresh process; {"pass": bool, "detail": str}."""
    env = dict(os.environ, KAYVIZ_NO_BROWSER="1")
    env["KAYVIZ_PORT"] = str(int(os.environ.get("KAYVIZ_TEST_PORT_BASE", "18700")) + 150)
    env.pop("KAYVIZ_URL", None)
    try:
        p = subprocess.run([sys.executable, "-m", "kayviz.evaluate.robustness", name],
                           env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"pass": False, "detail": f"timed out after {timeout:.0f} s"}
    for line in p.stdout.splitlines():
        if line.startswith("ROBUST:"):
            res = json.loads(line[len("ROBUST:"):])
            if p.returncode != 0:            # the result is in, but the exit crashed
                res = {"pass": False, "detail": f"exit code {p.returncode}; {res['detail']}"}
            return res
    return {"pass": False,
            "detail": f"exit code {p.returncode}: {(p.stderr or p.stdout)[-800:]}"}


def run_suite(checks: list[str] | None = None) -> list[dict]:
    rows = []
    for name in checks or CHECKS:
        print(f"[evaluate] robustness: {name}", flush=True)
        t0 = time.monotonic()
        res = run_check(name)
        rows.append({"suite": "robustness", "scene": "-", "metric": name,
                     "value": 1 if res["pass"] else 0, "unit": "pass", "better": "higher",
                     "note": None if res["pass"] else str(res["detail"])[:500]})
        print(f"[evaluate]   {'pass' if res['pass'] else 'FAIL'} "
              f"({time.monotonic() - t0:.1f} s) {res['detail']}", flush=True)
    return rows


# ── Helpers used inside a check process ───────────────────────────────────────

def _kv():
    import kayviz as kv
    kv.init()
    return kv


def _ws(kv, app: str = "script"):
    from websockets.sync.client import connect
    return connect(kv.url().replace("http", "ws") + f"/api/{app}/ws", max_size=None)


def _recv(ws, pred, timeout: float = 10.0):
    from kayviz.runtime.wire import decode
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = decode(ws.recv(timeout=max(0.05, end - time.monotonic())))
        if pred(msg):
            return msg
    raise TimeoutError("message not received")


def _raw_ws(kv):
    """A WebSocket that completes the handshake and then never reads: a tab whose
    browser is stuck. (The websockets client reads in a background thread.)"""
    import socket
    host, port = kv.url().split("//")[1].split(":")
    s = socket.create_connection((host, int(port)))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    s.sendall((f"GET /api/script/ws HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n").encode())
    if b" 101 " not in s.recv(256):
        raise RuntimeError("raw WebSocket handshake refused")
    return s


def _ping_ok(kv) -> bool:
    import requests
    try:
        return requests.get(kv.url() + "/api/script/ping", timeout=5).json().get("ok", False)
    except Exception:
        return False


def _footprint_mb() -> float:
    from .memory import process_footprint_mb
    return process_footprint_mb(os.getpid()) or 0.0


# ── fuzz-serializers ──────────────────────────────────────────────────────────

def _corrupt(rng, a, kind: str):
    """One random corruption of array *a* (points if kind == "points", else indices)."""
    a = np.array(a, copy=True)
    pick = rng.integers(12)
    if pick == 0:
        return a                                                 # valid
    if pick == 1 and kind == "points":
        a = a.astype(float); a.flat[rng.integers(a.size)] = rng.choice([np.nan, np.inf, -np.inf])
        return a
    if pick == 2:
        return a.ravel()                                         # wrong ndim
    if pick == 3:
        return a[:, :2] if a.ndim == 2 else a                    # wrong width
    if pick == 4:
        return np.c_[a, a[:, :1]] if a.ndim == 2 else a          # wider
    if pick == 5:
        return a.astype(object)
    if pick == 6:
        return a.astype(complex)
    if pick == 7:
        return a.astype(str)
    if pick == 8:
        return a[:0]                                             # empty
    if pick == 9 and kind == "indices":
        a = a.copy(); a.flat[rng.integers(a.size)] = rng.choice([-1, -7, 10**6]); return a
    if pick == 10 and kind == "indices":
        return a + 0.5                                           # non-integer
    if pick == 11:
        return a.tolist()
    return a


def _fuzz_serializers() -> dict:
    kv = _kv()
    from kayviz.runtime import registry
    from kayviz.runtime.wire import encode
    rng = np.random.default_rng(0)
    ok_keys, bad = set(), []
    structures: dict[str, tuple[str, int, int]] = {}          # name -> kind, n_vertices, n_faces
    warnings.simplefilter("ignore")
    for i in range(2000):
        n = int(rng.integers(3, 30))
        V = rng.random((n, 3))
        F = rng.integers(0, n, (int(rng.integers(1, 20)), int(rng.choice([3, 4, 5]))))
        E = rng.integers(0, n, (int(rng.integers(1, 20)), 2))
        name = f"o{i % 50}"
        call = int(rng.integers(6))
        color = [(0.2, 0.3, 0.4), (2, 0, 0), (0.1, 0.2), "red", None][int(rng.integers(5))]
        try:
            if call == 0:
                kw = {"color": color} if color is not None else {}
                kv.register_surface_mesh(name, _corrupt(rng, V, "points"),
                                         _corrupt(rng, F, "indices"), **kw)
                key, kind = name, "mesh"
            elif call == 1:
                kv.register_point_cloud(name, _corrupt(rng, V, "points"))
                key, kind = name, "points"
            elif call == 2:
                kv.register_curve_network(name, _corrupt(rng, V, "points"),
                                          _corrupt(rng, E, "indices"))
                key, kind = name, "curves"
            elif call == 3:
                kv.register_vector_field(name, _corrupt(rng, V, "points"),
                                         _corrupt(rng, V, "points"))
                key, kind = name, "field"
            elif call in (4, 5) and structures:
                target = list(structures)[int(rng.integers(len(structures)))]
                if call == 4:
                    vals = rng.random(int(rng.integers(1, 40)))
                    on = ["vertices", "faces", "edges", "nowhere"][int(rng.integers(4))]
                    kv.add_scalar_quantity(target, f"s{i % 5}", _corrupt(rng, vals, "points"),
                                           defined_on=on)
                else:
                    kv.add_vector_quantity(target, f"v{i % 5}", _corrupt(rng, V, "points"),
                                           defined_on=["vertices", "faces"][int(rng.integers(2))])
                key, kind = f"{target}::{'s' if call == 4 else 'v'}{i % 5}", "quantity"
            else:
                continue
        except ValueError as e:
            msg = str(e)
            if name not in msg and not any(t in msg for t in structures):
                bad.append(f"call {call}: ValueError without the object's name: {msg[:120]}")
            continue
        except Exception as e:                                # anything else is a bug
            bad.append(f"call {call}: {type(e).__name__}: {str(e)[:120]}")
            continue
        if kind != "quantity":
            # re-registering drops the old structure's quantities
            ok_keys = {k for k in ok_keys if not k.startswith(name + "::")}
            structures[name] = (kind, 0, 0)
        ok_keys.add(key)
    buf = registry.get_app("script")._buffer
    extra = set(buf) - ok_keys - {k for k in buf if k.endswith("::edges")}
    if extra:
        bad.append(f"buffer holds objects whose call failed: {sorted(extra)[:5]}")
    try:
        encode({"action": "scene_update", "objects": list(buf.values())})
    except Exception as e:
        bad.append(f"the scene buffer no longer encodes: {e!r}")
    return {"pass": not bad, "detail": f"{len(bad)} problem(s)" + (f": {bad[:6]}" if bad else
                                                                   f"; {len(buf)} objects kept")}


# ── fuzz-protocol ─────────────────────────────────────────────────────────────

def _fuzz_protocol() -> dict:
    kv = _kv()
    state = {"x": 1.0}

    def gui():
        kv.imgui.slider_float("X", state, "x", 0, 2)
        if kv.imgui.button("Go"):
            kv.register_point_cloud("Go", np.zeros((1, 3)))
    kv.set_user_callback(gui, app_name="fuzzapp")
    rng = np.random.default_rng(1)
    garbage = [rng.bytes(64), b"\x00\x00\x00\x10{\"a\":", b""]
    texts = ["{", "[1, 2]", "42", "null", '"x"', '{"action": 5}', '{"action": "nope"}',
             '{"action": "_set_state", "state": [1, 2]}', '{"action": "_set_state"}',
             '{"action": "_callback", "state": "x", "changed": 3}',
             '{"action": "_callback", "trigger": "Go", "state": {"x": "NaN"}}',
             '{"action": "applied", "seq": "x"}', "x" * (5 * 1024 * 1024)]
    problems = []
    for app in ("script", "fuzzapp"):
        for payload in garbage + texts:
            try:
                with _ws(kv, app) as ws:
                    ws.send(payload)
                    time.sleep(0.02)
            except Exception:
                pass                                      # the server may close us: fine
        try:
            with _ws(kv, app) as ws:
                for _ in range(1000):
                    ws.send('{"action": "_set_state", "state": {"x": 1.5}}')
        except Exception as e:
            problems.append(f"{app}: burst failed: {e!r}")
    if not _ping_ok(kv):
        problems.append("server stopped answering /ping")
    try:
        with _ws(kv) as ws:
            time.sleep(0.2)
            kv.register_point_cloud("After", np.zeros((2, 3)))
            _recv(ws, lambda m: any(o.get("name") == "After" for o in m.get("objects", [])))
    except Exception as e:
        problems.append(f"a well-behaved tab no longer receives pushes: {e!r}")
    return {"pass": not problems, "detail": "; ".join(problems) or "server and tabs unaffected"}


# ── lifecycle ─────────────────────────────────────────────────────────────────

def _push_burst() -> dict:
    kv = _kv()
    from kayviz.runtime import registry
    names = []
    with _ws(kv) as ws:
        time.sleep(0.2)
        for i in range(1000):
            kv.register_point_cloud(f"P{i}", np.full((1, 3), float(i)))
        while len(names) < 1000:
            m = _recv(ws, lambda m: m.get("action") == "scene_update")
            names += [o["name"] for o in m.get("objects", [])]
    in_order = names == [f"P{i}" for i in range(1000)]
    buf = list(registry.get_app("script")._buffer)
    return {"pass": in_order and buf == [f"P{i}" for i in range(1000)],
            "detail": f"received {len(names)} in order: {in_order}; buffer {len(buf)}"}


def _two_tabs() -> dict:
    kv = _kv()
    with _ws(kv) as a, _ws(kv) as b:
        time.sleep(0.2)
        kv.register_point_cloud("Both", np.zeros((1, 3)))
        got = [_recv(t, lambda m: any(o.get("name") == "Both" for o in m.get("objects", [])))
               for t in (a, b)]
    return {"pass": len(got) == 2, "detail": "both tabs received the push"}


def _slow_tab() -> dict:
    kv = _kv()
    from kayviz.runtime import registry
    app = registry.get_app("script")
    N = 120                                                        # 288 MB in all
    big = np.random.default_rng(0).random((200_000, 3))           # ~2.4 MB per push
    slow = _raw_ws(kv)                                             # never reads
    time.sleep(0.3)
    slow_ws = next(iter(app._queues))
    unsent = [0]

    def watch():                       # bytes written to the stuck tab, not taken
        t = slow_ws.scope.get("kayviz.transport")
        while t is not None and not t.is_closing():
            unsent[0] = max(unsent[0], t.get_write_buffer_size())
            time.sleep(0.01)
    threading.Thread(target=watch, daemon=True).start()
    with _ws(kv) as fast:
        time.sleep(0.3)
        got, stop = [], threading.Event()

        def drain():
            while not stop.is_set():
                try:
                    m = _recv(fast, lambda m: m.get("action") == "scene_update", timeout=1)
                    got.extend(o["name"] for o in m.get("objects", []))
                except TimeoutError:
                    pass
                except Exception:
                    return
        t = threading.Thread(target=drain, daemon=True)
        t.start()
        for i in range(N):
            kv.register_point_cloud(f"B{i}", big + i)
        deadline = time.monotonic() + 120
        while len(got) < N and time.monotonic() < deadline:
            time.sleep(0.1)
        stop.set()
        dropped = slow_ws not in app._queues
    slow.close()
    with _ws(kv) as again:
        snap = _recv(again, lambda m: m.get("action") == "scene_update", timeout=30)
        recovered = sorted(o["name"] for o in snap["objects"]) == sorted(f"B{i}" for i in range(N))
    held = unsent[0] / 2**20
    ok = len(got) == N and dropped and recovered and held < app.MAX_UNSENT / 2**20 + 10
    return {"pass": ok, "detail": f"fast tab got {len(got)}/{N}, slow tab dropped: {dropped}, "
                                  f"reconnect snapshot complete: {recovered}, most bytes held "
                                  f"for it: {held:.0f} MB ({N} pushes of 2.4 MB)"}


def _tab_closes_in_callback() -> dict:
    kv = _kv()
    calls = []

    def gui():
        if kv.imgui.button("Slow"):
            calls.append(1)
            time.sleep(1.0)
            kv.register_point_cloud("Slow", np.zeros((1, 3)))
    kv.set_user_callback(gui, app_name="slowapp")
    with _ws(kv, "slowapp") as ws:
        ws.send(json.dumps({"action": "_callback", "trigger": "Slow", "state": {},
                            "button": True}))
        time.sleep(0.2)                                   # closes while the callback runs
    time.sleep(1.2)
    with _ws(kv, "slowapp") as ws:
        ws.send(json.dumps({"action": "_callback", "trigger": "Slow", "state": {},
                            "button": True}))
        _recv(ws, lambda m: m.get("action") == "gui_state", timeout=10)
    return {"pass": len(calls) == 2 and _ping_ok(kv),
            "detail": f"callbacks run: {len(calls)}; the app answers after the closed tab"}


def _server_restart() -> dict:
    kv = _kv()
    from kayviz.runtime import script
    kv.register_point_cloud("Before", np.zeros((1, 3)))
    script._server.stop()
    kv.register_point_cloud("After", np.zeros((1, 3)))          # starts a new server
    with _ws(kv) as ws:
        snap = _recv(ws, lambda m: m.get("action") == "scene_update")
        names = sorted(o["name"] for o in snap["objects"])
    return {"pass": "After" in names and _ping_ok(kv), "detail": f"after restart: {names}"}


def _cell_rerun() -> dict:
    kv = _kv()
    import asyncio
    from kayviz.runtime import script

    def counts():
        fut = asyncio.run_coroutine_threadsafe(_task_count(), script._loop)
        return threading.active_count(), fut.result(5)
    samples = []
    for i in range(50):
        state = {"x": float(i)}

        def gui(state=state):
            kv.imgui.slider_float("X", state, "x", 0, 100)
        kv.set_user_callback(gui, app_name="cell")
        with _ws(kv, "cell") as ws:
            ws.send(json.dumps({"action": "_callback", "trigger": "x", "state": {"x": 3.0},
                                "changed": ["x"]}))
            _recv(ws, lambda m: m.get("action") == "gui_state", timeout=10)
        if i in (9, 49):
            time.sleep(0.5)
            samples.append(counts())
    (t10, k10), (t50, k50) = samples
    ok = t50 <= t10 + 2 and k50 <= k10 + 5
    return {"pass": ok, "detail": f"threads {t10} -> {t50}, loop tasks {k10} -> {k50} "
                                  f"(after 10 -> 50 re-runs)"}


async def _task_count() -> int:
    import asyncio
    return len(asyncio.all_tasks())


# ── leak-push-clear ───────────────────────────────────────────────────────────

def _leak_push_clear() -> dict:
    import gc
    import tracemalloc
    kv = _kv()
    rng = np.random.default_rng(0)
    V = rng.random((5000, 3))
    F = rng.integers(0, 5000, (10000, 3))
    stop = threading.Event()
    ws = _ws(kv)

    def drain():
        while not stop.is_set():
            try:
                ws.recv(timeout=0.5)
            except TimeoutError:
                pass
            except Exception:
                return
    threading.Thread(target=drain, daemon=True).start()
    time.sleep(0.2)
    tracemalloc.start()
    traced, foot = [], []
    for i in range(200):
        for j in range(10):
            kv.register_surface_mesh(f"M{j}", V, F)
        kv.clear()
        if i % 10 == 9:
            time.sleep(0.1)
            gc.collect()
            traced.append(tracemalloc.get_traced_memory()[0] / 2**20)
            foot.append(_footprint_mb())
    stop.set()
    ws.close()
    x = np.arange(len(traced))[4:]                     # from iteration 50 on
    slope_t = float(np.polyfit(x, traced[4:], 1)[0]) * 10      # MB per 100 iterations
    slope_f = float(np.polyfit(x, foot[4:], 1)[0]) * 10
    grew_t = traced[-1] - traced[4]
    grew_f = foot[-1] - foot[4]
    ok = grew_t < max(5.0, 0.1 * traced[4]) and grew_f < max(20.0, 0.1 * foot[4])
    return {"pass": ok, "detail": f"traced {traced[4]:.1f} -> {traced[-1]:.1f} MB "
                                  f"(slope {slope_t:+.2f} MB/100), footprint {foot[4]:.0f} -> "
                                  f"{foot[-1]:.0f} MB (slope {slope_f:+.2f} MB/100)"}


_IMPL = {"fuzz-serializers": _fuzz_serializers, "fuzz-protocol": _fuzz_protocol,
         "lifecycle-push-burst": _push_burst, "lifecycle-two-tabs": _two_tabs,
         "lifecycle-slow-tab-dropped": _slow_tab,
         "lifecycle-tab-closes-in-callback": _tab_closes_in_callback,
         "lifecycle-server-restart": _server_restart, "lifecycle-cell-rerun": _cell_rerun,
         "leak-push-clear": _leak_push_clear}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _IMPL:
        print(f"usage: python -m kayviz.evaluate.robustness <{'|'.join(CHECKS)}>",
              file=sys.stderr)
        return 2
    try:
        res = _IMPL[argv[0]]()
    except Exception as e:
        res = {"pass": False, "detail": f"{type(e).__name__}: {e}"}
    print("ROBUST:" + json.dumps(res), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
