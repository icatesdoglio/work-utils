from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W


user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)

# ---------- WinAPI types ----------
EnumWindowsProc = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

# Prototypes
user32.EnumWindows.argtypes = [EnumWindowsProc, W.LPARAM]
user32.EnumWindows.restype = W.BOOL

user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsWindowVisible.restype = W.BOOL

user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.GetWindowTextW.restype = C.c_int

user32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.GetClassNameW.restype = C.c_int

user32.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user32.GetWindowRect.restype = W.BOOL

user32.IsIconic.argtypes = [W.HWND]
user32.IsIconic.restype = W.BOOL

user32.IsZoomed = getattr(user32, "IsZoomed", None)
if user32.IsZoomed:
    user32.IsZoomed.argtypes = [W.HWND]
    user32.IsZoomed.restype = W.BOOL

user32.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint]
user32.SetWindowPos.restype = W.BOOL

user32.ShowWindow.argtypes = [W.HWND, C.c_int]
user32.ShowWindow.restype = W.BOOL

user32.MoveWindow.argtypes = [W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.BOOL]
user32.MoveWindow.restype = W.BOOL

user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD

user32.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
user32.MonitorFromWindow.restype = W.HMONITOR

user32.GetDesktopWindow.argtypes = []
user32.GetDesktopWindow.restype = W.HWND

MONITORINFOF_PRIMARY = 0x00000001

class MONITORINFO(C.Structure):
    _fields_ = [
        ('cbSize', W.DWORD),
        ('rcMonitor', W.RECT),
        ('rcWork', W.RECT),
        ('dwFlags', W.DWORD),
    ]

user32.GetMonitorInfoW.argtypes = [W.HMONITOR, C.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = W.BOOL

SWP_NOZORDER   = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

HWND_TOP = W.HWND(0)

# ---------- Helpers ----------
def _get_text(hwnd: W.HWND) -> str:
    buf = C.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value

def _get_class(hwnd: W.HWND) -> str:
    buf = C.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def _get_rect(hwnd: W.HWND) -> tuple[int, int, int, int] | None:
    r = W.RECT()
    if not user32.GetWindowRect(hwnd, C.byref(r)):
        return None
    return r.left, r.top, r.right - r.left, r.bottom - r.top

def _primary_monitor_workarea() -> tuple[int, int, int, int]:
    # Use desktop window to find a monitor and then locate the primary
    desktop = user32.GetDesktopWindow()
    hmon = user32.MonitorFromWindow(desktop, 1)  # MONITOR_DEFAULTTOPRIMARY
    mi = MONITORINFO()
    mi.cbSize = C.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmon, C.byref(mi))
    # Work area excludes taskbar; choose rcMonitor if you want full screen geometry
    x = mi.rcWork.left
    y = mi.rcWork.top
    w = mi.rcWork.right - mi.rcWork.left
    h = mi.rcWork.bottom - mi.rcWork.top
    return x, y, w, h

def enum_windows() -> list[dict]:
    out = []


    def cb(hwnd, lparam):
        if user32.IsZoomed: 
            maximized = bool(user32.IsZoomed(hwnd))
        else:
            maximized = False
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _get_text(hwnd)
        if not title:
            return True
        rect = _get_rect(hwnd)
        if not rect:
            return True
        klass = _get_class(hwnd)
        # skip toolbars / invisible styles by heuristics
        out.append({
            "hwnd": int(hwnd),
            "title": title,
            "class": klass,
            "rect": {
                "x": rect[0],
                "y": rect[1],
                "w": rect[2],
                "h": rect[3]
                },
            "minimized": bool(user32.IsIconic(hwnd)),
            "maximized": maximized
        })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out

def _get_window_pid(hwnd: W.HWND) -> int:
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return pid.value


def get_application_frame_window(hmon): 
    for win in hmon:
        if win["class"] == "ApplicationFrameWindow":
            return win
    raise KeyError("No Application window in hmon")

if __name__ == "__main__":
    for win in enum_windows():
        print(win)
