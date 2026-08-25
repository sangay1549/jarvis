import datetime
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET

import requests

from config import settings

REMINDER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.json")

_DURATIONS = [
    ("hours", 3600), ("hour", 3600), ("hrs", 3600), ("hr", 3600),
    ("minutes", 60), ("minute", 60), ("mins", 60), ("min", 60),
    ("seconds", 1), ("second", 1), ("secs", 1), ("sec", 1),
]


_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
}


def _to_num(text):
    text = text.strip().lower()
    if text in _NUM_WORDS:
        return _NUM_WORDS[text]
    if re.fullmatch(r"\d+", text):
        return int(text)
    parts = text.split()
    if len(parts) == 2 and parts[0] in _NUM_WORDS and parts[1] in _NUM_WORDS:
        return _NUM_WORDS[parts[0]] + _NUM_WORDS[parts[1]]
    return None


_UNIT_ALIAS = {
    "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
}

_HOUR_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

_MINUTE_WORDS = {
    "o'clock": 0, "five": 5, "ten": 10, "fifteen": 15, "quarter": 15,
    "twenty": 20, "twenty five": 25, "thirty": 30, "forty": 40,
    "forty five": 45, "fifty": 50, "fifty five": 55,
}


def parse_duration(text):
    m = re.search(r"half\s+(?:an\s+)?(hour|minute)", text)
    if m:
        return 1800 if m.group(1) == "hour" else 30
    words = re.findall(r"\d+|[a-z]+", text.lower())
    for i, w in enumerate(words):
        if w in _UNIT_ALIAS:
            if i >= 1:
                if i >= 2:
                    prev = _to_num(words[i - 2] + " " + words[i - 1])
                    if prev is not None:
                        return prev * _UNIT_ALIAS[w]
                prev = _to_num(words[i - 1])
                if prev is not None:
                    return prev * _UNIT_ALIAS[w]
    return None


def parse_reminder(text):
    m = re.search(r"remind me to (.+?)\s+in\s+(.+)", text)
    if m:
        dur = parse_duration(m.group(2).strip())
        if dur is not None:
            return m.group(1).strip(), dur
    m = re.search(r"remind me in (.+?)\s+to\s+(.+)", text)
    if m:
        dur = parse_duration(m.group(1).strip())
        if dur is not None:
            return m.group(2).strip(), dur
    return None


def _build_clock(hour, minute):
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def parse_alarm(text):
    m = re.search(r"(?:alarm|wake me)", text)
    if not m:
        return None

    dm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", text[m.start():])
    if dm:
        hour = int(dm.group(1))
        minute = int(dm.group(2) or 0)
        ap = dm.group(3)
        if ap:
            ap = ap.replace(".", "").lower()
            if ap == "pm" and hour < 12:
                hour += 12
            if ap == "am" and hour == 12:
                hour = 0
        elif hour < 12:
            hour += 12
        return _build_clock(hour, minute)

    qm = re.search(r"(quarter|half)\s+(past|to)\s+(\d{1,2}|[a-z]+)", text)
    if qm:
        hour_txt = qm.group(3)
        if hour_txt in _HOUR_WORDS:
            hour = _HOUR_WORDS[hour_txt]
        elif re.fullmatch(r"\d{1,2}", hour_txt):
            hour = int(hour_txt)
        else:
            hour = None
        if hour is not None:
            if qm.group(1) == "half":
                minute = 30
            else:
                minute = 45 if qm.group(2) == "to" else 15
            if qm.group(2) == "to":
                hour = (hour - 1) % 12 or 12
            am = re.search(r"\b(a\.?m\.?|p\.?m\.?)\b", text.lower())
            ap = am.group(1).replace(".", "") if am else None
            if ap == "pm" and hour < 12:
                hour += 12
            if ap == "am" and hour == 12:
                hour = 0
            if ap is None and hour < 12:
                hour += 12
            return _build_clock(hour, minute)

    tokens = re.findall(r"[a-z']+|\d+", text.lower())
    cleaned = []
    i = 0
    while i < len(tokens):
        if tokens[i] in ("o", "oh") and i + 1 < len(tokens) and tokens[i + 1] == "clock":
            cleaned.append("o'clock")
            i += 2
        elif tokens[i] in ("and", "at", "in"):
            i += 1
        else:
            cleaned.append(tokens[i])
            i += 1
    pm_i = next((i for i, w in enumerate(cleaned) if w in ("am", "pm")), None)
    search = cleaned[:pm_i] if pm_i is not None else cleaned

    def minute_from_suffix(suffix):
        if not suffix:
            return 0
        if len(suffix) >= 2 and " ".join(suffix[-2:]) in _MINUTE_WORDS:
            return _MINUTE_WORDS[" ".join(suffix[-2:])]
        if suffix[-1] in _MINUTE_WORDS:
            return _MINUTE_WORDS[suffix[-1]]
        return None

    hour = None
    minute = 0
    for i, w in enumerate(search):
        if w in _HOUR_WORDS:
            h = _HOUR_WORDS[w]
        elif re.fullmatch(r"\d{1,2}", w) and 1 <= int(w) <= 12:
            h = int(w)
        else:
            continue
        mm = minute_from_suffix(search[i + 1:])
        if mm is not None:
            hour, minute = h, mm
            break
    if hour is None:
        return None

    ap = cleaned[pm_i] if pm_i is not None and cleaned[pm_i] in ("am", "pm") else None
    if ap == "pm" and hour < 12:
        hour += 12
    if ap == "am" and hour == 12:
        hour = 0
    if ap is None and hour < 12:
        hour += 12
    return _build_clock(hour, minute)


