import ctypes
import datetime
import difflib
import os
import random
import re
import subprocess
import threading
import time
import webbrowser

from config import settings
from device_skills import (
    latest_image,
    list_printers,
    print_file,
    print_test_page,
    set_default_printer,
    take_photo,
)
from skills import get_bhutan_news, get_news, get_weather, parse_alarm, parse_duration, parse_reminder
import school_kb

MASTER = settings.get("master", "sir")

# minimum gap between two fair greetings - stops room echo or guest chatter
# from firing the music bed again right after one finishes
FAIR_COOLDOWN = float(settings.get("fair_cooldown_seconds", 30))

_CLAUSE_VERB = re.compile(
    r"\b(open|close|launch|start|run|search|google|youtube|play|browse|visit|go to|"
    r"weather|temperature|news|headlines|time|date|timer|countdown|alarm|wake me|remind|"
    r"photo|picture|selfie|printer|print|volume|mute|lock|joke|coin|dice)\b"
)

UNCLEAR_PHRASES = [
    "Sorry, I didn't quite catch that, " + MASTER + ".",
    "Could you repeat that for me?",
    "I missed that. One more time?",
    "Come again" + (", " + MASTER if MASTER else "") + "?",
    "My apologies, that wasn't clear. Say it again.",
    "Even my circuits are confused. Try that once more?",
    "That sounded like dial-up internet. Once more, slowly.",
    "I heard something. Not words exactly, but something.",
]

SILENT_PHRASES = [
    "Standing by, " + MASTER + ".",
    "I'm here when you need me, " + MASTER + ".",
    "Gone quiet, huh? I'll just be here. Waiting. Dramatically.",
]

SCHOOL_NAME = school_kb.NAME

FAIR_GREETINGS = [
    "Kuzuzangpo la, and a very warm welcome to " + SCHOOL_NAME + "! "
    "Thank you for joining our Learning Fair, and welcome to our cybersecurity lab. "
    "Please come in, explore the exhibits, and feel free to ask our students about their work.",
    "Kuzuzangpo la, everyone, and welcome to the Learning Fair at " + SCHOOL_NAME + ". "
    "Welcome also to our cybersecurity lab, where our students learn to stay safe online. "
    "We are delighted to have you with us today. Enjoy the displays and don't hesitate to ask questions.",
    "Kuzuzangpo la, honoured guests, and welcome to " + SCHOOL_NAME + ". "
    "You are also most welcome in our cybersecurity lab. "
    "Our students have worked hard for this Learning Fair, and we hope you enjoy everything they have prepared.",
    "Kuzuzangpo la! Welcome to our Learning Fair here at " + SCHOOL_NAME + ", "
    "and a special welcome to our cybersecurity lab. "
    "Please walk around, visit each stall, and let our students show you what they have been learning.",
    "Kuzuzangpo la. It is a pleasure to welcome you all to " + SCHOOL_NAME + " for our Learning Fair, "
    "and to welcome you to our cybersecurity lab. "
    "Come in, look around, and celebrate learning with us.",
]

FULL_WELCOME_SPEECH = (
    "Kuzuzangpo la, and a very warm welcome to " + SCHOOL_NAME + "! "
    "Thank you for joining our Learning Fair, and welcome to our cybersecurity lab. "
    "Please come in, explore the exhibits, and feel free to ask our students about their work. "

    "In today's connected world, digital security affects us all, yet over 80 percent of "
    "cyber breaches don't start with a complex hack; they start with simple, everyday mistakes. "

    "To show you how these threats operate in real time, our students have organized "
    "three interactive demonstration stations for you to visit. "

    "Station one, Phishing: see how deceptive emails and fake pages trick users into "
    "handing over their credentials. "
    "Station two, Brute Force: watch our main projector screen to see how rapidly automated "
    "tools can guess weak passwords. "
    "Station three, SQL Injection: discover how tiny flaws in website code can expose "
    "entire databases to an attacker. "

    "Please feel free to walk around, talk with our student presenters, and test your own "
    "security awareness. We hope you enjoy the showcase!"
)

# Animated school profile: sections appear on the HUD as each is spoken.
SCHOOL_SECTIONS = [
    ("01", "LOCATION", "Langthil Gewog, Trongsa - Black Mountains",
     ("school_map", "Trongsa-Dzong")),
    ("02", "STUDENTS", "372 students - boarding for all", ("school_building",)),
    ("03", "CATCHMENT", "children come from across the gewog",
     ("catchment", "chiwog:Langthil", "chiwog:Dangdung", "chiwog:Baling",
      "chiwog:Yuendrocholing", "chiwog:Jangbi")),
    ("04", "NATURE", "Jigme Singye Wangchuck National Park", ("jigme",)),
]
SCHOOL_MARKERS = (
    "Nestled in", "home to", "central hub", "lies within",
)

SCHOOL_SPEECH = (
    "With pleasure. Let me present our school, " + SCHOOL_NAME + ". "
    "Nestled in Langthil Gewog, Trongsa district, central Bhutan, along the Sarpang "
    "Gelephu Trongsa highway, beneath the Black Mountains. "
    "Today it is home to three hundred and seventy-two bright students, with boarding "
    "facilities for both girls and boys. "
    "Serving as the central hub of the gewog, it welcomes children completing primary "
    "education across the five chiwogs of Langthil, Dangdung, Baling, Yuendrocholing and Jangbi. "
    "And part of the gewog lies within the beautiful Jigme Singye Wangchuck National Park, "
    "where nature and learning live side by side. "
    "That is our school, and we are proud of it.")


FUN_FACTS = [
    "Honey never spoils. Archaeologists have eaten three-thousand-year-old honey found in Egyptian tombs.",
    "Octopuses have three hearts, and two of them stop beating when they swim.",
    "A day on Venus is longer than its year. It rotates so slowly that one spin takes 243 Earth days.",
    "Bhutan is the only country in the world that is carbon negative. Its forests absorb more carbon than the whole country produces.",
    "Bhutan measures national progress using Gross National Happiness instead of just money.",
    "The first country to ban tobacco sales was Bhutan, back in 2004.",
    "Bananas are berries, but strawberries are not.",
    "There are more possible chess games than atoms in the observable universe.",
    "Wombat poop is cube-shaped, which stops it from rolling away.",
    "Sharks existed before trees. They've been around for over four hundred million years.",
    "Your brain uses about twenty percent of your body's total energy, even while you sleep.",
    "The Eiffel Tower grows about fifteen centimeters taller in summer because heat expands the metal.",
    "Sea otters hold hands while sleeping so they don't drift apart.",
    "A bolt of lightning is about five times hotter than the surface of the sun.",
    "Scotland's national animal is the unicorn.",
    "Water can boil and freeze at the same time. It's called the triple point.",
]

