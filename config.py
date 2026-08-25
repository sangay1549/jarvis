import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "name": "Jarvis",
    "master": "sir",
    "tts_engine": "edge",
    "voice": "en-GB-ThomasNeural",
    "edge_rate": "-4%",
    "edge_volume": "+0%",
    "edge_pitch": "+0Hz",
    "speech_rate": 180,
    "language": "en-US",
    "city": "auto",
    "listen_seconds": 6,
    "news_count": 5,
    "wake_enabled": True,
    "wake_word": "jarvis",
    "bg_music": "",
    "bg_volume": 0.12,
    "ui_sounds": True,
    "hud_autolaunch": True,
}

try:
    with open(_PATH, "r", encoding="utf-8") as f:
        _user = json.load(f)
except Exception:
    _user = {}

settings = {**DEFAULTS, **_user}
