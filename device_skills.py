import glob
import json
import os
import re
import subprocess
import time


def _pictures_dir():
    pics = os.path.join(os.path.expanduser("~"), "Pictures")
    os.makedirs(pics, exist_ok=True)
    return pics


def take_photo():
    try:
        import cv2
    except ImportError:
        return None, "OpenCV is not installed. Run: pip install opencv-python"
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return None, "I couldn't access your camera."
    frame = None
    for _ in range(10):
        ret, f = cap.read()
        if ret:
            frame = f
        time.sleep(0.04)
    cap.release()
    if frame is None:
        return None, "The camera didn't return an image."
    frame = cv2.flip(frame, 1)
    folder = os.path.join(_pictures_dir(), "Jarvis")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "photo_" + time.strftime("%Y%m%d_%H%M%S") + ".jpg")
    try:
        cv2.imwrite(path, frame)
    except Exception as e:
        return None, "Couldn't save the photo. " + str(e)
    return path, None


def latest_image():
    folders = [
        os.path.join(_pictures_dir(), "Jarvis"),
        os.path.join(_pictures_dir(), "Screenshots"),
        os.path.join(_pictures_dir(), "Camera Roll"),
        _pictures_dir(),
        os.path.join(os.path.expanduser("~"), "Desktop"),
    ]
    best = None
    seen = set()
    for folder in folders:
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            for p in glob.glob(os.path.join(folder, ext)):
                if p in seen:
                    continue
                seen.add(p)
                if best is None or os.path.getmtime(p) > os.path.getmtime(best):
                    best = p
    return best


def list_printers():
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Printer | Select-Object Name,Default,WorkOffline | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=25,
        )
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        return [
            (d.get("Name", "?"), bool(d.get("Default")), bool(d.get("WorkOffline")))
            for d in data
        ], None
    except Exception as e:
        return [], str(e)


def _match_printer(name, printers):
    name = re.sub(r"\b(the|printer|default|to|as)\b", "", name).strip()
    if not name:
        return None
    a = name.lower()
    for entry in printers:
        b = entry[0].lower()
        if a in b or b in a:
            return entry[0]
    tokens = [t for t in a.split() if len(t) > 2]
    for entry in printers:
        b = entry[0].lower()
        if tokens and any(t in b for t in tokens):
            return entry[0]
    return None


def set_default_printer(name):
    printers, err = list_printers()
    if err:
        return None, err
    target = _match_printer(name, printers)
    if not target:
        return None, "I couldn't find a printer matching " + name + "."
    subprocess.Popen('RUNDLL32 PRINTUI.DLL,PrintUIEntry /y /n "{}"'.format(target), shell=True)
    return target, None


def print_test_page(printer_name=None):
    target = printer_name
    if not target:
        printers, err = list_printers()
        if err:
            return None, err
        defaults = [p[0] for p in printers if p[1]]
        target = defaults[0] if defaults else (printers[0][0] if printers else None)
    if not target:
        return None, "no printer found"
    subprocess.Popen('RUNDLL32 PRINTUI.DLL,PrintUIEntry /k /n "{}"'.format(target), shell=True)
    return target, None


def print_file(path):
    try:
        os.startfile(path, "print")
        return os.path.basename(path), None
    except Exception as e:
        return None, str(e)
