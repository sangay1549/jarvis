import asyncio
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import wave
from collections import deque

import numpy as np
import pyttsx3
import sounddevice as sd
import speech_recognition as sr

try:
    import winsound
except ImportError:
    winsound = None

try:
    import miniaudio
except ImportError:
    miniaudio = None

from config import settings

SAMPLE_RATE = 16000
BITS = 16
VOSK_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "vosk-model-small-en-us-0.15"
)
_DBG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_debug.log")


def _dbg(msg):
    if not settings.get("debug_voice", False):
        return
    try:
        with open(_DBG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ UI sounds
# Short Jarvis-style HUD blips. Played through sounddevice so they mix WITH
# speech instead of stealing winsound's single PlaySound channel.

_UI_SFX_CACHE = {}
_UI_SR = 22050


def _env(n, attack=0.06, release=0.5):
    e = np.ones(n)
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    e[:a] = np.linspace(0.0, 1.0, a)
    e[-r:] *= np.linspace(1.0, 0.0, r)
    return e


def _ui_sfx(kind):
    if kind in _UI_SFX_CACHE:
        return _UI_SFX_CACHE[kind]
    sr = _UI_SR
    sig = None
    try:
        if kind == "tick":
            n = int(sr * 0.035)
            t = np.arange(n) / sr
            f = 2100 - 900 * (t / t[-1])
            sig = np.sin(2 * np.pi * np.cumsum(f) / sr) * _env(n, 0.02, 0.85)
        elif kind == "activate":
            parts = []
            for freq, dur in ((1250, 0.05), (1875, 0.07)):
                m = int(sr * dur)
                tt = np.arange(m) / sr
                parts.append(np.sin(2 * np.pi * freq * tt) * _env(m))
            gap = np.zeros(int(sr * 0.02))
            sig = np.concatenate([parts[0], gap, parts[1]])
        elif kind == "done":
            parts = []
            for freq, dur in ((1650, 0.07), (1100, 0.09)):
                m = int(sr * dur)
                tt = np.arange(m) / sr
                parts.append(np.sin(2 * np.pi * freq * tt) * _env(m))
            sig = np.concatenate(parts)
        elif kind == "whoosh":
            n = int(sr * 0.22)
            t = np.arange(n) / sr
            f = 340 + 780 * (t / t[-1]) ** 1.6
            sweep = np.sin(2 * np.pi * np.cumsum(f) / sr)
            shimmer = 0.35 * np.sin(2 * np.pi * (f * 2.01) * t)
            amp = np.sin(np.pi * (t / t[-1])) ** 1.4
            sig = (sweep + shimmer) * amp
        if sig is not None:
            sig = (sig / max(1e-6, np.max(np.abs(sig))) * 32767 * 0.16).astype(np.int16)
        _UI_SFX_CACHE[kind] = sig
    except Exception:
        _UI_SFX_CACHE[kind] = None
    return _UI_SFX_CACHE[kind]


def ui_sound(kind):
    if not settings.get("ui_sounds", True):
        return
    wav_bytes = _ui_sfx(kind)
    if wav_bytes is None:
        return
    try:
        sd.play(np.frombuffer(wav_bytes, dtype=np.int16), _UI_SR, blocking=False)
    except Exception:
        pass


class VoiceIO:
    def __init__(self):
        self.rate = int(settings.get("speech_rate", 180))
        self.voice = settings.get("voice", "en-GB-RyanNeural")
        self.tts_engine = settings.get("tts_engine", "edge")
        self.offline_only = bool(settings.get("offline_only", False))
        self.edge_rate = settings.get("edge_rate", "-4%")
        self.edge_volume = settings.get("edge_volume", "+0%")
        self.edge_pitch = settings.get("edge_pitch", "-10Hz")
        self.bg_volume = float(settings.get("bg_volume", 0.12))
        self.listen_seconds = int(settings.get("listen_seconds", 6))
        self.language = settings.get("language", "en-US")
        self.threshold = 180.0
        self._vosk = None
        self._tts_lock = threading.RLock()
        self._speaking = threading.Event()
        # counts requested-but-not-yet-finished speeches so listeners can't
        # slip into the instant between one ending and the next starting
        self._pending_cv = threading.Condition()
        self._pending = 0
        self._audio_cache = {}
        self._cache_order = []
        # persistent speech cache: once a phrase is synthesized it is stored
        # on disk and replays instantly, even when Edge TTS is slow/offline
        self._disk_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "speech_cache")
        try:
            os.makedirs(self._disk_dir, exist_ok=True)
        except Exception:
            pass
        self._chime_cache = {}
        self._bg_file_cache = {}
        self.last_gender = None
        threading.Thread(target=self._load_vosk, daemon=True).start()
        threading.Thread(target=self._warmup, daemon=True).start()

    def _load_vosk(self):
        try:
            if not os.path.isdir(VOSK_MODEL_DIR):
                msg = "Vosk model folder not found"
                print(msg + "; online recognition will be used." if not self.offline_only
                      else msg + "; offline_only has no recognizer - reinstall the vosk-model-small-en-us-0.15 folder.")
                return
            from vosk import Model
            self._vosk = Model(VOSK_MODEL_DIR)
            print("Offline speech model loaded (Vosk).")
        except Exception as e:
            print("Vosk failed to load, online recognition will be used:", e)

    def _warmup(self):
        try:
            import edge_tts  # noqa: F401
            import miniaudio  # noqa: F401
        except Exception:
            pass
        if self.tts_engine != "edge" or self.offline_only:
            try:
                self._get_sapi_engine()
                print("Windows voice ready.")
            except Exception as e:
                print("Windows voice failed to load:", e)

    def _cache_put(self, key, wav_bytes):
        if len(self._cache_order) >= 60:
            old = self._cache_order.pop(0)
            self._audio_cache.pop(old, None)
        self._audio_cache[key] = wav_bytes
        self._cache_order.append(key)

    def is_speaking(self):
        with self._pending_cv:
            pending = self._pending
        return pending > 0 or self._speaking.is_set()

    def _speech_idle(self):
        with self._pending_cv:
            pending = self._pending
        return pending <= 0 and not self._speaking.is_set()

    def wait_until_silent(self, timeout=10.0):
        deadline = time.time() + max(0.0, timeout)
        while time.time() < deadline:
            if self._speech_idle():
                # settle window: never open the mic in the instant between
                # one finished speech and the next queued one
                time.sleep(min(0.25, max(0.05, deadline - time.time())))
                if self._speech_idle():
                    return True
            time.sleep(0.08)
        return self._speech_idle()

    def _chime(self, notes, volume=0.30):
        try:
            key = (notes, volume)
            cached = self._chime_cache.get(key)
            if cached is None:
                sr = 22050
                parts = []
                for freq, dur in notes:
                    t = np.linspace(0, dur, int(sr * dur), False)
                    tone = np.sin(2 * np.pi * freq * t)
                    attack = int(t.size * 0.15)
                    release = int(t.size * 0.45)
                    env = np.ones(t.size)
                    env[:attack] = np.linspace(0.1, 1.0, attack)
                    env[-release:] *= np.linspace(1.0, 0.0, release)
                    parts.append(tone * env)
                sig = np.concatenate(parts)
                audio = (sig * volume * 32767).astype(np.int16)
                buf = io.BytesIO()
                with wave.open(buf, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(sr)
                    w.writeframes(audio.tobytes())
                cached = buf.getvalue()
                self._chime_cache[key] = cached
            if winsound is not None:
                # chimes share the one PlaySound channel with speech - the lock
                # makes check+play atomic so neither can cut the other off
                if self._tts_lock.acquire(blocking=False):
                    try:
                        if not self._speaking.is_set():
                            winsound.PlaySound(cached, winsound.SND_MEMORY)
                    finally:
                        self._tts_lock.release()
        except Exception:
            pass

    def play_wake_chime(self):
        self._chime(((987.77, 0.09), (1318.51, 0.16)))

    def play_sleep_chime(self):
        self._chime(((659.26, 0.08), (493.88, 0.13)), volume=0.22)

    def _ambient(self, seconds, rate):
        """Soft synthesized chord pad; loopable and click-free."""
        try:
            loop_s = 6.0
            n = int(rate * loop_s)
            t = np.arange(n) / rate
            seg = np.zeros(n)
            chord = [220.00, 277.18, 329.63, 440.00]
            for i, f in enumerate(chord):
                fq = round(f * loop_s) / loop_s
                ph = 2 * np.pi * fq * t
                tone = np.sin(ph) + 0.30 * np.sin(2 * ph + 0.5)
                lfo = (i % 2 + 1) / loop_s
                seg += tone * (0.6 + 0.4 * np.sin(2 * np.pi * lfo * t + i))
            seg /= len(chord) * 1.3
            reps = int(np.ceil(seconds / loop_s)) + 1
            full = np.tile(seg, reps)[: int(rate * seconds)]
            edge = int(rate * 0.05)
            if full.size > 2 * edge:
                full[:edge] *= np.linspace(0.0, 1.0, edge)
                full[-edge:] *= np.linspace(1.0, 0.0, edge)
            return (full * 32767 * self.bg_volume).astype(np.int16)
        except Exception:
            return None

    BG_EXTS = (".wav", ".mp3", ".ogg", ".flac")

    # seconds of music-only intro before the voice joins
    BG_LEAD_IN = 1.2

    def _custom_bg_path(self):
        custom = str(settings.get("bg_music", "") or "").strip()
        if custom:
            p = custom if os.path.isabs(custom) else os.path.join(
                os.path.dirname(os.path.abspath(__file__)), custom)
            return p if os.path.isfile(p) else None
        here = os.path.dirname(os.path.abspath(__file__))
        for name in sorted(os.listdir(here)):
            if name.lower().startswith("bg_music") and os.path.splitext(name)[1].lower() in self.BG_EXTS:
                return os.path.join(here, name)
        return None

    def _named_bg_path(self, stem):
        here = os.path.dirname(os.path.abspath(__file__))
        base = os.path.join(here, stem)
        for e in self.BG_EXTS:
            if os.path.isfile(base + e):
                return base + e
        return None

    def _bg_source_path(self, stem=None):
        """Per-speech music file; falls back to the default bg_music.*"""
        if stem:
            p = self._named_bg_path(stem)
            if p:
                return p
        return self._custom_bg_path()

    def _custom_bg(self, seconds, rate, path=None):
        """User's own music file (bg_music.* or 'bg_music' path), looped to length."""
        try:
            path = path or self._custom_bg_path()
            if not path:
                return None
            cached = self._bg_file_cache.get(path)
            if cached is None:
                decoded = miniaudio.decode_file(path)
                x = np.asarray(decoded.samples, dtype=np.float32)
                if decoded.nchannels > 1:
                    x = x.reshape(-1, decoded.nchannels).mean(axis=1)
                peak = float(np.max(np.abs(x))) if x.size else 0.0
                if peak <= 0:
                    return None
                x *= (32767.0 * self.bg_volume) / peak
                cached = (x.astype(np.int16), int(decoded.sample_rate))
                self._bg_file_cache[path] = cached
            samples, src_rate = cached
            if len(samples) < 8:
                return None
            if src_rate != rate:
                idx = np.linspace(0, len(samples) - 1, int(len(samples) * rate / src_rate))
                lo = np.floor(idx).astype(int)
                hi = np.minimum(lo + 1, len(samples) - 1)
                frac = (idx - lo).astype(np.float32)
                samples = samples[lo] * (1 - frac) + samples[hi] * frac
            if len(samples) < 8:
                return None
            need = int(rate * seconds)
            reps = int(np.ceil(need / max(1, len(samples))))
            full = np.tile(samples.astype(np.float32), reps)[:need]
            edge = min(int(rate * 0.05), full.size // 2 or 1)
            full[:edge] *= np.linspace(0.0, 1.0, edge)
            full[-edge:] *= np.linspace(1.0, 0.0, edge)
            return full.astype(np.int16)
        except Exception as e:
            print("Custom bg music failed:", e)
            return None

    def _mix_bg(self, wav_bytes, bg_path=None):
        """Music starts first, voice joins after BG_LEAD_IN seconds over the bed."""
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as r:
                rate = r.getframerate()
                ch = r.getnchannels()
                sw = r.getsampwidth()
                frames = r.readframes(r.getnframes())
            if sw != 2:
                return wav_bytes
            x = np.frombuffer(frames, dtype=np.int16).astype(np.float32).copy()
            dur = (x.size // ch) / rate
            total = dur + self.BG_LEAD_IN + 1.5
            pad = self._custom_bg(total, rate, bg_path)
            if pad is None:
                pad = self._ambient(total, rate)
            if pad is None:
                return wav_bytes
            out = pad.astype(np.float32)
            if ch > 1:
                # pad is mono - duplicate it onto every channel so the output
                # size matches the interleaved voice data (a mono-size buffer
                # written with a stereo header plays at double speed)
                out = np.repeat(out.reshape(-1, 1), ch, axis=1).reshape(-1)
            tail = min(out.size, int(rate * 1.2) * ch)
            out[-tail:] *= np.linspace(1.0, 0.0, tail)
            lead_n = int(rate * self.BG_LEAD_IN) * ch
            lead_n -= lead_n % ch
            end = min(x.size, out.size - lead_n)
            if end > 0:
                # duck the music a touch under the voice, then blend
                seg = out[lead_n:lead_n + end]
                seg *= 0.7
                seg += x[:end]
                out[lead_n:lead_n + end] = seg
            np.clip(out, -32767, 32767, out=out)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(ch)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(out.astype(np.int16).tobytes())
            return buf.getvalue()
        except Exception:
            return wav_bytes

    def speak(self, text, on_start=None, on_end=None, bg=False, bg_file=None):
        if not text:
            if on_end:
                try:
                    on_end()
                except Exception:
                    pass
            return
        text = self._tts_friendly(text)
        _dbg("speak queued (%d chars): %s" % (len(text), text[:70]))
        # count this request as pending BEFORE spawning anything, and clear it
        # only when its worker's finally runs - closes the clear-then-set gap
        # between two queued speeches that used to leak mic-open-during-speech
        with self._pending_cv:
            self._pending += 1

        def _done():
            with self._pending_cv:
                self._pending -= 1
                self._pending_cv.notify_all()
            if on_end:
                try:
                    on_end()
                except Exception:
                    pass

        try:
            if self.tts_engine == "edge" and not self.offline_only:
                self._speak_edge(text, on_start, _done, bg=bg, bg_file=bg_file)
            else:
                self._speak_sapi(text, on_start, _done, bg=bg)
        except Exception:
            _done()

    # phonetic respellings so the English neural voice pronounces
    # Dzongkha / local names the way they are actually spoken
    _PRONOUNCE = [
        ("Kuzuzangpo", "Koodzoo zahngpoh"),
        ("kuzuzangpo", "koodzoo zahngpoh"),
        ("Langthil", "Langthel"),
        ("langthil", "langthel"),
        ("Trongsa", "Trawngsa"),
        ("trongsa", "trawngsa"),
        ("Gelephu", "Gaylephoo"),
        ("gelephu", "gaylephoo"),
        ("Sarpang", "Sarpaang"),
        ("sarpang", "sarpaang"),
        ("Gewog", "Gaywog"),
        ("gewog", "gaywog"),
        ("Chiwogs", "Cheewogs"),
        ("chiwogs", "cheewogs"),
        ("Chiwog", "Cheewog"),
        ("chiwog", "cheewog"),
        ("Yuendrocholing", "Youdrup-chohling"),
        ("yuendrocholing", "youdrup-chohling"),
        ("Baling", "Bahling"),
        ("baling", "bahling"),
        ("Jangbi", "Jangbee"),
        ("jangbi", "jangbee"),
        ("Dangdung", "Dahngdoong"),
        ("dangdung", "dahngdoong"),
        ("Singye", "Singay"),
        ("singye", "singay"),
        ("Wangchuck", "Wangchuk"),
        ("wangchuck", "wangchuk"),
        ("Jigme", "Jigmey"),
        ("jigme", "jigmey"),
        ("Taktsang", "Toksang"),
        ("taktsang", "toksang"),
        ("Datshi", "Datchi"),
        ("datshi", "datchi"),
        ("Ngultrum", "Engooltroem"),
        ("ngultrum", "engooltroem"),
        ("Dzongkhag", "Zongkhaag"),
        ("dzongkhag", "zongkhaag"),
        ("Dzongkha", "Zonka"),
        ("dzongkha", "zonka"),
        ("Thimphu", "Thimpoo"),
        ("thimphu", "thimpoo"),
        ("Kuensel", "Kwen-sel"),
        ("kuensel", "kwen-sel"),
    ]

    @staticmethod
    def _tts_friendly(text):
        # apostrophe words some voices skip; feed phonetic spellings to the engine
        text = (
            text.replace("ma'am", "mam")
            .replace("Ma'am", "Mam")
            .replace("MA'AM", "MAM")
            .replace("o'clock", "oclock")
        )
        for bad, good in VoiceIO._PRONOUNCE:
            if bad in text:
                text = text.replace(bad, good)
        return text

    def _speak_edge(self, text, on_start=None, on_end=None, bg=False, bg_file=None):
        def _run():
            with self._tts_lock:
                self._speaking.set()
                try:
                    wav_bytes = self._edge_generate(text, bg=bg, key_suffix=bg_file)
                    if wav_bytes is not None:
                        # fire on_start when audio actually begins, not while
                        # still generating (visuals sync to real playback)
                        try:
                            if on_start:
                                on_start()
                        except Exception:
                            pass
                        self._play_wav_bytes(wav_bytes)
                except Exception as e:
                    print("Edge TTS unavailable, using Windows voice:", e)
                    try:
                        if on_start:
                            on_start()
                    except Exception:
                        pass
                    self._speak_sapi_blocking(text)
                finally:
                    self._speaking.clear()
                    try:
                        if on_end:
                            on_end()
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True).start()

    def _edge_key(self, text, bg):
        key = "|".join([self.voice, self.edge_rate, self.edge_volume, self.edge_pitch, text])
        if bg:
            key += "|bg"
        return key

    def cached_duration(self, text, bg=False, key_suffix=None):
        key = self._edge_key(text, bg)
        if key_suffix:
            key += "|" + key_suffix
        wav_bytes = self._audio_cache.get(key)
        return self._wav_duration(wav_bytes) if wav_bytes is not None else None

    def _edge_generate(self, text, bg=False, key_suffix=None):
        """Cached (memory -> disk) or freshly synthesized wav bytes."""
        key = self._edge_key(text, bg)
        if key_suffix:
            key += "|" + key_suffix
        cached = self._audio_cache.get(key)
        if cached is None:
            digest = hashlib.md5(key.encode("utf-8")).hexdigest()
            cache_path = os.path.join(self._disk_dir, digest + ".wav")
            if os.path.isfile(cache_path):
                try:
                    with open(cache_path, "rb") as f:
                        cached = f.read()
                    self._cache_put(key, cached)
                except Exception:
                    cached = None
        if cached is not None:
            return cached
        import edge_tts
        import miniaudio  # noqa: F401

        t0 = time.time()
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        try:
            async def _generate():
                c = edge_tts.Communicate(
                    text,
                    self.voice,
                    rate=self.edge_rate,
                    volume=self.edge_volume,
                    pitch=self.edge_pitch,
                )
                await c.save(path)
            asyncio.run(_generate())
            wav_bytes = self._decode_to_wav_bytes(path)
            if bg:
                wav_bytes = self._mix_bg(wav_bytes, self._bg_source_path(key_suffix))
            self._cache_put(key, wav_bytes)
            _dbg("edge generated %.2fs for %d chars" % (time.time() - t0, len(text)))
            try:
                digest = hashlib.md5(key.encode("utf-8")).hexdigest()
                cache_path = os.path.join(self._disk_dir, digest + ".wav")
                tmpf = cache_path + ".tmp"
                with open(tmpf, "wb") as f:
                    f.write(wav_bytes)
                os.replace(tmpf, cache_path)
            except Exception:
                pass
            return wav_bytes
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def precache(self, texts, bg=False, key=None):
        """Synthesize speeches in the background so later playback starts instantly."""
        if isinstance(texts, str):
            texts = [texts]

        def _run():
            for t in texts:
                try:
                    self._edge_generate(t, bg=bg, key_suffix=key)
                except Exception as e:
                    print("Precache stopped:", e)
                    return

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _decode_to_wav_bytes(path):
        decoded = miniaudio.decode_file(path)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(decoded.nchannels)
            w.setsampwidth(decoded.sample_width)
            w.setframerate(decoded.sample_rate)
            w.writeframes(decoded.samples)
        return buf.getvalue()

    @staticmethod
    def _wav_duration(wav_bytes):
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as r:
                return r.getnframes() / float(r.getframerate())
        except Exception:
            return 0.0

    def _play_wav_bytes(self, wav_bytes):
        if winsound is not None:
            expected = self._wav_duration(wav_bytes)
            t0 = time.time()
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
            actual = time.time() - t0
            if actual < expected - 0.35:
                _dbg("PLAYBACK CUT: %.2fs played of %.2fs audio" % (actual, expected))
            else:
                _dbg("playback ok: %.2fs / %.2fs" % (actual, expected))
            return
        decoded = miniaudio.decode(wav_bytes)
        with miniaudio.PlaybackDevice(
            output_format=decoded.sample_format,
            nchannels=decoded.nchannels,
            sample_rate=decoded.sample_rate,
        ) as device:
            device.start()
            device.write(decoded.samples)

    def _speak_sapi(self, text, on_start=None, on_end=None, bg=False):
        def _run():
            with self._tts_lock:
                self._speaking.set()
                try:
                    if on_start:
                        on_start()
                except Exception:
                    pass
                try:
                    spoke = False
                    if bg:
                        try:
                            wav = self._sapi_wav_bytes(text)
                        except Exception:
                            wav = None
                        if wav:
                            self._play_wav_bytes(self._mix_bg(wav))
                            spoke = True
                    if not spoke:
                        self._speak_sapi_blocking(text)
                finally:
                    self._speaking.clear()
                    try:
                        if on_end:
                            on_end()
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True).start()

    def _sapi_wav_bytes(self, text):
        """Render speech with the offline Windows voice to PCM wav bytes."""
        import pyttsx3
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            self._pick_sapi_voice(engine)
            engine.save_to_file(text, path)
            engine.runAndWait()
            with wave.open(path, "rb") as r:
                if r.getnframes() <= 0 or r.getsampwidth() != 2:
                    return None
                rate, ch, sw = r.getframerate(), r.getnchannels(), r.getsampwidth()
                frames = r.readframes(r.getnframes())
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(ch)
                w.setsampwidth(sw)
                w.setframerate(rate)
                w.writeframes(frames)
            return buf.getvalue()
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def _get_sapi_engine(self):
        # A pyttsx3 engine must be created AND used in the same thread;
        # sharing one across threads hangs runAndWait() with no sound.
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", self.rate)
        self._pick_sapi_voice(engine)
        return engine

    def _pick_sapi_voice(self, engine):
        try:
            voices = engine.getProperty("voices") or []
            names = [v.name.lower() for v in voices]
            # one fixed fallback voice - gender switching made it sound like two people
            prefs = ["david", "george", "guy", "male"]
            chosen = None
            for p in prefs:
                for v, n in zip(voices, names):
                    if p in n and "neural" not in n:
                        chosen = v.id
                        break
                if chosen:
                    break
            if not chosen and names:
                chosen = voices[0].id
            if chosen:
                engine.setProperty("voice", chosen)
        except Exception:
            pass

    def _speak_sapi_blocking(self, text):
        try:
            engine = self._get_sapi_engine()
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception:
                engine = self._get_sapi_engine()
                engine.say(text)
                engine.runAndWait()
        except Exception as e:
            print("TTS error:", e)

    def _rms(self, block):
        return float(np.sqrt(np.mean(np.square(block.astype(np.float32)))))

    def _speech_quality(self, recording):
        """Fraction of 60ms frames at/above the loudness threshold."""
        try:
            x = np.abs(recording.astype(np.float32))
            frame = int(SAMPLE_RATE * 0.06)
            n = len(x) // frame
            if not n:
                return 0.0
            energies = np.sqrt(np.mean(x[: n * frame].reshape(n, frame) ** 2, axis=1))
            return float(np.mean(energies >= self.threshold))
        except Exception:
            return 1.0

    def _record_vad(self, max_seconds, silence_secs=1.0, onset_secs=None):
        if onset_secs is None:
            onset_secs = float(settings.get("speech_start_timeout", 6))
        block_frames = int(SAMPLE_RATE * 0.06)
        calib_frames = int(0.5 / 0.06)
        need_onset = max(2, int(round(0.18 / 0.06)))
        preroll = deque(maxlen=calib_frames)
        chunks = []
        calib = []
        noise = 1.0
        speech_started = False
        last_voice = 0.0
        onset_hits = 0
        start = time.time()
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                blocksize=block_frames,
            ) as stream:
                while time.time() - start < max_seconds:
                    data, _ = stream.read(block_frames)
                    block = data[:, 0]
                    level = self._rms(block)
                    if len(calib) < calib_frames:
                        calib.append(level)
                        preroll.append(block)
                        if len(calib) == calib_frames:
                            noise = max(float(np.median(calib)), 1.0)
                            margin = float(settings.get("vad_noise_margin", 3.5))
                            floor = float(settings.get("vad_min_threshold", 250.0))
                            self.threshold = max(noise * margin, floor)
                        continue
                    if not speech_started:
                        preroll.append(block)
                        if level >= self.threshold:
                            onset_hits += 1
                            if onset_hits >= need_onset:
                                speech_started = True
                                last_voice = time.time()
                                chunks.extend(preroll)
                                preroll.clear()
                        else:
                            onset_hits = max(0, onset_hits - 1)
                        if not speech_started and time.time() - start >= onset_secs:
                            break
                        continue
                    chunks.append(block)
                    if level >= self.threshold:
                        last_voice = time.time()
                    elif time.time() - last_voice >= silence_secs:
                        _dbg("mic stop: %.1fs below threshold (pause), spoke for %.1fs, threshold=%.0f"
                             % (silence_secs, time.time() - start, self.threshold))
                        break
        except Exception as e:
            return None, "Microphone error: " + str(e)
        if not chunks:
            if speech_started:
                _dbg("mic stop: no chunks")
            return None, None
        dur = len(np.concatenate(chunks)) / float(SAMPLE_RATE)
        _dbg("mic captured %.2fs (max was %ds)" % (dur, max_seconds))
        if dur >= max_seconds - 0.35:
            _dbg("MIC CUT: hit listen_seconds limit before you finished")
        return np.concatenate(chunks), None

    @staticmethod
    def guess_gender(recording):
        """Estimate the speaker's pitch; deeper voices -> 'male', higher -> 'female'."""
        try:
            x = recording.astype(np.float32) / 32768.0
            frame = int(SAMPLE_RATE * 0.04)
            hop = frame // 2
            lag_min = max(2, int(SAMPLE_RATE / 350))
            lag_max = int(SAMPLE_RATE / 70)
            f0s = []
            for start in range(0, len(x) - frame, hop):
                seg = x[start:start + frame]
                if np.sqrt(np.mean(seg * seg)) < 0.01:
                    continue
                seg = seg - np.mean(seg)
                ac = np.correlate(seg, seg, "full")[frame - 1:]
                if ac[0] <= 0:
                    continue
                ac = ac / ac[0]
                window = ac[lag_min:lag_max]
                if len(window) == 0:
                    continue
                peak = int(np.argmax(window)) + lag_min
                if ac[peak] > 0.5:
                    f0s.append(SAMPLE_RATE / peak)
            if len(f0s) < 6:
                return None
            med = float(np.median(f0s))
            print("Voice pitch: " + str(round(med)) + " Hz")
            return "female" if med >= 160.0 else "male"
        except Exception:
            return None

    def _persist_gender(self, g):
        try:
            import json as _json
            from config import _PATH
            settings["detected_gender"] = g
            with open(_PATH, "r", encoding="utf-8") as f:
                cfg = _json.load(f)
            cfg["detected_gender"] = g
            with open(_PATH, "w", encoding="utf-8") as f:
                _json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def listen(self):
        end_silence = float(settings.get("end_silence", 0.7))
        recording, err = self._record_vad(self.listen_seconds, silence_secs=end_silence)
        if err:
            return None, err
        if recording is None or len(recording) < SAMPLE_RATE // 3:
            return None, None
        dur = len(recording) / SAMPLE_RATE
        quality = self._speech_quality(recording)
        if quality < 0.10 or (dur < 1.0 and quality < 0.35):
            return None, None
        g = self.guess_gender(recording)
        if g and g != self.last_gender:
            self.last_gender = g
            self._persist_gender(g)

        text = None
        if self._vosk is not None:
            try:
                text = self._transcribe_vosk(recording)
                if not text:
                    _dbg("stt: vosk returned empty for %.2fs audio" % dur)
                    return "", None
            except Exception as e:
                print("Vosk failed, falling back to Google:", e)
        if not text and not self.offline_only:
            try:
                text = self._transcribe_google(recording)
                if not text:
                    return "", None
            except Exception as e:
                return None, str(e)
        _dbg("heard: " + text[:120])
        return text, None

    def listen_wake(self, seconds=3):
        recording, err = self._record_vad(seconds, silence_secs=0.7, onset_secs=seconds)
        if err or recording is None:
            return None, err
        if len(recording) < SAMPLE_RATE // 2 or self._rms(recording) < self.threshold * 0.95:
            return None, None
        if self._speech_quality(recording) < 0.12:
            return None, None
        try:
            if self._vosk is not None:
                text = self._transcribe_vosk(recording)
            elif not self.offline_only:
                text = self._transcribe_google(recording)
            else:
                return None, None
            if not text:
                return None, None
        except Exception as e:
            return None, str(e)
        return text, None

    def listen_wake_stream(self, matcher, max_seconds=20, abort=None):
        """Gapless wake listening: one continuous mic stream fed to Vosk while
        scanning PARTIAL results every frame. Fires the moment the wake word
        appears - no record/decode dead zones between attempts."""
        if self._vosk is None:
            text, err = self.listen_wake(seconds=3)
            if text and matcher and not matcher(text.lower()):
                return None, None
            return text, err
        from vosk import KaldiRecognizer

        rec = KaldiRecognizer(self._vosk, SAMPLE_RATE)
        rec.SetWords(False)
        block = max(1, int(SAMPLE_RATE * 0.06))
        calib = []
        preroll = deque(maxlen=14)
        hot = False
        last_voice = 0.0
        started = time.time()
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=block
            ) as stream:
                while time.time() - started < max_seconds:
                    if abort is not None and abort():
                        break
                    data, _ = stream.read(block)
                    b = data[:, 0]
                    lvl = self._rms(b)
                    if len(calib) < 25:
                        calib.append(lvl)
                        if len(calib) == 25:
                            noise = max(float(np.median(calib)), 1.0)
                            margin = float(settings.get("vad_noise_margin", 3.5))
                            floor = float(settings.get("vad_min_threshold", 250.0))
                            self.threshold = max(noise * margin, floor)
                        continue
                    if not hot:
                        preroll.append(b)
                        if lvl >= self.threshold:
                            hot = True
                            last_voice = time.time()
                            for f in list(preroll):
                                rec.AcceptWaveform(f.tobytes())
                            preroll.clear()
                        continue
                    rec.AcceptWaveform(b.tobytes())
                    if lvl >= self.threshold:
                        last_voice = time.time()
                    else:
                        if time.time() - last_voice > 1.2:
                            try:
                                json.loads(rec.FinalResult() or "{}")
                                rec.Reset()
                            except Exception:
                                pass
                            hot = False
                            continue
                    part = ""
                    try:
                        part = (json.loads(rec.PartialResult() or "{}").get("partial") or "").strip()
                    except Exception:
                        pass
                    if part and matcher(part.lower()):
                        _dbg("wake stream hit: " + part[:60])
                        return part, None
        except Exception as e:
            return None, "Microphone error: " + str(e)
        return None, None

    @staticmethod
    def _normalize(recording):
        """Amplify quiet recordings so the recognizer gets usable audio."""
        try:
            x = recording.astype(np.float32)
            if not len(x):
                return recording
            peak = float(np.max(np.abs(x)))
            if 0 < peak < 14000:
                gain = min(22000.0 / peak, 8.0)
                x *= gain
                np.clip(x, -32767, 32767, out=x)
            return x.astype(np.int16)
        except Exception:
            return recording

    def _transcribe_vosk(self, recording):
        from vosk import KaldiRecognizer
        recording = self._normalize(recording)
        rec = KaldiRecognizer(self._vosk, SAMPLE_RATE)
        rec.SetWords(False)
        raw = recording.tobytes()
        chunk = SAMPLE_RATE * 2
        for i in range(0, len(raw), chunk):
            rec.AcceptWaveform(raw[i:i + chunk])
        result = json.loads(rec.FinalResult() or "{}")
        return (result.get("text") or "").strip()

    def _transcribe_google(self, recording):
        recording = self._normalize(recording)
        r = sr.Recognizer()
        audio = sr.AudioData(recording.tobytes(), SAMPLE_RATE, BITS // 8)
        try:
            return r.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            raise RuntimeError("Could not reach the speech service. Check your internet.")
