"""Liga/desliga a abertura automática do SaveSync quando o Windows inicia."""
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "SaveSync"


def command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    main = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
    return f'"{pythonw}" "{main}" --startup'


def set_enabled(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE)
            except FileNotFoundError:
                pass


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, VALUE)[0])
    except OSError:
        return False
