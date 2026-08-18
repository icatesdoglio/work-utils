"""Connect / disconnect Windows VPN entries using the RAS API (rasapi32.dll)."""
from __future__ import annotations

import argparse
import getpass
import ctypes as C
from ctypes import wintypes as W

import keyring

_KEYRING_SERVICE = "local_automation/vpn"


# ---------- Constants ----------

RAS_MaxEntryName      = 256
RAS_MaxPhoneNumber    = 128
RAS_MaxCallbackNumber = 128
RAS_MaxDeviceType     = 16
RAS_MaxDeviceName     = 128
MAX_PATH              = 260
UNLEN                 = 256
PWLEN                 = 256
DNLEN                 = 15

RASCS_Connected    = 0x2000
RASCS_Disconnected = 0x2001

ERROR_BUFFER_TOO_SMALL = 603


# ---------- Structures ----------

class RASENTRYNAME(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("dwSize",          W.DWORD),
        ("szEntryName",     C.c_wchar * (RAS_MaxEntryName + 1)),
        ("dwFlags",         W.DWORD),
        ("szPhonebookPath", C.c_wchar * (MAX_PATH + 1)),
    ]


class RASDIALPARAMS(C.Structure):
    _pack_ = 4
    _fields_ = [
        ("dwSize",            W.DWORD),
        ("szEntryName",       C.c_wchar * (RAS_MaxEntryName + 1)),
        ("szPhoneNumber",     C.c_wchar * (RAS_MaxPhoneNumber + 1)),
        ("szCallbackNumber",  C.c_wchar * (RAS_MaxCallbackNumber + 1)),
        ("szUserName",        C.c_wchar * (UNLEN + 1)),
        ("szPassword",        C.c_wchar * (PWLEN + 1)),
        ("szDomain",          C.c_wchar * (DNLEN + 1)),
        ("dwSubEntry",        W.DWORD),
        ("dwCallbackId",      C.c_size_t),   # ULONG_PTR
        ("dwIfIndex",         W.DWORD),
    ]


class GUID(C.Structure):
    _fields_ = [
        ("Data1", W.DWORD),
        ("Data2", W.WORD),
        ("Data3", W.WORD),
        ("Data4", C.c_byte * 8),
    ]


class LUID(C.Structure):
    _fields_ = [
        ("LowPart",  W.DWORD),
        ("HighPart", W.LONG),
    ]


HRASCONN = C.c_void_p


class RASCONN(C.Structure):
    _pack_ = 4   # rasapi32 structs use #pragma pack(4) in the Windows SDK
    _fields_ = [
        ("dwSize",           W.DWORD),
        ("hrasconn",         HRASCONN),
        ("szEntryName",      C.c_wchar * (RAS_MaxEntryName + 1)),
        ("szDeviceType",     C.c_wchar * (RAS_MaxDeviceType + 1)),
        ("szDeviceName",     C.c_wchar * (RAS_MaxDeviceName + 1)),
        ("szPhonebook",      C.c_wchar * MAX_PATH),
        ("dwSubEntry",       W.DWORD),
        ("guidEntry",        GUID),
        ("dwFlags",          W.DWORD),
        ("luid",             LUID),
        ("guidCorrelationId", GUID),
    ]


class RASCONNSTATUS(C.Structure):
    _fields_ = [
        ("dwSize",        W.DWORD),
        ("rasconnstate",  W.DWORD),
        ("dwError",       W.DWORD),
        ("szDeviceType",  C.c_wchar * (RAS_MaxDeviceType + 1)),
        ("szDeviceName",  C.c_wchar * (RAS_MaxDeviceName + 1)),
        ("szPhoneNumber", C.c_wchar * (RAS_MaxPhoneNumber + 1)),
    ]


# ---------- RAS API ----------

_rasapi32 = C.WinDLL("rasapi32", use_last_error=True)

_rasapi32.RasEnumEntriesW.argtypes = [
    W.LPCWSTR, W.LPCWSTR,
    C.POINTER(RASENTRYNAME), C.POINTER(W.DWORD), C.POINTER(W.DWORD),
]
_rasapi32.RasEnumEntriesW.restype = W.DWORD

_rasapi32.RasEnumConnectionsW.argtypes = [
    C.POINTER(RASCONN), C.POINTER(W.DWORD), C.POINTER(W.DWORD),
]
_rasapi32.RasEnumConnectionsW.restype = W.DWORD

_rasapi32.RasDialW.argtypes = [
    C.c_void_p,               # LPRASDIALEXTENSIONS (NULL = defaults)
    W.LPCWSTR,                # phonebook path (NULL = default)
    C.POINTER(RASDIALPARAMS),
    W.DWORD,                  # dwNotifierType
    C.c_void_p,               # lpvNotifier (NULL = synchronous)
    C.POINTER(HRASCONN),
]
_rasapi32.RasDialW.restype = W.DWORD

