"""Connect to a machine via mstsc and reposition the window on the best display."""
from __future__ import annotations

import argparse
import subprocess
import time
import ctypes as C
from ctypes import wintypes as W

from local_automation.utils.display import enum_displays, make_process_dpi_aware, pick_display
from local_automation.utils.window import user32, _get_text, _get_class, _get_window_pid


WINDOW_WAIT_SECONDS = 20
BOTTOM_PADDING = 15

# Initial RDP canvas size — mstsc respects /w and /h but will resize after placement.
_RDP_WIDTH  = 1900
_RDP_HEIGHT = 955


# ---------- Window search ----------

def find_rdp_window(mstsc_pid: int, host: str, timeout: int = WINDOW_WAIT_SECONDS) -> W.HWND | None:
    """
    Poll until we find the mstsc window.  Scoring prefers the window owned by
    our process, then falls back on class name and title heuristics.
    """
    EnumWindowsProc = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    deadline = time.time() + timeout

    while time.time() < deadline:
        matches: list[tuple[int, W.HWND]] = []

        def _cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True

            title      = _get_text(hwnd).lower()
            class_name = _get_class(hwnd).lower()
            pid        = _get_window_pid(hwnd)

            score = 0
            if pid == mstsc_pid:              score += 10
            if "tscshellcontainerclass" in class_name: score += 5
            if host.lower() in title:         score += 4
            if "remote desktop" in title:     score += 2

            if score > 0:
                matches.append((score, hwnd))
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)

        if matches:
            matches.sort(reverse=True, key=lambda x: x[0])
            return matches[0][1]

        time.sleep(0.25)

    return None


# ---------- Window placement ----------

def move_window_to_display(hwnd: W.HWND, display: dict) -> None:
    left   = int(display["x"])
    top    = int(display["y"])
    width  = int(display["width"])
    height = int(display["height"] - display.get("taskbar_height", 0) - BOTTOM_PADDING)

    # Un-maximize first so mstsc doesn't snap back to its previous geometry.
    SW_SHOWNORMAL = 1
    user32.ShowWindow(hwnd, SW_SHOWNORMAL)
    user32.MoveWindow(hwnd, left, top, width, height, True)


# ---------- Launch ----------

def launch_rdp(machine: str) -> subprocess.Popen:
    return subprocess.Popen([
        "mstsc.exe",
        f"/v:{machine}",
        f"/w:{_RDP_WIDTH}",
        f"/h:{_RDP_HEIGHT}",
    ])


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Connect to an on-prem machine via Remote Desktop and position the window."
    )
    parser.add_argument(
        "machine",
        type=str,
        help="DNS machine name or alias (e.g. WJVVDIANA22)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=WINDOW_WAIT_SECONDS,
        metavar="SECONDS",
        help=f"Seconds to wait for the mstsc window to appear (default: {WINDOW_WAIT_SECONDS})",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    make_process_dpi_aware()

    displays = enum_displays()
    display  = pick_display(displays)

    proc = launch_rdp(args.machine)
    hwnd = find_rdp_window(proc.pid, host=args.machine, timeout=args.wait)

    if hwnd is None:
        print(f"[warn] Could not find the mstsc window after {args.wait}s — it may still be connecting.")
        return

    move_window_to_display(hwnd, display)


if __name__ == "__main__":
    main()

