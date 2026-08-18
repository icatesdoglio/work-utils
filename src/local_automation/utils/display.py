"""Monitor/display enumeration and selection utilities."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W


# ---------- WinAPI setup ----------

user32 = C.WinDLL("user32", use_last_error=True)
shcore = C.WinDLL("shcore", use_last_error=True)

MDT_EFFECTIVE_DPI = 0


class RECT(C.Structure):
    _fields_ = [
        ("left",   C.c_long),
        ("top",    C.c_long),
        ("right",  C.c_long),
        ("bottom", C.c_long),
    ]


class MONITORINFO(C.Structure):
    _fields_ = [
        ("cbSize",    C.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork",    RECT),
        ("dwFlags",   C.c_ulong),
    ]


MONITORENUMPROC = C.WINFUNCTYPE(
    C.c_int,
    W.HMONITOR,
    W.HDC,
    C.POINTER(RECT),
    C.c_double,
)

user32.EnumDisplayMonitors.restype = C.c_bool


# ---------- DPI ----------

def make_process_dpi_aware() -> None:
    """Set DPI awareness so window coordinates behave correctly on scaled monitors."""
    try:
        user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def _get_monitor_dpi(hMonitor: W.HMONITOR) -> tuple[int, int]:
    dpi_x = C.c_uint()
    dpi_y = C.c_uint()
    shcore.GetDpiForMonitor(hMonitor, MDT_EFFECTIVE_DPI, C.byref(dpi_x), C.byref(dpi_y))
    return dpi_x.value, dpi_y.value


# ---------- Enumeration ----------

def enum_displays() -> list[dict]:
    """Return a list of monitor info dicts, one per display."""
    monitors: list[dict] = []

    def _callback(hMonitor, hdc, lprcClip, dwData):
        info = MONITORINFO()
        info.cbSize = C.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hMonitor, C.byref(info))

        rect = info.rcMonitor
        width  = rect.right  - rect.left
        height = rect.bottom - rect.top

        dpi_x, dpi_y = _get_monitor_dpi(hMonitor)

        monitors.append({
            "x":              rect.left,
            "y":              rect.top,
            "width":          width,
            "height":         height,
            "work_x":         info.rcWork.left,
            "work_y":         info.rcWork.top,
            "work_width":     info.rcWork.right  - info.rcWork.left,
            "work_height":    info.rcWork.bottom - info.rcWork.top,
            "taskbar_height": height - (info.rcWork.bottom - info.rcWork.top),
            "taskbar_width":  width  - (info.rcWork.right  - info.rcWork.left),
            "dpi_x":          dpi_x,
            "dpi_y":          dpi_y,
            "primary":        bool(info.dwFlags & 1),
        })
        return True

    cb_func = MONITORENUMPROC(_callback)
    user32.EnumDisplayMonitors(0, 0, cb_func, 0)
    return monitors


# ---------- Display selection ----------

def _left_display(displays: list[dict]) -> dict:
    return min(displays, key=lambda d: d["x"])


def _check_at_work(displays: list[dict]) -> dict:
    """
    At a 3-monitor desk, the primary is typically the center.
    Pick the leftmost non-primary so we don't land on the primary.
    """
    primary_index, primary = next(
        (i, d) for i, d in enumerate(displays) if d["primary"]
    )
    if _left_display(displays) == primary:
        non_primary = [d for i, d in enumerate(displays) if i != primary_index]
        return _left_display(non_primary)
    return _left_display(displays)


def pick_display(displays: list[dict]) -> dict:
    """
    Choose the best display for positioning an RDP window.

    - 1 monitor  → only choice
    - 2 monitors → left display
    - 3 monitors → left non-primary (laptop + 2 external setup heuristic)
    - 4+         → leftmost
    """
    match len(displays):
        case 1:
            return displays[0]
        case 2:
            return _left_display(displays)
        case 3:
            return _check_at_work(displays)
        case _:
            return _left_display(displays)


if __name__ == "__main__":
    for i, m in enumerate(enum_displays()):
        print(f"\nDISPLAY {i}:")
        for k, v in m.items():
            print(f"  {k} = {v}")
