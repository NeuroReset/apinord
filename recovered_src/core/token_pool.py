"""
Unified token acquisition: single entry point for gee_token generation.
Priority: 1) Token Server pool, 2) Puppeteer (gen_geetoken.js), 3) Legacy client_report.
Thread-safe with double-checked locking.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

TOKEN_SERVER_URL = "http://localhost:3333"
MAX_USES_PER_TOKEN = 95

_lock = threading.Lock()
_gen_lock = threading.Lock()
_current_token = ""
_uses_left = 0
_total_generated = 0


def _get_script_dir() -> str:
    if getattr(sys, "frozen", False) or "__compiled__" in dir():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _project_root() -> str:
    if getattr(sys, "frozen", False) or "__compiled__" in dir():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fetch_from_server() -> str:
    """Fetch a token from the local Token Server (localhost:3333)."""
    try:
        resp = urllib.request.urlopen(f"{TOKEN_SERVER_URL}/token", timeout=35)
        data = json.loads(resp.read().decode("utf-8"))
        token = data.get("gee_token")
        pool = data.get("pool_remaining", "?")
        if data.get("success") and token:
            print(f"[POOL] Token Server OK (pool={pool}): {token[:20]}...")
            return token
    except Exception as e:
        print(f"[POOL] Token Server indisponível: {e}")
    return ""


def _restart_server():
    """Restart Token Server via core.token_manager."""
    try:
        from core.token_manager import _reconfigure_token_server, ensure_token_server

        print("[POOL] Reiniciando Token Server...")
        if ensure_token_server():
            _reconfigure_token_server()
            time.sleep(5)
            return True
    except Exception as e:
        print(f"[POOL] Falha ao reiniciar Token Server: {e}")
    return False


def _try_puppeteer() -> str:
    """Try generating via gen_geetoken.js (Puppeteer). Returns '' on failure."""
    script_path = os.path.join(_project_root(), "geetest", "gen_geetoken.js")
    if not os.path.exists(script_path):
        return ""

    env = os.environ.copy()
    env["GEE_APPID"] = "9ia4hndgblg9xihxcwgdjt9ztg8sjwaf"

    try:
        result = subprocess.run(
            ["node", script_path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(script_path),
            env=env,
        )
        if result.returncode != 0:
            print(f"[POOL] Puppeteer falhou (exit {result.returncode}): {result.stderr}")
            return ""

        data = json.loads(result.stdout)
        token = data.get("gee_token")
        if not token:
            print(f"[POOL] Puppeteer: sem gee_token: {result.stdout[:150]}")
            return ""
        return token
    except FileNotFoundError:
        return ""
    except Exception as e:
        print(f"[POOL] Puppeteer erro: {e}")
        return ""


def _generate_with_retry() -> str:
    """
    Retry loop: Token Server -> Puppeteer -> restart -> repeat.
    Never returns empty — keeps trying up to 10 cycles.
    """
    max_cycles = 10
    for cycle in range(max_cycles):
        token = _try_puppeteer()
        if token:
            return token

        token = _fetch_from_server()
        if token:
            return token

        print(f"[POOL] Nenhum método gerou token (ciclo {cycle + 1}/{max_cycles}). Reiniciando...")
        _restart_server()
        wait_secs = min(30, (cycle + 1) * 5)
        print(f"[POOL] Aguardando {wait_secs}s para pool encher...")
        time.sleep(wait_secs)

    print("[POOL] TODAS tentativas falharam. Usando fallback legado...")
    return _fallback_client_report()


def _fallback_client_report() -> str:
    """Last resort: generate via GeeTest client_report API directly."""
    try:
        import hashlib
        import tls_client

        session = tls_client.Session(
            client_identifier="chrome_146",
            random_tls_extension_order=True,
        )

        guard_hashes = [
            "ad192bb5891726240f7bcc1d137507302bce7d844c7484574ff270c4327c864c",
            "9fa267e473e9f860762bf51c85601879324a29010ea786180276847f1e6185e7",
        ]
        header = bytes((71, 69, 69, 0, 6))
        body = "".join(guard_hashes).encode("ascii")
        payload = base64.b64encode(header + body).decode("ascii")
        payload = f'"{payload}"'

        headers = {
            "accept": "*/*",
            "api-version": "1",
            "appid": "9ia4hndgblg9xihxcwgdjt9ztg8sjwaf",
            "client-type": "3",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://d11dm6tasib5wm.cloudfront.net",
            "referer": "https://d11dm6tasib5wm.cloudfront.net/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
            ),
        }
        response = session.post(
            "https://riskct.geetest.com/g2/api/v1/client_report",
            data=payload,
            headers=headers,
        )
        data = response.json()
        if response.status_code == 200 and data.get("success"):
            return data.get("data", {}).get("gee_token", "")
    except Exception as e:
        print(f"[POOL] Fallback legado falhou: {e}")
    return ""


def get_token() -> str:
    """Returns a valid gee_token. Thread-safe with double-checked locking."""
    global _current_token, _uses_left, _total_generated

    with _lock:
        if _uses_left > 0 and _current_token:
            _uses_left -= 1
            print(f"[POOL] Token reutilizado (restam {_uses_left} usos)")
            return _current_token

    with _gen_lock:
        with _lock:
            if _uses_left > 0 and _current_token:
                _uses_left -= 1
                return _current_token

        print("[POOL] Gerando novo gee_token...")
        start = time.time()
        token = _generate_with_retry()
        elapsed = time.time() - start

        with _lock:
            _current_token = token
            _uses_left = MAX_USES_PER_TOKEN
            _total_generated += 1

        print(
            f"[POOL] Novo gee_token #{_total_generated} em {elapsed:.1f}s "
            f"({len(token)} chars, {_uses_left} usos)"
        )
        return token


def reset():
    """Reset the token cache (used when switching platforms)."""
    global _current_token, _uses_left
    with _lock:
        _current_token = ""
        _uses_left = 0
