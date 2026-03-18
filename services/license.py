"""
Sistema de licenciamento com HWID + Supabase
Modo QA permite rodar local sem autenticação
"""

import base64
import ctypes
import datetime
import hashlib
import hmac
import json
import os
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import winreg

QA_MODE = True

SUPABASE_URL = "https://ejwqwvscplpvvkulahac.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

LICENSE_FILE = "license.key"
CACHE_FILE = ".lcache"


def _run_wmic(command):
    try:
        result = subprocess.check_output(
            command,
            shell=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        lines = [line.strip() for line in result.split("\n") if line.strip()]
        if len(lines) > 1:
            return lines[1]
        if lines:
            return lines[0]
        return ""
    except Exception:
        return ""


def _get_machine_guid():
    try:
        reg_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Cryptography",
        )
        value, _ = winreg.QueryValueEx(reg_key, "MachineGuid")
        winreg.CloseKey(reg_key)
        return value
    except Exception:
        return ""


def generate_hwid():
    components = [
        f"CPU:{_run_wmic('wmic cpu get ProcessorId')}",
        f"DISK:{_run_wmic('wmic diskdrive get SerialNumber')}",
        f"MB:{_run_wmic('wmic baseboard get SerialNumber')}",
        f"GUID:{_get_machine_guid()}",
    ]
    raw = "|".join(components)
    return hashlib.sha256(raw.encode()).hexdigest()


def _derive_cache_key(hwid):
    salt = b"dCpY_aNt1cL0nE_s4Lt_2026"
    return hashlib.pbkdf2_hmac("sha256", hwid.encode(), salt, 100000)


def _xor_crypt(data, key):
    result = bytearray(len(data))
    keystream = bytearray()
    block = key

    while len(keystream) < len(data):
        block = hashlib.sha256(block).digest()
        keystream.extend(block)

    for i, v in enumerate(data):
        result[i] = v ^ keystream[i]

    return bytes(result)


def save_hwid_cache(hwid, license_key):
    try:
        cache_key = _derive_cache_key(hwid)

        payload = {
            "h": hwid,
            "k": license_key,
            "t": int(time.time()),
            "g": _get_machine_guid(),
        }

        payload_bytes = json.dumps(payload).encode()
        mac = hmac.new(cache_key, payload_bytes, hashlib.sha256).digest()

        encrypted = _xor_crypt(payload_bytes, cache_key)

        blob = struct.pack("<I", len(mac)) + mac + encrypted

        with open(CACHE_FILE, "w") as f:
            f.write(base64.b64encode(blob).decode())

    except Exception:
        pass


def verify_hwid_cache(hwid):
    if not os.path.exists(CACHE_FILE):
        return "missing"

    try:
        with open(CACHE_FILE) as f:
            blob = base64.b64decode(f.read())

        mac_len = struct.unpack("<I", blob[:4])[0]

        mac = blob[4 : 4 + mac_len]
        encrypted = blob[4 + mac_len :]

        cache_key = _derive_cache_key(hwid)

        payload_bytes = _xor_crypt(encrypted, cache_key)

        expected = hmac.new(cache_key, payload_bytes, hashlib.sha256).digest()

        if not hmac.compare_digest(mac, expected):
            return "clone"

        payload = json.loads(payload_bytes.decode())

        if payload.get("h") != hwid:
            return "clone"

        return "ok"

    except Exception:
        return "corrupt"


def _call_supabase_rpc(function_name, params):
    url = f"{SUPABASE_URL}/rest/v1/rpc/{function_name}"

    data = json.dumps(params).encode()

    req = urllib.request.Request(url, data=data, method="POST")

    req.add_header("Content-Type", "application/json")
    req.add_header("apikey", SUPABASE_ANON_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_ANON_KEY}")

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except Exception as exc:
        return {"error": str(exc)}


def validate_license(license_key, hwid):

    payloads = [
        {"p_key": license_key, "p_hwid": hwid},
        {"license_key": license_key, "hwid": hwid},
        {"key": license_key, "hwid": hwid},
    ]

    for payload in payloads:
        result = _call_supabase_rpc("validate_license", payload)

        if isinstance(result, dict) and result.get("code") != "PGRST202":
            return result

    return {"error": "rpc_failed"}


def license_check_flow():

    if QA_MODE:
        print("[QA MODE] Licenciamento desativado")
        return (
            {
                "success": True,
                "days_remaining": 9999,
                "config": {"platforms": {"default": True}},
            },
            {"default": True},
        )

    print("Gerando HWID...")

    hwid = generate_hwid()

    cache_status = verify_hwid_cache(hwid)

    if cache_status == "clone":
        print("Licenca invalida")
        sys.exit(1)

    if os.path.exists(LICENSE_FILE):
        with open(LICENSE_FILE) as f:
            license_key = f.read().strip()
    else:
        license_key = input("Key: ").strip()

    result = validate_license(license_key, hwid)

    if result.get("error"):
        print("Erro:", result["error"])
        sys.exit(1)

    save_hwid_cache(hwid, license_key)

    return result, result.get("config", {})


class LicenseMonitor:

    def __init__(self, license_key=None, hwid=None, interval=1800):
        self._key = license_key
        self._hwid = hwid
        self._interval = interval
        self._stop = False

    def start(self):

        if QA_MODE:
            print("[QA MODE] Monitor de licenca desativado")
            return

        import threading

        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def stop(self):
        self._stop = True

    def _loop(self):

        while not self._stop:

            time.sleep(self._interval)

            result = validate_license(self._key, self._hwid)

            if result.get("error"):
                print("Licenca invalidada")
                os._exit(1)

def load_saved_key():
    try:
        if os.path.exists(LICENSE_FILE):
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
        return None
    except Exception:
        return None


def save_key(key):
    try:
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            f.write(key.strip())
    except Exception:
        return None