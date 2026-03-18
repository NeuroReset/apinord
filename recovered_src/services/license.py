"""
Sistema de licenciamento com HWID + Supabase
Modo QA permite rodar local sem autenticação
"""

import base64
import ctypes
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


_K = bytes(
[
104,200,192,16,2,160,145,120,161,211,197,208,45,98,162,8,
106,235,65,28,145,26,159,152,72,129,112,0,19,75,11,101
]
)


def _d(b64):
    data = base64.b64decode(b64)
    result = bytearray(len(data))
    for idx,value in enumerate(data):
        result[idx] = value ^ _K[idx % len(_K)]
    return bytes(result).decode("utf-8")


SUPABASE_URL = "https://sonjfneihntrponjbxxr.supabase.co"

SUPABASE_ANON_KEY = _d(
"DbGKeGDn8hHuuo+ZeBjrOSSCCG/YdM2tK8I5Nlogez0+i4opLMXoMtGw9p1ELctCEI8ZXvlD8t4y2yNJYAJlLwSSqVk06f8q1on2hhkAkF4QsnJG+X/H8H7gHWxpKGZUHYGpZ2vD/EHSiZaZGyvPTh+Jcyj4VtzSONgoUXoEYSBbhrpRN+7VNZOegYFeK89eXogCVadX9dl8zxpVawRfPB+GiCAs8fg80+qduRRT5lcjhTFZ9lXTyC3AFS0jeGYBHYWUVVrXy0zOm6mTdAn9OA=="
)

LICENSE_FILE="license.key"
CACHE_FILE=".lcache"


def _run_wmic(command):
    try:
        result=subprocess.check_output(
            command,
            shell=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )

        lines=[l.strip() for l in result.split("\n") if l.strip()]

        if len(lines)>1:
            return lines[1]

        if lines:
            return lines[0]

        return ""

    except Exception:
        return ""


def _get_machine_guid():

    try:

        reg_key=winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Cryptography"
        )

        value,_=winreg.QueryValueEx(reg_key,"MachineGuid")

        winreg.CloseKey(reg_key)

        return value

    except Exception:
        return ""


def generate_hwid():

    components=[
        f"CPU:{_run_wmic('wmic cpu get ProcessorId')}",
        f"DISK:{_run_wmic('wmic diskdrive get SerialNumber')}",
        f"MB:{_run_wmic('wmic baseboard get SerialNumber')}",
        f"GUID:{_get_machine_guid()}"
    ]

    raw="|".join(components)

    return hashlib.sha256(raw.encode()).hexdigest()


def _derive_cache_key(hwid):

    salt=b"dCpY_aNt1cL0nE_s4Lt_2026"

    return hashlib.pbkdf2_hmac(
        "sha256",
        hwid.encode(),
        salt,
        100000
    )


def _xor_crypt(data,key):

    result=bytearray(len(data))
    keystream=bytearray()
    block=key

    while len(keystream)<len(data):

        block=hashlib.sha256(block).digest()

        keystream.extend(block)

    for i,v in enumerate(data):

        result[i]=v ^ keystream[i]

    return bytes(result)


def validate_license(license_key,hwid):

    if QA_MODE:

        return {
            "success":True,
            "days_remaining":9999,
            "config":{"platforms":{"default":True}}
        }

    url=f"{SUPABASE_URL}/rest/v1/rpc/validate_license"

    payload={
        "p_key":license_key,
        "p_hwid":hwid
    }

    data=json.dumps(payload).encode()

    req=urllib.request.Request(url,data=data,method="POST")

    req.add_header("Content-Type","application/json")
    req.add_header("apikey",SUPABASE_ANON_KEY)
    req.add_header("Authorization",f"Bearer {SUPABASE_ANON_KEY}")

    try:

        resp=urllib.request.urlopen(req,timeout=15)

        return json.loads(resp.read().decode())

    except Exception as exc:

        return {"error":str(exc)}


def license_check_flow():

    if QA_MODE:

        print("[QA MODE] Licenciamento desativado")

        return (
            {
                "success":True,
                "days_remaining":9999,
                "config":{"platforms":{"default":True}}
            },
            {"default":True}
        )

    from colorama import Fore,Style

    print(
        f"{Fore.CYAN}Gerando identificador do hardware...{Style.RESET_ALL}",
        end="",
        flush=True
    )

    hwid=generate_hwid()

    print(f"\r{Fore.GREEN}[OK] Hardware ID gerado.{Style.RESET_ALL}")

    license_key=input("Key: ").strip()

    result=validate_license(license_key,hwid)

    if result.get("error"):

        print("Erro:",result["error"])

        sys.exit(1)

    return result,result.get("config",{})


class LicenseMonitor:

    def __init__(self,license_key=None,hwid=None,interval=1800):

        self._key=license_key
        self._hwid=hwid
        self._interval=interval
        self._stop=False


    def start(self):

        if QA_MODE:

            print("[QA MODE] LicenseMonitor desativado")

            return

        import threading

        t=threading.Thread(target=self._loop,daemon=True)

        t.start()


    def stop(self):

        self._stop=True


    def _loop(self):

        while not self._stop:

            time.sleep(self._interval)

            result=validate_license(self._key,self._hwid)

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