_rasapi32.RasHangUpW.argtypes = [HRASCONN]
_rasapi32.RasHangUpW.restype = W.DWORD

_rasapi32.RasGetConnectStatusW.argtypes = [HRASCONN, C.POINTER(RASCONNSTATUS)]
_rasapi32.RasGetConnectStatusW.restype = W.DWORD

_rasapi32.RasGetEntryDialParamsW.argtypes = [
    W.LPCWSTR,                # phonebook path (NULL = default)
    C.POINTER(RASDIALPARAMS),
    C.POINTER(W.BOOL),        # lpfPassword — set to TRUE if a saved password was retrieved
]
_rasapi32.RasGetEntryDialParamsW.restype = W.DWORD

_rasapi32.RasSetEntryDialParamsW.argtypes = [
    W.LPCWSTR,                # phonebook path (NULL = default)
    C.POINTER(RASDIALPARAMS),
    W.BOOL,                   # fRemovePassword — TRUE to clear the stored password
]
_rasapi32.RasSetEntryDialParamsW.restype = W.DWORD


def _ras_error(code: int) -> str:
    buf = C.create_unicode_buffer(512)
    _rasapi32.RasGetErrorStringW(code, buf, len(buf))
    msg = buf.value.strip()
    if not msg:
        msg = C.FormatError(code).strip()
    return msg or f"RAS error {code}"


# ---------- Public helpers ----------

def enum_ras_entries() -> list[str]:
    """Return the names of all VPN/dial-up entries in the default phonebook."""
    cb       = W.DWORD(C.sizeof(RASENTRYNAME))
    count    = W.DWORD(0)
    entry    = RASENTRYNAME()
    entry.dwSize = C.sizeof(RASENTRYNAME)

    ret = _rasapi32.RasEnumEntriesW(None, None, C.byref(entry), C.byref(cb), C.byref(count))

    if ret == ERROR_BUFFER_TOO_SMALL or count.value > 1:
        arr = (RASENTRYNAME * count.value)()
        for e in arr:
            e.dwSize = C.sizeof(RASENTRYNAME)
        ret = _rasapi32.RasEnumEntriesW(None, None, arr, C.byref(cb), C.byref(count))
        if ret != 0:
            raise OSError(_ras_error(ret))
        return [arr[i].szEntryName for i in range(count.value)]

    if ret != 0:
        raise OSError(_ras_error(ret))

    return [entry.szEntryName] if count.value else []


def enum_ras_connections() -> list[dict]:
    """Return active RAS/VPN connections as dicts with 'entry', 'device_type', 'device_name'."""
    cb    = W.DWORD(C.sizeof(RASCONN))
    count = W.DWORD(0)
    conn  = RASCONN()
    conn.dwSize = C.sizeof(RASCONN)

    ret = _rasapi32.RasEnumConnectionsW(C.byref(conn), C.byref(cb), C.byref(count))

    if ret == ERROR_BUFFER_TOO_SMALL or count.value > 1:
        arr = (RASCONN * count.value)()
        for c in arr:
            c.dwSize = C.sizeof(RASCONN)
        ret = _rasapi32.RasEnumConnectionsW(arr, C.byref(cb), C.byref(count))
        if ret != 0:
            raise OSError(_ras_error(ret))
        return [
            {
                "entry":       arr[i].szEntryName,
                "device_type": arr[i].szDeviceType,
                "device_name": arr[i].szDeviceName,
                "hrasconn":    arr[i].hrasconn,
            }
            for i in range(count.value)
        ]

    if ret != 0:
        raise OSError(_ras_error(ret))

    if count.value == 0:
        return []

    return [{
        "entry":       conn.szEntryName,
        "device_type": conn.szDeviceType,
        "device_name": conn.szDeviceName,
        "hrasconn":    conn.hrasconn,
    }]


