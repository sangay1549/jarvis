"""Headless J.A.R.V.I.S. interface.

There is no desktop window any more - every visual (chat log, subtitles,
state, presentations) lives in the browser HUD served by holo_bridge.
This module keeps the exact public API the rest of the codebase expects,
so assistant.py / dechen.py work unchanged.
"""
import os
import threading
import time

from config import settings
import holo_bridge

STATIONS = [
    ("01", "PHISHING", "deceptive emails & fake login pages", ("phishing",)),
    ("02", "BRUTE FORCE", "automated tools guess weak passwords", ("bruteforce",)),
    ("03", "SQL INJECTION", "code flaws expose whole databases", ("sqlinjection",)),
]

_IMG_CAPTIONS = {
    "school_map": "LANGTHIL GEWOG · TRONGSA",
    "trongsa-dzong": "TRONGSA DZONGKHAG",
    "jigme": "JIGME SINGYE WANGCHUCK NP",
    "school_building": "OUR CAMPUS",
    "catchment": "CATCHMENT AREA · FIVE CHIWOGS",
    "phishing": "STATION 01 · PHISHING",
    "bruteforce": "STATION 02 · BRUTE FORCE",
    "sqlinjection": "STATION 03 · SQL INJECTION",
}


class DechenGUI:
    def __init__(self, title="J.A.R.V.I.S."):
        self.state = "IDLE"
        self._loop_mode = bool(settings.get("auto_listen", False))
        self.on_talk = None
        self._ai_mode = "OFFLINE"
        self.subtitle = ""
        self.title = title
        try:
            holo_bridge.start()
            holo_bridge.update(loop_mode=self._loop_mode,
                               ai_mode=self._ai_mode)
            if settings.get("hud_autolaunch", True) and holo_bridge._active_port:
                import webbrowser
                threading.Timer(1.6, lambda: webbrowser.open(
                    "http://localhost:%d/" % holo_bridge._active_port)).start()
        except Exception as e:
            print("bridge start failed:", e)
        self.log_sys("J.A.R.V.I.S. v6.0 initialized.")

    # ------------------------------------------------------------- scheduling
    def after(self, ms, fn):
        """Drop-in replacement for tk root.after (used by assistant.py)."""
        t = threading.Timer(ms / 1000.0, fn)
        t.daemon = True
        t.start()

    def threadsafe(self, fn, *a, **k):
        fn(*a, **k)

    # ------------------------------------------------------------- state
    @property
    def loop_mode(self):
        return self._loop_mode

    @loop_mode.setter
    def loop_mode(self, v):
        self._loop_mode = bool(v)
        try:
            holo_bridge.update(loop_mode=self._loop_mode)
        except Exception:
            pass

    @property
    def ai_mode(self):
        return self._ai_mode

    @ai_mode.setter
    def ai_mode(self, v):
        self._ai_mode = v
        try:
            holo_bridge.update(ai_mode=v)
        except Exception:
            pass

    def set_state(self, st):
        self.state = st
        try:
            holo_bridge.update(state=st)
        except Exception:
            pass

    # ------------------------------------------------------------- chat log
    def log_user(self, text):
        try:
            holo_bridge.push_log("user", text)
            holo_bridge.update(last_user=text)
        except Exception:
            pass

    def log_dechen(self, text):
        try:
            holo_bridge.push_log("dechen", text)
            holo_bridge.update(last_reply=text)
        except Exception:
            pass

    def log_sys(self, text):
        try:
            holo_bridge.push_log("sys", text)
        except Exception:
            pass

    # ------------------------------------------------------------- subtitles
    def set_subtitle(self, text, seconds=6):
        self.subtitle = str(text)[:160]
        try:
            holo_bridge.update(subtitle=self.subtitle,
                               subtitle_until=time.time() + seconds)
        except Exception:
            pass

    # ------------------------------------------------------------- shows
    def _find_image(self, stem):
        here = os.path.dirname(os.path.abspath(__file__))
        for ext in (".png", ".jpg", ".jpeg", ".gif"):
            name = stem + ext
            p = os.path.join(here, name)
            if os.path.isfile(p):
                return name
        return None

    @staticmethod
    def _norm_items(items, finder):
        """(num, name, desc[, img|imgs]) tuples -> JSON-safe dicts."""
        out = []
        for itm in items:
            num, name, desc = itm[0], itm[1], itm[2]
            d = {"num": num, "name": name, "desc": desc,
                 "img": None, "cap": "", "chips": []}
            if len(itm) > 3 and itm[3]:
                stems = itm[3]
                if isinstance(stems, str):
                    stems = [stems]
                imgs, caps, chips = [], [], []
                for st in stems:
                    if st.startswith("chiwog:"):
                        chips.append(st.split(":", 1)[1])
                        continue
                    fname = finder(st)
                    if fname:
                        imgs.append(fname)
                        caps.append(_IMG_CAPTIONS.get(st.lower(), ""))
                if imgs:
                    d["img"] = imgs
                    d["cap"] = caps
                if chips:
                    d["chips"] = chips
            out.append(d)
        return out

    def start_station_show(self, marks, total, items=None, title=None):
        norm = self._norm_items(list(items) if items else STATIONS,
                                self._find_image)
        try:
            holo_bridge.start_show("station", marks, total, norm,
                                   title or "CYBERSECURITY LAB · LIVE DEMO")
        except Exception:
            pass

    def start_school_show(self, marks, total, items):
        norm = self._norm_items(items, self._find_image)
        try:
            holo_bridge.start_show("school", marks, total, norm,
                                   "SCHOOL ARCHIVE · KNOW YOUR ROOTS")
        except Exception:
            pass

    # ------------------------------------------------------------- lifecycle
    def run(self):
        """No window to spin - just keep the process alive."""
        print("Jarvis is running headless - HUD: http://localhost:8770/")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass

    def quit_after(self, seconds):
        threading.Timer(float(seconds), os._exit, args=(0,)).start()