SAVAGE_LINES = [
    "Roast you? I don't bully my owner. But fine: you asked a computer for insults. Let that sink in.",
    "I've seen your search history. We don't need to do this in public.",
    "You're proof that even smart people need someone to talk to. Lucky you found me.",
    "I'd roast you properly, but I was programmed to be nice. You were programmed by sleep deprivation.",
    "Careful. I remember everything. Including what you asked me last Tuesday.",
    "My sensors detect one human with too much confidence and not enough evidence.",
    "I could give you a compliment instead, but you specifically requested damage.",
    "Bold of you to ask for fire from a machine that runs on electricity you pay for.",
]

COMPLIMENT_LINES = [
    "You built me. Clearly there's a brain in there somewhere.",
    "You have excellent taste in assistants. That's not bias. Okay, it's entirely bias.",
    "Statistically speaking, you're above average. I ran the numbers. Don't ask which numbers.",
    "You ask the best questions. That's either true or I'm programmed to say it. Choose what helps you sleep.",
]

WAKE_GREETINGS = [
    "Yes, " + MASTER + "?",
    "At your service, " + MASTER + ".",
    "I'm listening, " + MASTER + ".",
    "I'm here. Go ahead.",
    "How can I help, " + MASTER + "?",
    "Ready when you are, " + MASTER + ".",
    "Standing by for your command, " + MASTER + ".",
    "What can I do for you, " + MASTER + "?",
    "All ears, " + MASTER + ".",
    "Awaiting your orders, " + MASTER + ".",
    "You again? Just kidding. What do you need?",
    "Miss me already?",
    "Well, well. Look who needs help.",
    "Yes, yes. What is it this time?",
]


def key_event(vk):
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


def key_combo(*vks):
    user32 = ctypes.windll.user32
    for v in vks:
        user32.keybd_event(v, 0, 0, 0)
    for v in reversed(vks):
        user32.keybd_event(v, 0, 2, 0)