def get_weather(city=None):
    city = (city or settings.get("city", "auto") or "").strip()
    url = "https://wttr.in/{}?format=j1".format(city or "")
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception as e:
        print("Weather error:", e)
        return None
    cur = d["current_condition"][0]
    desc = cur["weatherDesc"][0]["value"]
    temp = cur["temp_C"]
    feels = cur["FeelsLikeC"]
    hum = cur["humidity"]
    wind = cur["windspeedKmph"]
    where = city or d["nearest_area"][0]["areaName"][0]["value"]
    return (
        f"The weather in {where} is {desc} at {temp} degrees Celsius, "
        f"feeling like {feels}. Humidity is {hum} percent and wind speed "
        f"is {wind} kilometers per hour."
    )


def get_news(limit=5):
    url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, timeout=15)
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:limit]
    except Exception as e:
        print("News error:", e)
        return []
    headlines = []
    for item in items:
        title = item.findtext("title")
        if title:
            headlines.append(title.split(" - ", 1)[0] if " - " in title else title)
    return headlines


def get_bhutan_news(limit=4):
    urls = [
        "https://news.google.com/rss/search?q=Bhutan+when:7d&hl=en-US&gl=US&ceid=US:en",
        "https://kuenselonline.com/feed/",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=15)
            root = ET.fromstring(r.content)
            items = root.findall(".//item")[:limit]
            headlines = []
            for item in items:
                title = item.findtext("title")
                if not title:
                    continue
                title = title.split(" - ", 1)[0] if " - " in title else title
                if any(k in title.lower() for k in ("bhutan", "thimphu", "kuensel")) or url.startswith("https://kuensel"):
                    headlines.append(title.strip())
            if headlines:
                return headlines[:limit]
        except Exception as e:
            print("Bhutan news error:", e)
    return []


class ReminderManager(threading.Thread):
    def __init__(self, on_due=None):
        super().__init__(daemon=True)
        self._on_due = on_due
        self._items = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._load()
        self.start()

    def set_handler(self, fn):
        self._on_due = fn

    def _load(self):
        try:
            with open(REMINDER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                item["active"] = True
            self._items = data
            self._next_id = max([i.get("id", 0) for i in data] or [0]) + 1
        except Exception:
            self._items = []

    def _save(self):
        try:
            with open(REMINDER_FILE, "w", encoding="utf-8") as f:
                json.dump([i for i in self._items if i.get("active")], f, indent=2)
        except Exception:
            pass

    def add(self, seconds, message, kind="reminder"):
        with self._lock:
            item = {
                "id": self._next_id,
                "due": time.time() + seconds,
                "message": message,
                "kind": kind,
                "active": True,
            }
            self._next_id += 1
            self._items.append(item)
        self._save()
        return item

    def add_at(self, when, message, kind="alarm"):
        return self.add(max(0.0, when.timestamp() - time.time()), message, kind)

    def pending(self):
        with self._lock:
            now = time.time()
            out = [i for i in self._items if i.get("active") and i["due"] > now]
            out.sort(key=lambda i: i["due"])
            return out

    def cancel_all(self):
        with self._lock:
            for i in self._items:
                i["active"] = False
        self._save()

    def run(self):
        while True:
            now = time.time()
            due = []
            with self._lock:
                for i in self._items:
                    if i.get("active") and i["due"] <= now:
                        i["active"] = False
                        due.append(i)
            if due:
                self._save()
                for i in due:
                    if self._on_due:
                        try:
                            self._on_due(i)
                        except Exception as e:
                            print("Reminder error:", e)
            time.sleep(1)
