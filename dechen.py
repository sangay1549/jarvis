import ctypes
import os
import sys
import traceback

from ai import Brain
from assistant import Assistant
from audio import VoiceIO
from config import settings
from gui import DechenGUI
from skills import ReminderManager

_MUTEX = "Jarvis_SingleInstance_Mutex"


def _already_running():
    if os.name != "nt":
        return False
    ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX)
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def main():
    vo = VoiceIO()
    gui = DechenGUI()
    brain = Brain()
    reminders = ReminderManager()

    assistant = Assistant(vo, gui, brain, reminders)
    reminders.set_handler(assistant.on_reminder_due)
    gui.on_talk = assistant.talk
    gui.ai_mode = brain.mode.upper()
    brain.on_error = gui.log_sys

    gui.log_sys("Brain: local scripts - instant replies, no API delay.")
    gui.log_sys("Say '" + settings.get("wake_word", "jarvis") + "' anytime - no clicks needed.")
    gui.log_sys("After each reply I stay open for one minute - ask anything, no wake word needed.")

    if settings.get("wake_enabled", True):
        gui.log_sys("Wake word active: say '" + settings.get("wake_word", "jarvis") + "'.")
    assistant.start_wake()

    gui.run()


if __name__ == "__main__":
    if _already_running():
        print("Jarvis is already running - close that window first.")
        try:
            import tkinter.messagebox as mb
            mb.showwarning("J.A.R.V.I.S.", "Jarvis is already running.\nClose the other Jarvis window first.")
        except Exception:
            pass
        sys.exit(0)
    try:
        main()
    except Exception:
        try:
            with open("error.log", "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n\n")
        except Exception:
            pass
        raise