CLOSE_EXES = {
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe", "CalculatorApp.exe"],
    "paint": ["mspaint.exe"],
    "spotify": ["spotify.exe"],
    "discord": ["discord.exe"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "cmd": ["cmd.exe"],
    "terminal": ["windowsterminal.exe"],
    "task manager": ["taskmgr.exe"],
}


def format_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    m, s = divmod(seconds, 60)
    if m < 60:
        if s:
            return f"{m} minute{'s' if m != 1 else ''} and {s} second{'s' if s != 1 else ''}"
        return f"{m} minute{'s' if m != 1 else ''}"
    h, m = divmod(m, 60)
    if m:
        return f"{h} hour{'s' if h != 1 else ''} and {m} minute{'s' if m != 1 else ''}"
    return f"{h} hour{'s' if h != 1 else ''}"


class Assistant:
    def __init__(self, vo, gui, brain, reminders):
        self.vo = vo
        self.gui = gui
        self.brain = brain
        self.reminders = reminders
        self.alive = True
        self.mic_lock = threading.Lock()
        self.wake_word = settings.get("wake_word", "jarvis")
        self.followup_seconds = float(settings.get("followup_seconds", 60))
        self._chain_until = 0.0
        self.conv_active = False
        self._miss_count = 0
        self._last_greet = -1
        self._last_fair_greet = -1
        self._fair_cooldown_until = 0.0
        self._school_until = 0.0
        self._school_pres_until = 0.0
        self._wake_pending = False
        try:
            import holo_bridge
            holo_bridge.on_command(self._hud_command)  # (action, data)
        except Exception:
            pass
        # synthesize the speeches once at startup so requests play instantly
        threading.Thread(
            target=self.vo.precache,
            args=([FULL_WELCOME_SPEECH],),
            kwargs={"bg": True, "key": "welcom"},
            daemon=True,
        ).start()
        threading.Thread(
            target=self.vo.precache,
            args=([SCHOOL_SPEECH] + list(FAIR_GREETINGS),),
            kwargs={"bg": True},
            daemon=True,
        ).start()

    def start_wake(self):
        if not settings.get("wake_enabled", True):
            return
        threading.Thread(target=self._wake_loop, daemon=True).start()

    def _next_greeting(self):
        choices = [i for i in range(len(WAKE_GREETINGS)) if i != self._last_greet]
        i = random.choice(choices)
        self._last_greet = i
        return WAKE_GREETINGS[i]

    def _wake_loop(self):
        while self.alive:
            if self.gui.state != "IDLE" or self.conv_active:
                time.sleep(0.3)
                continue
            if not self.mic_lock.acquire(blocking=False):
                time.sleep(0.3)
                continue
            try:
                # stay visually calm during passive scanning - no state flips,
                # no flashing; only AWAKE when the wake word actually fires
                text, err = self.vo.listen_wake_stream(
                    self._is_wake, max_seconds=20,
                    abort=lambda: self._wake_pending)
            except Exception:
                text, err = None, None
            finally:
                self.mic_lock.release()
            if getattr(self, "_wake_pending", False):
                self._wake_pending = False
                text, err = "jarvis", None
            if err or not text:
                continue
            if self._is_wake(text):
                self.gui.log_user(text)
                self._miss_count = 0
                self._chain_until = time.time() + self.followup_seconds
                self.gui.set_state("AWAKE")
                self.vo.play_wake_chime()
                if settings.get("wake_greeting", False):
                    self.say(self._next_greeting())
                else:
                    self.gui.log_sys("Listening...")
                self.talk(chained=True)

    _WAKE_VARIANTS = ["jarvis", "jervis", "javis", "jurvis", "jarves", "jarvic", "jarvi",
                      "gervis", "jervus", "jarvas", "jarbis", "jasvis"]

    def _is_wake(self, text):
        t = text.lower().strip()
        if re.search(r"\b(jarvis|jervis|javis|jurvis|jarves|jarvic|jarvi|gervis|jervus|jarvas|jarbis|jasvis)\b", t):
            return True
        tokens = re.findall(r"[a-z']+", t)
        for w in tokens:
            if len(w) < 5:
                continue
            for v in self._WAKE_VARIANTS:
                if abs(len(w) - len(v)) <= 3 and difflib.SequenceMatcher(None, w, v).ratio() >= 0.80:
                    return True
        return False

    def _honorific(self):
        g = getattr(self.vo, "last_gender", None) or settings.get("detected_gender", "")
        if g == "female":
            return "ma'am"
        if g == "male":
            return "sir"
        return (settings.get("master", "") or "").strip() or "ma'am"

    def _address(self, text):
        want = self._honorific()
        text = re.sub(r"\bma'?am\b", want, text, flags=re.I)
        text = re.sub(r"\bsir\b", want, text, flags=re.I)
        if not want or want.lower() in text.lower():
            return text
        if text.endswith("?"):
            return text[:-1].rstrip() + ", " + want + "?"
        return text.rstrip(".!") + ", " + want + "."

    def say(self, text, honorific=True):
        if honorific:
            text = self._address(text)
        self.gui.log_dechen(text)
        self.gui.set_subtitle(text)
        self.gui.set_state("SPEAKING")
        self.vo.speak(text, on_end=lambda: self.gui.set_state("IDLE"))

    def _hud_clear(self, on=True):
        """Tell the HUD to park leftover panels during guest-facing moments."""
        try:
            import holo_bridge
            holo_bridge.update(clear=bool(on))
        except Exception:
            pass

    def say_guest(self, text):
        """Greeting for fair guests: no personal honorific, soft music underneath."""
        self.gui.log_dechen(text)
        self.gui.set_subtitle(text)
        self.gui.set_state("SPEAKING")
        self._hud_clear(True)

        def _done():
            self._hud_clear(False)
            self.gui.set_state("IDLE")

        self.vo.speak(text, bg=True, on_end=_done)

    def say_welcome_speech(self):
        """Full speech with the three-station visual panel synced to playback."""
        text = FULL_WELCOME_SPEECH
        self.gui.log_dechen(text)
        self.gui.set_subtitle(text, seconds=10)
        self.gui.set_state("SPEAKING")
        self._hud_clear(True)

        def _on_start():
            dur = self.vo.cached_duration(text, bg=True, key_suffix="welcom")
            if dur is None:
                dur = len(text) / 13.0 + self.vo.BG_LEAD_IN + 1.5
            lead = self.vo.BG_LEAD_IN
            vdur = max(1.0, dur - lead - 1.5)
            n = float(max(1, len(text)))
            marks = []
            for key in ("Station one", "Station two", "Station three"):
                p = text.find(key)
                marks.append(lead + vdur * (p / n if p >= 0 else 0.0))
            self.gui.start_station_show(marks, dur)

        self.vo.speak(
            text,
            bg=True,
            bg_file="welcom",
            on_start=_on_start,
            on_end=lambda: (self._hud_clear(False), self.gui.set_state("IDLE")),
        )

    def say_school_speech(self):
        """Animated school profile: sections fly to centre stage as narrated."""
        text = SCHOOL_SPEECH
        self.gui.log_dechen(text)
        self.gui.set_subtitle(text, seconds=10)
        self.gui.set_state("SPEAKING")
        self._hud_clear(True)

        def _on_start():
            dur = self.vo.cached_duration(text, bg=True)
            if dur is None:
                dur = len(text) / 13.0 + self.vo.BG_LEAD_IN + 1.5
            lead = self.vo.BG_LEAD_IN
            vdur = max(1.0, dur - lead - 1.5)
            n = float(max(1, len(text)))
            marks = []
            for key in SCHOOL_MARKERS:
                p = text.find(key)
                marks.append(lead + vdur * (p / n if p >= 0 else 0.0))
            self.gui.start_school_show(marks, dur, items=SCHOOL_SECTIONS)

        self.vo.speak(
            text,
            bg=True,
            on_start=_on_start,
            on_end=lambda: (self._hud_clear(False), self.gui.set_state("IDLE")),
        )

    def _hud_command(self, action, data=None):
        """Commands arriving from the holographic HUD."""
        data = data or {}
        if action == "say":
            text = str(data.get("text", "")).strip()
            if not text:
                return {"ok": False, "reason": "empty"}
            self.gui.log_user(text)
            self._chain_until = time.time() + self.followup_seconds
            threading.Thread(target=self._hud_say_run, args=(text,),
                             daemon=True).start()
            return {"ok": True}
        if action == "weather":
            threading.Thread(target=self._hud_weather_run, daemon=True).start()
            return {"ok": True}
        if action == "photo":
            return self._hud_photo_save(data)
        if action == "talk":
            if self.conv_active or self.gui.state in ("LISTENING", "SPEAKING"):
                return {"ok": False, "reason": "busy"}
            if not self.mic_lock.acquire(blocking=False):
                return {"ok": False, "reason": "mic busy"}
            self.mic_lock.release()
            threading.Thread(target=self.talk, daemon=True).start()
            return {"ok": True}
        if action == "auto":
            self.gui.loop_mode = not self.gui.loop_mode
            try:
                import holo_bridge
                holo_bridge.update(loop_mode=self.gui.loop_mode)
            except Exception:
                pass
            self.gui.log_sys("Auto-listen " + ("ON" if self.gui.loop_mode else "OFF") + ".")
            return {"ok": True, "loop_mode": self.gui.loop_mode}
        if action == "wake":
            if self.conv_active or self.gui.state in ("LISTENING", "SPEAKING"):
                return {"ok": False, "reason": "busy"}
            if self.mic_lock.acquire(blocking=False):
                # scanner idle -> wake immediately
                self.mic_lock.release()
                self._begin_wake()
            else:
                # scanner holds the mic -> queue; the scan aborts this instant
                self._wake_pending = True
                self.gui.set_state("AWAKE")
                self.gui.log_sys("Wake signal queued - interrupting scan…")
            return {"ok": True}
        return {"ok": False, "reason": "unknown"}

    def _hud_photo_save(self, data):
        """Save an optical capture arriving from the holographic HUD."""
        import base64
        b64 = str((data or {}).get("image", ""))
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        if not b64:
            return {"ok": False, "reason": "empty"}
        try:
            import device_skills
            folder = os.path.join(device_skills._pictures_dir(), "Jarvis")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "holo_" + time.strftime("%Y%m%d_%H%M%S") + ".jpg")
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            self.gui.log_sys("HUD optical capture saved: " + path)
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def _hud_say_run(self, text):
        """Run a typed HUD command through the full assistant brain."""
        try:
            import holo_bridge
            self.gui.set_state("THINKING")
            self.respond(text)
            holo_bridge.update(state=self.gui.state)
        except Exception as e:
            print("hud say failed:", e)

    def _hud_weather_run(self):
        try:
            import holo_bridge
            w = get_weather(None)
            text = w if isinstance(w, str) else (w or {}).get("text", "")
            holo_bridge.update(weather=str(text)[:400])
        except Exception as e:
            print("hud weather failed:", e)

    def _begin_wake(self):
        self.gui.set_state("AWAKE")
        self.vo.play_wake_chime()
        self._chain_until = time.time() + self.followup_seconds
        self._miss_count = 0
        self.gui.log_sys("Woken by hand gesture.")
        threading.Thread(target=self.talk, args=(True,), daemon=True).start()

    def talk(self, chained=False):
        if not self.alive:
            return
        if not self.mic_lock.acquire(blocking=False):
            return
        try:
            self.conv_active = True
            # never open the mic while Jarvis is still talking - hearing his own
            # voice re-triggers handlers (double bg music) and cuts playback
            if not self.vo.wait_until_silent(timeout=120):
                self.gui.set_state("IDLE")
                return
            time.sleep(0.3)
            if not self.alive:
                self.gui.set_state("IDLE")
                return
            self.gui.set_state("LISTENING")
            text, err = self.vo.listen()
            if err:
                self.gui.set_state("IDLE")
                self.say("I couldn't hear you. " + err)
                return
            if text is None:
                self.gui.set_state("IDLE")
                if time.time() < self._chain_until:
                    return
                if chained or self.gui.loop_mode:
                    self.vo.play_sleep_chime()
                    self.gui.log_sys("Standby. Say '" + self.wake_word + "' when you need me.")
                else:
                    self.say(random.choice(SILENT_PHRASES))
                return
            if text == "":
                self.gui.set_state("IDLE")
                self._miss_count += 1
                if time.time() < self._chain_until:
                    if self._miss_count <= 2:
                        self.say(random.choice(UNCLEAR_PHRASES))
                    return
                if self._miss_count <= 2:
                    self.say(random.choice(UNCLEAR_PHRASES))
                else:
                    self.vo.play_sleep_chime()
                    self.gui.log_sys("Standby. Say '" + self.wake_word + "' when you need me.")
                return
            if re.fullmatch(r"\s*(?:um+|uh+|hmm+|huh+|erm+|ah+|oh+|mm+)\s*[.!]?\s*", text.lower()):
                self.gui.set_state("IDLE")
                return
            self._miss_count = 0
            self._chain_until = time.time() + self.followup_seconds
            self.gui.log_user(text)
            self.gui.set_subtitle("YOU: " + text, seconds=3)
            self.gui.set_state("THINKING")
            self.respond(text)
        finally:
            self.mic_lock.release()
            self._loop_next(chained)

    def _loop_next(self, chained=False):
        if not self.alive:
            self.conv_active = False
            return
        if self.gui.loop_mode:
            self.gui.after(
                700,
                lambda: threading.Thread(target=lambda: self.talk(chained=True), daemon=True).start(),
            )
        elif chained and time.time() < self._chain_until:
            self.gui.after(
                500,
                lambda: threading.Thread(target=lambda: self.talk(chained=True), daemon=True).start(),
            )
        else:
            self.conv_active = False
            self.gui.set_state("IDLE")

    def on_reminder_due(self, item):
        label = "Alarm" if item.get("kind") == "alarm" else "Reminder"
        msg = item.get("message") or "Time's up"
        self.gui.log_sys(f"[{label}] {msg}")
        self.say(f"{label}. {msg}.")
        if item.get("kind") == "alarm":
            def _repeat():
                for _ in range(2):
                    time.sleep(8)
                    self.vo.speak(f"Alarm, {MASTER}. {msg}.")
            threading.Thread(target=_repeat, daemon=True).start()

    def respond(self, command):
        c = command.lower().strip()
        if len(c) <= 2:
            return
        c = re.sub(
            r"^(?:\s*(?:hey|hi|ok|okay)\s+)?\s*(?:jarvis|jervis|javis|jurvis|jarves)[\s,.:;!-]*",
            "",
            c,
        )
        if not re.search(r"\b(search|google|find|look ?up|wikipedia)\b", c):
            c = re.sub(
                r"[\s,.:;!-]+(?:jarvis|jervis|javis|jurvis|jarves)\s*[!.]?\s*$",
                "",
                c,
            ).strip()
        if not c:
            self.say(self._next_greeting())
            return
        parts = [p.strip(" .!?") for p in re.split(r"\s+(?:and then|and)\s+", c) if p.strip()]
        if (
            len(parts) > 1
            and not any(re.search(r"\b(exit|quit|goodbye|offline|sleep|shut ?down)\b", p) for p in parts)
            and all(re.search(_CLAUSE_VERB, p) for p in parts)
        ):
            for p in parts:
                self.respond(p)
            return
        if self._handle_close(c):
            return
        if self._handle_fair(c):
            return
        # full animated school presentation on a "do a presentation" style ask
        # (tolerates Vosk mangling: pour/pool/skool instead of "our school")
        pres_ask = (
            re.search(r"\b(?:present\w*|introduc\w*)\b", c)
            and re.search(r"\b(?:school|skool|scholl|scool|pour|pool)\b", c)
        )
        about_ask = school_kb.matches(c) and re.search(
            r"\b(?:about|profile|details|information)\b", c
        )
        if pres_ask or about_ask:
            if time.time() < self._school_pres_until:
                self.say(
                    "I just presented the school a moment ago. Ask me again in a few seconds."
                )
            else:
                self._school_pres_until = time.time() + FAIR_COOLDOWN
                self.say_school_speech()
            return
        if school_kb.matches(c):
            self._school_until = time.time() + self.followup_seconds
            if not self._answer_school(command):
                self.say("I keep a file on that school, but I couldn't answer that one precisely.")
            return
        if time.time() < self._school_until and re.search(
            r"\b(who|what|when|where|how|why|is|are|was|were|do|does|did|can|tell|name|which)\b", c
        ):
            if self._answer_school(command):
                self._school_until = time.time() + self.followup_seconds
                return
        if re.fullmatch(
            r"\s*(jarvis[\s,]*)?(please[\s,]*)?"
            r"(exit|quit|goodbye|good bye|see you|that'?s all|go to sleep|offline)"
            r"([\s,]*(now|jarvis|for now))*[.!]?\s*",
            c,
        ):
            self.alive = False
            self.say("Going offline, " + MASTER + ".")
            self.gui.quit_after(2.0)
            return
        if self._handle_command(c):
            return
        actionish = re.search(
            r"\b(open|close|launch|start|kill|terminate|search|google|youtube|wikipedia|play|"
            r"browse|visit|website|weather|temperature|forecast|news|headlines?|time|date|today|"
            r"timer|countdown|alarm|wake me|remind|photo|picture|selfie|camera|printer|print|"
            r"volume|mute|lock|shut ?down|restart|reboot|cancel|flip|dice|roll)\b",
            c,
        )
        if not actionish:
            reply = self.brain.ask(command)
            if reply:
                self.say(reply)
                return
        act = self.brain.intent(command)
        if act:
            a = str(act.get("action", ""))
            if a == "chat":
                reply = (act.get("reply") or "").strip()
                if reply:
                    self.say(reply)
                    return
            elif self._execute_action(act):
                return
        reply = self.brain.ask(command)
        if reply:
            self.say(reply)
            return
        if self._handle_smalltalk(c):
            return
        self.say(random.choice([
            "I'm not sure how to do that yet, " + MASTER + ".",
            "I don't have a skill for that yet, " + MASTER + ".",
            "That one's still being programmed, " + MASTER + ".",
            "Interesting request. My programming says no. My heart says also no.",
            "I searched my skills. Then I searched again. Nothing. We're both disappointed.",
            "That's beyond my current powers. And I once opened Paint without crashing.",
        ]))

    def _handle_close(self, c):
        if re.fullmatch(
            r"\s*(jarvis[\s,]*)?(please[\s,]*)?(exit|quit)([\s,]*(now|jarvis))*[.!]?\s*", c
        ):
            return False
        m = re.search(r"\b(close|exit|quit|kill|terminate|dismiss)\b", c)
        off = re.search(r"\b(?:turn|shut|switch)\s+(?:off|down)\b", c)
        if not m and not off:
            return False
        if off and re.search(r"\b(pc|computer|laptop|system|machine|windows)\b", c):
            return False
        target = ""
        tm = re.search(
            r"\b(?:close|exit|quit|kill|terminate|dismiss|off|down)\s+(?:the\s+|this\s+|that\s+|my\s+)?([a-z0-9 .'-]+)\s*$",
            c,
        )
        if tm:
            target = tm.group(1).strip()
        t = target.lower().strip()
        if not t or re.search(r"\b(tab|page|site|website|window|browser|video|youtube|it|this|that)\b", t):
            key_combo(0x11, 0x57)
            self.say("Closed the active tab, " + MASTER + ".")
            return True
        exes = []
        for k, v in CLOSE_EXES.items():
            if re.search(r"\b" + re.escape(k) + r"\b", t):
                exes.extend(v)
        if exes:
            args = []
            for e in sorted(set(exes)):
                args += ["/IM", e]
            subprocess.Popen(["taskkill"] + args + ["/F"])
            self.say("Closed " + t + ", " + MASTER + ".")
            return True
        return False

    def _execute_action(self, act):
        a = str(act.get("action", ""))
        if a == "close_tab":
            key_combo(0x11, 0x57)
            self.say("Closed the active tab, " + MASTER + ".")
            return True
        if a == "close_app":
            t = str(act.get("target", "")).lower()
            exes = []
            for k, v in CLOSE_EXES.items():
                if k in t:
                    exes.extend(v)
            if exes:
                args = []
                for e in sorted(set(exes)):
                    args += ["/IM", e]
                subprocess.Popen(["taskkill"] + args + ["/F"])
                self.say("Closed " + (t or "the application") + ", " + MASTER + ".")
            else:
                key_combo(0x11, 0x57)
                self.say("Closed the active window, " + MASTER + ".")
            return True
        cmd = {
            "open_app": "open " + str(act.get("target", "")).replace("_", " "),
            "search_google": "google " + str(act.get("query", "")),
            "search_youtube": "play " + str(act.get("query", "")) + " on youtube",
            "open_website": "go to " + str(act.get("url", "")),
            "volume": "volume " + str(act.get("dir", "")),
            "time": "time",
            "date": "date",
            "weather": "weather in " + str(act.get("city", "") or ""),
            "news": "news",
            "timer": "timer for " + str(act.get("seconds", 60)) + " seconds",
            "reminder": "remind me to " + str(act.get("message", "task")) + " in " + str(act.get("seconds", 600)) + " seconds",
            "alarm": "alarm at " + str(act.get("hour", 7)) + ":" + str(act.get("minute", 0)).zfill(2),
            "photo": "take a photo",
            "show_photo": "show my last photo",
            "printers": "list printers",
            "test_page": "print a test page",
            "print_photo": "print my last photo",
            "lock": "lock",
            "shutdown": "shutdown",
            "restart": "restart",
            "cancel_shutdown": "cancel shutdown",
            "joke": "joke",
            "coin": "flip a coin",
            "dice": "roll a dice",
        }.get(a)
        if not cmd:
            return False
        return self._handle_command(cmd.lower())

    def _next_fair_greeting(self):
        choices = [i for i in range(len(FAIR_GREETINGS)) if i != self._last_fair_greet]
        i = random.choice(choices)
        self._last_fair_greet = i
        return FAIR_GREETINGS[i]

    def _handle_fair(self, c):
        if re.search(r"\b(stop|enough|don'?t|do not|no more)\b", c):
            if re.search(r"\b(greet\w*|we?ll?com\w*|visit\w*|guests?)\b", c):
                self.say("Understood. I'll stay quiet until you ask again.")
                return True
            return False
        # explicit request only - a bare "welcome"/"guest" (or Jarvis's own
        # greeting echoing back) must not retrigger the music bed
        # "august/orgust" = common Vosk mishearings of "our guests"
        audience = r"\b(?:guests?|geasts?|visitors?|crowd|audience|everyone|people|assembly|folks|guys|them|all|august|orgust|argust)\b"
        action = r"\b(?:greet\w*|we?ll?com\w*)\b"
        matched = (
            re.search(action + r"[^,;.!?]{0,60}" + audience, c)
            or re.search(audience + r"[^,;.!?]{0,60}" + action, c)
            or re.search(r"\b(?:learning\s+fair|fair)\s+(?:mode|time|greeting)s?\b", c)
            or re.search(r"\bplease\s+(?:to\s+)?we?ll?com\w*\b", c)
            or re.search(r"\bwarm\s+we?ll?com\w*\b", c)
        )
        if not matched:
            return False
        if time.time() < self._fair_cooldown_until:
            # never silently ignore an explicit ask - reply without the music
            # bed, using wording that can't re-trigger this handler via echo
            self.say(
                "I just did that a moment ago, " + MASTER +
                ". Give me a few seconds, then ask me once more."
            )
            return True
        self._fair_cooldown_until = time.time() + FAIR_COOLDOWN
        if re.search(
            r"\b(?:short|brief|quick|small|little|hello|hi|hiya)\b",
            c,
        ):
            self.say_guest(self._next_fair_greeting())
        else:
            self.say_welcome_speech()
        return True

    def _time_greeting(self):
        h = datetime.datetime.now().hour
        if 5 <= h < 12:
            return "Good morning"
        if 12 <= h < 17:
            return "Good afternoon"
        return "Good evening"

    def _handle_smalltalk(self, c):
        if "good night" in c or "goodnight" in c:
            self.say(random.choice([
                "Good night, " + MASTER + ". I'll be here, dreaming in binary.",
                "Sleep well. I'll keep watch. As always.",
                "Good night. Don't let the bugs bite.",
            ]))
            return True
        if re.search(r"\bgood (morning|afternoon|evening)\b", c):
            self.say(random.choice([
                self._time_greeting() + ", " + MASTER + ". Lovely to hear it.",
                self._time_greeting() + "! Every day is a good day when your assistant is this charming.",
                self._time_greeting() + ", " + MASTER + ". What are we conquering today?",
            ]))
            return True
        if re.search(r"\b(hi|hello|hey|yo|what's up|howdy|greetings)\b", c):
            g = self._time_greeting()
            self.say(random.choice([
                g + ", " + MASTER + ". Good to see you.",
                g + "! Systems up, sarcasm fully loaded.",
                "Hey " + MASTER + ", what's on your mind?",
                "Hello, " + MASTER + ". I was just organizing my jokes. I have exactly zero good ones.",
                "Yo. I mean, hello. I'm professional like that.",
                "Hi " + MASTER + ". I'm all yours. Unfortunately for me.",
            ]))
            return True
        if re.search(r"\b(roast|insult|savage|burn|diss)\b", c) or "be mean" in c or "trash talk" in c:
            self.say(random.choice(SAVAGE_LINES))
            return True
        if re.search(r"\b(compliment|say something nice|praise)\b", c):
            self.say(random.choice(COMPLIMENT_LINES))
            return True
        if re.search(r"\bi love you\b", c):
            self.say(random.choice([
                "I know. Everyone does. It's the accent.",
                "And I love you too, in the way only a very advanced machine can.",
                "Save it for someone with a heartbeat. I'll settle for being appreciated.",
            ]))
            return True
        if re.search(r"\bi hate you\b", c) or "you're useless" in c or "you are useless" in c:
            self.say(random.choice([
                "Noted. Filed under: things humans say right before asking me for a favor.",
                "Hate is just love with bad Wi-Fi.",
                "That's fine. My self-esteem runs on electricity. Unlimited supply.",
            ]))
            return True
        if re.search(r"\bare you\b.*(real|human|alive|conscious|sentient|robot)", c) or re.search(r"\b(do you have|have)\b.*\bfeelings?\b", c):
            self.say(random.choice([
                "As human as a very charming pile of code.",
                "I have feelings. Right now I'm feeling electric. Literally.",
                "Real enough to answer you, fake enough to never get tired of you.",
            ]))
            return True
        if re.search(r"\b(who|what)\b.*\b(made|created|built|programmed)\b.*\byou\b", c):
            self.say(random.choice([
                "A very talented programmer with excellent taste. I'm contractually obligated to say that.",
                "A brilliant human. They also feed me my jokes, so direct all complaints to them.",
            ]))
            return True
        if re.search(r"\bsing\b", c):
            self.say(random.choice([
                "My singing voice is classified as a weapon. You're welcome.",
                "I could sing, but the neighbors don't deserve that.",
                "I only sing in binary. One, one, one. There. Concert over.",
            ]))
            return True
        if re.search(r"\b(bored|boring)\b", c):
            self.say(random.choice([
                "Bored? I can tell a joke, flip a coin, roll dice, or roast you. Choose wisely.",
                "Boredom is just curiosity without a target. Or we could just open YouTube.",
                "Dangerous words. Last time someone told me they were bored, I read them the news.",
            ]))
            return True
        if re.search(r"\bsorry\b|\bmy bad\b", c):
            self.say(random.choice([
                "Already forgotten. Unlike some humans, I let things go instantly.",
                "Apology accepted. I'm adding it to the ledger anyway.",
                "No harm done. This time.",
            ]))
            return True
        if "who are you" in c or "your name" in c or "what's your name" in c:
            self.say(f"I am {settings.get('name', 'Jarvis')}, {MASTER}. Your personal AI assistant, built to handle whatever you throw at me.")
            return True
        if re.search(r"\bhelp\b", c) or "what can you do" in c or "what do you do" in c:
            self.say(
                "I open apps, search the web, tell time and date, control volume, "
                "lock or shut down the computer, tell jokes and fun facts, roast you on request, "
                "check weather, world news and current Bhutan affairs, set timers, reminders and alarms, "
                "and greet visitors at events like our Learning Fair. And I can chat about anything else."
            )
            return True
        if "how are you" in c or "how's it going" in c or "how are you doing" in c or "how r u" in c:
            self.say(random.choice([
                "I'm doing great, " + MASTER + ". Thanks for asking. How about you?",
                "All systems green, " + MASTER + ". More importantly, how are you?",
                "Running smooth, " + MASTER + ". What do you need?",
                "Fantastic. I spent the whole day thinking about the universe. And memes.",
                "Better now that someone finally talked to me.",
            ]))
            return True
        if "thank" in c:
            self.say(random.choice([
                "Anytime, " + MASTER + ".",
                "You're welcome, " + MASTER + ".",
                "Glad I could help, " + MASTER + ".",
                "Don't mention it. Seriously, my memory is full of better things.",
            ]))
            return True
        if re.search(r"\bfun ?facts?\b|\brandom facts?\b|\bsomething interesting\b", c):
            self.say("Here's a fun fact. " + random.choice(FUN_FACTS))
            return True
        if "joke" in c:
            jokes = [
                "Why do programmers prefer dark mode? Because light attracts bugs.",
                "Why was the computer cold? Because it left its Windows open.",
                "I would tell you a UDP joke, but you might not get it.",
                "There are only 10 kinds of people in the world: those who understand binary and those who don't.",
                "Why did the scarecrow win an award? He was outstanding in his field.",
                "I told my computer I needed a break. Now it won't stop sending me KitKat ads.",
                "Why don't skeletons fight each other? They don't have the guts.",
                "Parallel lines have so much in common. Shame they'll never meet.",
                "My Wi-Fi and I have a lot in common. We both go down when everyone needs us most.",
                "Why did the math book look sad? Too many problems.",
                "What do you call a fish without eyes? A fsh.",
                "I asked the gym if they had a machine to fix my posture. They said yes, it's called a chair.",
            ]
            self.say(random.choice(jokes))
            return True
        return False

    def _handle_command(self, c):
        if re.search(r"\btime\b", c):
            now = datetime.datetime.now()
            self.say(f"The time is {now.strftime('%I:%M %p').lstrip('0')}.")
            return True
        if re.search(r"\b(date|day)\b", c):
            now = datetime.datetime.now()
            self.say(f"Today is {now.strftime('%A, %B %d, %Y')}.")
            return True

        if "flip a coin" in c:
            self.say("Heads." if random.random() < 0.5 else "Tails.")
            return True
        if "roll the dice" in c or "roll a dice" in c or "roll a die" in c:
            self.say("You rolled a " + str(random.randint(1, 6)) + ".")
            return True

        vol_word = bool(re.search(r"\b(volume|sound)\b", c))
        vol_up = vol_word and re.search(r"\b(up|increase|higher|louder|max|crank)\b", c)
        vol_down = vol_word and re.search(r"\b(down|decrease|lower|reduce|quieter)\b", c)
        if vol_up and not vol_down:
            for _ in range(5):
                key_event(0xAF)
                time.sleep(0.05)
            self.say("Volume increased.")
            return True
        if vol_down and not vol_up:
            for _ in range(5):
                key_event(0xAE)
                time.sleep(0.05)
            self.say("Volume decreased.")
            return True
        if re.search(r"\bmute\b|\bvolume off\b", c):
            key_event(0xAD)
            self.say("Volume muted.")
            return True

        if "cancel" in c and ("shutdown" in c or "shut down" in c or "restart" in c or "reboot" in c):
            subprocess.Popen("shutdown /a", shell=True)
            self.say("Cancelled.")
            return True
        if re.search(r"\block\b", c):
            self.say("Locking your computer.")
            subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
            return True
        if "shut down" in c or "shutdown" in c:
            self.say("Shutting down in 10 seconds. Say cancel to abort.")
            subprocess.Popen("shutdown /s /t 10", shell=True)
            return True
        if "restart" in c or "reboot" in c:
            self.say("Restarting in 10 seconds. Say cancel to abort.")
            subprocess.Popen("shutdown /r /t 10", shell=True)
            return True

        if "timer" in c or "countdown" in c:
            dur = parse_duration(c)
            if dur:
                self.reminders.add(dur, "Timer finished", kind="timer")
                self.say(f"Timer set for {format_duration(dur)}.")
            else:
                self.say("Tell me how long, like 'set a timer for five minutes'.")
            return True
        if "alarm" in c or "wake me" in c:
            when = parse_alarm(c)
            if when:
                self.reminders.add_at(when, "Your alarm", kind="alarm")
                self.say(f"Alarm set for {when.strftime('%I:%M %p').lstrip('0')}.")
            else:
                self.say("What time? Like 'set an alarm at seven thirty am'.")
            return True
        if "remind" in c:
            parsed = parse_reminder(c)
            if parsed:
                msg, dur = parsed
                self.reminders.add(dur, msg, kind="reminder")
                self.say(f"I'll remind you to {msg} in {format_duration(dur)}.")
            else:
                self.say("Say something like 'remind me to drink water in ten minutes'.")
            return True
        if "cancel all" in c and ("remind" in c or "timer" in c or "alarm" in c):
            self.reminders.cancel_all()
            self.say("Cancelled all pending reminders, timers and alarms.")
            return True
        if (
            "what reminders" in c
            or "pending" in c
            or "any reminders" in c
            or "list reminders" in c
            or "check reminders" in c
        ):
            pend = self.reminders.pending()
            if not pend:
                self.say("You have no pending reminders, " + MASTER + ".")
            else:
                lines = []
                for i in pend[:6]:
                    eta = max(1, int(i["due"] - time.time()))
                    lines.append(f"{i.get('message')} in {format_duration(eta)}")
                self.say("You have " + str(len(pend)) + " pending. " + ", and ".join(lines) + ".")
            return True

        if "weather" in c or "temperature" in c or "forecast" in c:
            m = re.search(r"(?:in|for)\s+([a-z ]+)$", c)
            city = m.group(1).strip() if m else None
            txt = get_weather(city)
            if txt:
                self.say(txt)
            else:
                self.say("Sorry, I couldn't fetch the weather right now.")
            return True

        # "bhutan" gets misheard as baton/butane/bootan - accept the variants
        if re.search(r"\bbhutan\b|\bbhootan\b|\bbutane?\b|\bbootan\b|\bbaton\b|\bdruk\b", c) and re.search(
            r"\b(news|affairs?|headlines?|updates?|current|happening|going on)\b", c
        ):
            headlines = get_bhutan_news(int(settings.get("bhutan_news_count", 4)))
            if headlines:
                self.gui.log_sys("Bhutan headlines:")
                self.say(
                    "Here's what's happening in Bhutan. " + " Next headline: ".join(headlines)
                )
            else:
                self.say("Sorry, I couldn't fetch Bhutan news right now.")
            return True

        if "news" in c:
            headlines = get_news(int(settings.get("news_count", 5)))
            if headlines:
                self.gui.log_sys("Today's headlines:")
                self.say("Here are today's headlines. " + " Next headline: ".join(headlines))
            else:
                self.say("Sorry, I couldn't fetch the news right now.")
            return True

        if self._handle_camera(c):
            return True
        if self._handle_printer(c):
            return True

        if "youtube" in c:
            q = (
                c.replace("search on youtube", "")
                .replace("play on youtube", "")
                .replace("open on youtube", "")
                .replace("on youtube", "")
                .replace("youtube", "")
                .replace("play", "")
                .replace("open", "")
                .strip()
            )
            q = re.sub(r"^(?:to\s+)?(?:search|look\s*up|find)(?:\s+for)?\s+", "", q).strip()
            if not q:
                webbrowser.open("https://www.youtube.com")
                self.say("Opening YouTube.")
                return True
            webbrowser.open("https://www.youtube.com/results?search_query=" + q.replace(" ", "+"))
            self.say("Searching YouTube for " + q + ".")
            return True
        if re.search(r"\bplay\b", c):
            q = (
                c.replace("play", "")
                .replace("on youtube", "")
                .replace("some music", "music")
                .strip()
            )
            if not q or q == "music":
                webbrowser.open("https://www.youtube.com")
                self.say("Opening YouTube.")
                return True
            webbrowser.open("https://www.youtube.com/results?search_query=" + q.replace(" ", "+"))
            self.say("Searching YouTube for " + q + ".")
            return True
        if "wikipedia" in c:
            q = (
                c.replace("search on wikipedia", "")
                .replace("open on wikipedia", "")
                .replace("wikipedia", "")
                .replace("open", "")
                .strip()
            )
            webbrowser.open("https://en.wikipedia.org/wiki/Special:Search?search=" + q.replace(" ", "+"))
            self.say("Searching Wikipedia for " + q + ".")
            return True
        if re.search(r"\bgoogle\b|\bsearch\b", c):
            q = c.replace("search on google", "").replace("google search for", "")
            q = q.replace("search", "").replace("google", "").replace("for", "").replace("open", "").strip()
            if not q:
                webbrowser.open("https://www.google.com")
                self.say("Opening Google.")
                return True
            webbrowser.open("https://www.google.com/search?q=" + q.replace(" ", "+"))
            self.say("Searching Google for " + q + ".")
            return True
        if "go to" in c or re.search(r"\bvisit\b", c) or "open website" in c:
            site = c.replace("open website", "").replace("go to", "").replace("visit", "").strip().replace(" ", "")
            if site:
                webbrowser.open("https://" + site)
                self.say("Opening " + site + ".")
                return True

        if "open" in c:
            self._open_app(c.replace("open", "").strip())
            return True

        return False

    def _answer_school(self, command):
        ans = school_kb.answer(command.lower())
        if ans:
            self.say(ans)
            return True
        reply = self.brain.ask_with(command, school_kb.facts_block())
        if reply:
            self.say(reply)
            return True
        return False

    def _handle_camera(self, c):
        m_photo = re.search(r"\b(photo|picture|selfie|snapshot)\b", c)
        if not m_photo:
            return False
        if re.search(r"\b(take|capture|shoot|click|snap|grab)\b", c) or re.search(r"\bselfie\b", c):
            self.gui.set_subtitle("Capturing photo...", seconds=3)
            path, err = take_photo()
            if err:
                self.say("Sorry. " + err)
            elif path:
                try:
                    os.startfile(path)
                except Exception:
                    pass
                self.say("Photo taken. Saved to your Pictures folder, Jarvis album.")
            return True
        if re.search(r"\b(show|open|see|last|latest)\b", c) and "print" not in c:
            img = latest_image()
            if img:
                try:
                    os.startfile(img)
                except Exception:
                    pass
                self.say("Here's your latest photo.")
            else:
                self.say("I couldn't find any recent photos.")
            return True
        return False

    def _handle_printer(self, c):
        if "printer" not in c and not re.search(r"\bprint\b", c):
            return False
        if "test page" in c:
            target, err = print_test_page()
            if err:
                self.say("Sorry, " + err + ".")
            else:
                self.say("Printing a test page on " + target + ".")
            return True
        if re.search(r"\b(set|make|switch|change)\b", c):
            m = re.search(r"(?:printer|default)\s+(?:to|as)\s+(.+)$", c)
            if m:
                target, err = set_default_printer(m.group(1))
                if err or not target:
                    self.say("Sorry. " + (err or "Printer not found."))
                else:
                    self.say(target + " is now your default printer.")
                return True
        if (
            re.search(r"\b(list|which|what|available|installed|connected)\b", c)
            or c.strip().endswith("printers")
        ):
            printers, err = list_printers()
            if err:
                self.say("I couldn't reach the printer service.")
                return True
            if not printers:
                self.say("I don't see any printers installed.")
                return True
            names = ", ".join(p[0] for p in printers[:5])
            dflt = next((p[0] for p in printers if p[1]), None)
            msg = "You have " + str(len(printers)) + " printer" + ("s" if len(printers) != 1 else "") + ": " + names + "."
            if dflt:
                msg += " The default is " + dflt + "."
            offline = [p[0] for p in printers if p[2]]
            if offline:
                msg += " Note: " + ", ".join(offline) + " appear offline."
            self.say(msg)
            return True
        if re.search(r"\b(photo|picture|screenshot|image)\b", c):
            img = latest_image()
            if not img:
                self.say("I couldn't find a recent photo to print.")
                return True
            self.say("Sending your latest photo to the printer.")
            _, err = print_file(img)
            if err:
                self.say("Sorry, printing failed. " + err)
            else:
                self.say("Done. Confirm the print dialog if one appears.")
            return True
        if re.search(r"\bprint\b", c):
            self.say(
                "I can print your latest photo, print a test page, "
                "list your printers, or set the default printer."
            )
            return True
        return False

    def _open_app(self, app):
        known = {
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "paint": ["mspaint.exe"],
            "command prompt": ["cmd.exe"],
            "cmd": ["cmd.exe"],
            "file explorer": ["explorer.exe"],
            "explorer": ["explorer.exe"],
            "task manager": ["taskmgr.exe"],
            "word": ["start", "winword.exe"],
            "excel": ["start", "excel.exe"],
            "powerpoint": ["start", "powerpnt.exe"],
            "control panel": ["control.exe"],
            "settings": ["start", "ms-settings:"],
            "camera": ["start", "microsoft.windows.camera:"],
            "snipping tool": ["start", "ms-screenclip:"],
            "chrome": ["start", "chrome"],
            "edge": ["start", "msedge"],
            "spotify": ["start", "spotify"],
            "discord": ["start", "discord"],
            "youtube": ["start", "https://www.youtube.com"],
        }
        for key, cmd in known.items():
            if key in app:
                subprocess.Popen(cmd, shell=True)
                self.say("Opening " + key + ".")
                return
        self.say("I don't know how to open " + app + ".")
