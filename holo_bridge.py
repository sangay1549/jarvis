"""Tiny local bridge: exposes Jarvis assistant state to the holographic HUD.

GET http://localhost:8770/state -> JSON snapshot (CORS enabled)
GET http://localhost:8770/      -> serves holo_hud.html itself
"""
import json
import os
import threading
import time

try:
    import psutil
except Exception:
    psutil = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_here = os.path.dirname(os.path.abspath(__file__))
_state = {
    "state": "BOOT",
    "last_user": "",
    "last_reply": "",
    "subtitle": "",
    "loop_mode": False,
    "ai_mode": "OFFLINE",
    "clear": False,
}
_lock = threading.Lock()
_started = time.time()
_cmd_cb = None
_show_seq = 0
_active_port = None
_metrics = {"cpu": 0.0, "ram": 0.0, "net_up_kbs": 0.0, "net_down_kbs": 0.0,
            "has_psutil": psutil is not None}
_net_last = {"t": time.time(), "sent": 0, "recv": 0}


def push_log(tag, text):
    """Append a chat-log entry (kept short - the HUD renders the tail)."""
    entry = {"ts": round(time.time(), 3), "tag": str(tag), "text": str(text)[:300]}
    with _lock:
        try:
            log = _state.setdefault("log", [])
        except Exception:
            return
        log.append(entry)
        del _state["log"][:-120]


def start_show(kind, marks, total, items, title):
    """Publish a presentation timeline; the HUD picks it up on its next poll."""
    global _show_seq
    _show_seq += 1
    with _lock:
        _state["show"] = {
            "id": _show_seq,
            "kind": str(kind),
            "t0": round(time.time(), 3),
            "total": float(total),
            "marks": [float(m) for m in marks],
            "items": items,
            "title": str(title),
        }


def _sample_loop():
    if not psutil:
        return
    try:
        psutil.cpu_percent(interval=None)
        c = psutil.net_io_counters()
        _net_last.update(sent=c.bytes_sent, recv=c.bytes_recv, t=time.time())
    except Exception:
        pass
    while True:
        time.sleep(1.0)
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            c = psutil.net_io_counters()
            now = time.time()
            dt = max(0.2, now - _net_last["t"])
            up = max(0.0, (c.bytes_sent - _net_last["sent"]) / dt / 1024.0)
            down = max(0.0, (c.bytes_recv - _net_last["recv"]) / dt / 1024.0)
            _net_last.update(sent=c.bytes_sent, recv=c.bytes_recv, t=now)
            with _lock:
                _metrics.update(cpu=round(cpu, 1), ram=round(ram, 1),
                                net_up_kbs=round(up, 1),
                                net_down_kbs=round(down, 1))
        except Exception:
            pass


threading.Thread(target=_sample_loop, daemon=True).start()


def on_command(cb):
    """Register handler(action:str) -> dict for POST /command."""
    global _cmd_cb
    _cmd_cb = cb


def update(**kw):
    with _lock:
        _state.update(kw)
        _state["ts"] = time.time()


def start(port=8770):
    global _active_port
    class Handler(BaseHTTPRequestHandler):
        def _hdrs(self, ctype, n):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(n))
            self.end_headers()

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(n) if n else b"{}"
                action, data = "", {}
                try:
                    pl = json.loads(raw.decode("utf-8"))
                    action = pl.get("action", "")
                    data = pl.get("data") or {}
                except Exception:
                    pass
                result = {"ok": False}
                if _cmd_cb:
                    try:
                        result = _cmd_cb(action, data) or {"ok": True}
                    except Exception as e:
                        result = {"ok": False, "error": str(e)}
                body = json.dumps(result).encode("utf-8")
                self._hdrs("application/json", len(body))
                self.wfile.write(body)
            except Exception:
                try:
                    self.send_response(500)
                    self.end_headers()
                except Exception:
                    pass

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

        def do_GET(self):
            try:
                if self.path.startswith("/state"):
                    with _lock:
                        snap = dict(_state)
                        if "log" in snap:
                            snap["log"] = list(snap["log"])
                        if "show" in snap:
                            snap["show"] = dict(snap["show"]) if snap["show"] else None
                        snap.update(_metrics)
                        snap["ts"] = time.time()   # fresh clock anchor every poll
                    snap.setdefault("weather", "")
                    snap["uptime_s"] = round(time.time() - _started)
                    body = json.dumps(snap).encode("utf-8")
                    self._hdrs("application/json", len(body))
                    self.wfile.write(body)
                elif self.path in ("/", "/index.html", "/hud"):
                    path = os.path.join(_here, "holo_hud.html")
                    with open(path, "rb") as f:
                        body = f.read()
                    self._hdrs("text/html; charset=utf-8", len(body))
                    self.wfile.write(body)
                elif self.path.startswith("/img/"):
                    name = os.path.basename(self.path[len("/img/"):])
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                        name = ""
                    imgpath = os.path.join(_here, name) if name else ""
                    if not imgpath or not os.path.isfile(imgpath):
                        self.send_response(404)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        return
                    ctype = {"png": "image/png", "jpg": "image/jpeg",
                             "jpeg": "image/jpeg", "gif": "image/gif",
                             "bmp": "image/bmp"}.get(ext.lstrip("."), "application/octet-stream")
                    with open(imgpath, "rb") as f:
                        body = f.read()
                    self._hdrs(ctype, len(body))
                    self.wfile.write(body)
                elif self.path.startswith("/libs/"):
                    name = os.path.basename(self.path[len("/libs/"):])
                    libpath = os.path.join(_here, "libs", name)
                    if not os.path.isfile(libpath):
                        self.send_response(404)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        return
                    ctype = "application/octet-stream"
                    if name.endswith(".js"):
                        ctype = "application/javascript"
                    elif name.endswith(".html"):
                        ctype = "text/html; charset=utf-8"
                    elif name.endswith(".wasm"):
                        ctype = "application/wasm"
                    with open(libpath, "rb") as f:
                        body = f.read()
                    self._hdrs(ctype, len(body))
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
            except Exception:
                pass

        def log_message(self, *a):
            pass

    try:
        srv = None
        last_err = None
        class Server(ThreadingHTTPServer):
            allow_reuse_address = False   # Windows: fail loudly if port is held
        for p in (port, port + 1, port + 2, port + 3):
            try:
                srv = Server(("127.0.0.1", p), Handler)
                port = p
                break
            except Exception as e:
                last_err = e
        if srv is None:
            print("HUD bridge unavailable:", last_err)
            return False
        with _lock:
            _state["ts"] = time.time()   # srvDelta in the HUD needs this
        _active_port = port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("HUD bridge online: http://localhost:%d/" % port)
        return True
    except Exception as e:
        print("HUD bridge unavailable:", e)
        return False


if __name__ == "__main__":
    start()
    while True:
        time.sleep(60)