def ras_dial(entry: str, *, username: str = "", password: str = "", domain: str = "") -> None:
    """
    Connect to a RAS/VPN phonebook entry synchronously.

    Credential lookup order:
      1. CLI flags (--user / --password / --domain)
      2. keyring / Windows Credential Manager (saved via `vpn save-creds`)
      3. RAS phonebook (RasGetEntryDialParams — unreliable on modern Windows)
      4. Interactive prompt as last resort

    Raises OSError on failure.
    """
    params = RASDIALPARAMS()
    params.dwSize      = C.sizeof(RASDIALPARAMS)
    params.szEntryName = entry

    # --- 1. Seed from RAS phonebook (gets username/domain reliably; password rarely) ---
    has_pw_ras = W.BOOL(False)
    _rasapi32.RasGetEntryDialParamsW(None, C.byref(params), C.byref(has_pw_ras))

    # --- 2. Overlay keyring credentials (more reliable on modern Windows) ---
    if not password:
        stored = keyring.get_credential(_KEYRING_SERVICE, entry)
        if stored:
            raw = stored.password  # "DOMAIN\\user:password" or "user:password"
            kr_user, _, kr_pass = raw.partition(":")
            if "\\" in kr_user:
                kr_domain, _, kr_user = kr_user.partition("\\")
                if not params.szDomain:
                    params.szDomain = kr_domain
            if not params.szUserName:
                params.szUserName = kr_user
            params.szPassword = kr_pass

    # --- 3. CLI overrides (highest priority) ---
    if username:
        params.szUserName = username
    if password:
        params.szPassword = password
    if domain:
        params.szDomain = domain

    # --- 4. Prompt as last resort ---
    if not params.szPassword:
        user_display = params.szUserName or "(unknown)"
        print(f"[warn] No saved password found for '{entry}' — run: vpn save-creds {entry}")
        params.szPassword = getpass.getpass(f"Password for {user_display}: ")

    hconn = HRASCONN(None)
    ret   = _rasapi32.RasDialW(None, None, C.byref(params), 0, None, C.byref(hconn))

    if ret != 0:
        if hconn.value:
            _rasapi32.RasHangUpW(hconn)
        raise OSError(_ras_error(ret))


def ras_hangup(entry: str) -> None:
    """
    Disconnect an active RAS/VPN connection by entry name.
    Raises KeyError if no matching connection is found.
    Raises OSError on API failure.
    """
    conns = enum_ras_connections()
    match = next((c for c in conns if c["entry"].lower() == entry.lower()), None)
    if match is None:
        raise KeyError(f"No active connection found for entry '{entry}'")

    hconn = HRASCONN(match["hrasconn"])
    ret   = _rasapi32.RasHangUpW(hconn)
    if ret != 0:
        raise OSError(_ras_error(ret))


def ras_save_creds(entry: str, *, username: str = "", password: str = "", domain: str = "") -> None:
    """
    Persist credentials for a phonebook entry in Windows Credential Manager via keyring.
    Any field left empty keeps whatever value is already saved.
    """
    existing = keyring.get_credential(_KEYRING_SERVICE, entry)

    # Keep existing values for any field not explicitly provided.
    saved_user   = username or (existing.username if existing else "")
    saved_domain = domain   or ""

    # Store "domain\\username" as the keyring username so both are retrievable.
    kr_username = f"{saved_domain}\\{saved_user}" if saved_domain else saved_user
    keyring.set_password(_KEYRING_SERVICE, entry, f"{kr_username}:{password}")


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Windows VPN connections via the RAS API.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list",   help="List available VPN phonebook entries")
    sub.add_parser("status", help="Show active VPN connections")

    p_connect = sub.add_parser("connect", help="Connect to a VPN entry")
    p_connect.add_argument("entry",      help="Phonebook entry name")
    p_connect.add_argument("--user",     default="", help="Username (uses saved credential if omitted)")
    p_connect.add_argument("--password", default="", help="Password (uses saved credential if omitted)")
    p_connect.add_argument("--domain",   default="", help="Domain (uses saved credential if omitted)")

    p_disc = sub.add_parser("disconnect", help="Disconnect an active VPN connection")
    p_disc.add_argument("entry", help="Phonebook entry name")

    p_save = sub.add_parser("save-creds", help="Save credentials to the phonebook entry")
    p_save.add_argument("entry",      help="Phonebook entry name")
    p_save.add_argument("--user",     default="", help="Username to save")
    p_save.add_argument("--password", default="", help="Password to save (prompted if omitted)")
    p_save.add_argument("--domain",   default="", help="Domain to save")

    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.cmd == "list":
        entries = enum_ras_entries()
        if not entries:
            print("No VPN entries found in the phonebook.")
        else:
            for e in entries:
                print(e)

    elif args.cmd == "status":
        conns = enum_ras_connections()
        if not conns:
            print("No active VPN connections.")
        else:
            for c in conns:
                print(f"  {c['entry']}  ({c['device_type']} / {c['device_name']})")

    elif args.cmd == "connect":
        print(f"Connecting to '{args.entry}' ...")
        ras_dial(args.entry, username=args.user, password=args.password, domain=args.domain)
        print("Connected.")

    elif args.cmd == "disconnect":
        print(f"Disconnecting '{args.entry}' ...")
        ras_hangup(args.entry)
        print("Disconnected.")

    elif args.cmd == "save-creds":
        pw = args.password or getpass.getpass(f"Password for '{args.entry}': ")
        ras_save_creds(args.entry, username=args.user, password=pw, domain=args.domain)
        print(f"Credentials saved for '{args.entry}'.")


if __name__ == "__main__":
    main()
