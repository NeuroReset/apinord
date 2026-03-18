"""
Serviço de bypass de captcha GeeTest v4.
Integrado com Token Server (Puppeteer) para tokens únicos por registro.

Observação:
- Este arquivo foi recuperado manualmente do bytecode Python 3.12.
- O bypass completo é o bloco mais intricado do módulo original.
- Para preservar o comportamento, `bypass_geetest` usa fallback para o `.pyc`
  original quando ele estiver disponível.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import random
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Dict

from services.crypto import decrypt, encrypt, md5
from services.proxy import get_proxy_kwargs, track_bandwidth

GEETEST_LOT_NUMBER = "000000cabf2f4f37bbb10c358b865c41"
GEETEST_GEN_TIME = "1623828054"
GEETEST_PASS_TOKEN = "2cc051e0c885a08dd046f1a789cffa72eddfc266f663cb2ded1ac08a5102bfe9"
GEETEST_CAPTCHA_OUTPUT = "1X_RK3ag_IKlW15iHhSywQ=="

CAPTCHA_ERROR_CODES = [26, 126, 1124, 1125, 1126, 1127, 1131]
TOKEN_SERVER_URL = "http://localhost:3333"

_token_server_available = None
_last_server_check = 0
_token_stats = {
    "puppeteer_fetched": 0,
    "puppeteer_reused": 0,
    "puppeteer_errors": 0,
    "legacy_fetched": 0,
}
_stats_lock = threading.Lock()
_puppeteer_cache = {"token": "", "token_id": "", "uses": 0, "max_uses": 100}
_puppeteer_lock = threading.Lock()
_fetch_lock = threading.Lock()
_legacy_cache = {"token": "", "uses": 0, "max_uses": 100}
_legacy_lock = threading.Lock()


def _compiled_captcha_module():
    root = Path(__file__).resolve().parents[2]
    pyc_path = root / "PYZ.pyz_extracted" / "services" / "captcha.pyc"
    if not pyc_path.exists():
        return None

    spec = importlib.util.spec_from_file_location("_compiled_services_captcha", str(pyc_path))
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gen_lot_number() -> str:
    """Gera lot_number aleatório no formato hex do GeeTest."""
    return hashlib.md5(os.urandom(32)).hexdigest()


def _gen_time() -> str:
    """Gera gen_time atual (unix timestamp)."""
    return str(int(time.time()))


def _gen_pass_token() -> str:
    """Gera pass_token aleatório no formato sha256 do GeeTest."""
    return hashlib.sha256(os.urandom(64)).hexdigest()


def _gen_captcha_output() -> str:
    """Gera captcha_output aleatório no formato base64 do GeeTest."""
    return base64.b64encode(os.urandom(16)).decode()


def _http_get(url: str, timeout: int = 5) -> dict:
    """HTTP GET usando urllib (stdlib - sem dependencias externas)."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, data: dict, timeout: int = 10) -> dict:
    """HTTP POST JSON usando urllib (stdlib)."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_token_server() -> bool:
    """Verifica se o Token Server está rodando."""
    global _token_server_available
    try:
        data = _http_get(f"{TOKEN_SERVER_URL}/health", timeout=5)
        _token_server_available = data.get("status") == "ok"
        return _token_server_available
    except Exception:
        _token_server_available = False
        return False


def get_token_server_status() -> dict:
    """Retorna status completo do Token Server."""
    try:
        return _http_get(f"{TOKEN_SERVER_URL}/status", timeout=5)
    except Exception:
        return {"error": "Token Server offline"}


def configure_token_server_domain(domain: str, gee_appid: str = None, mobile_mode: bool = False):
    """Configura o domínio do Token Server para a plataforma atual."""
    global _token_server_available

    _token_server_available = None

    with _puppeteer_lock:
        _puppeteer_cache["token"] = ""
        _puppeteer_cache["uses"] = 0
        _puppeteer_cache["token_id"] = ""

    with _legacy_lock:
        _legacy_cache["token"] = ""
        _legacy_cache["uses"] = 0

    config = {"domain": domain, "mobileMode": mobile_mode}
    if gee_appid:
        config["appId"] = gee_appid

    try:
        from services.proxy import get_proxy_url

        proxy_url = get_proxy_url()
        if proxy_url:
            config["geetest_proxies"] = [proxy_url]
    except Exception:
        pass

    data = _http_post_json(f"{TOKEN_SERVER_URL}/config", config, timeout=10)
    if data.get("success") is True:
        mode_str = " (MOBILE)" if mobile_mode else ""
        print(f"[TokenServer] Dominio atualizado: {domain}{mode_str}")
        _token_server_available = True
        return True

    _token_server_available = False
    return False


def discover_api_url(domain: str) -> str:
    """Usa o Token Server para navegar até o domínio e descobrir a URL da API."""
    try:
        data = _http_post_json(
            f"{TOKEN_SERVER_URL}/discovery", {"domain": domain}, timeout=30
        )
        if data.get("success"):
            url = data.get("api_url")
            print(f"[Discovery] API encontrada em {domain}: {url}")
            return url
        print(f"[Discovery] Falha em {domain}")
    except Exception as e:
        print(f"[Discovery] Falha em {domain}: {e}")
    return None


def fetch_from_token_server() -> str:
    """Busca um gee_token fresco do Token Server (Puppeteer)."""
    global _token_server_available, _last_server_check

    max_retries = 4
    retry_delays = (5, 10, 15, 20)

    if _token_server_available is False and time.time() - _last_server_check < 30:
        return ""

    for attempt in range(max_retries):
        try:
            data = _http_get(f"{TOKEN_SERVER_URL}/token", timeout=35)
            if data.get("success"):
                token = data.get("gee_token", "")
                pool = data.get("pool_remaining", "?")
                elapsed = data.get("elapsed_ms")
                token_id = data.get("token_id", "?")
                age = data.get("age_ms")
                is_offline = data.get("isOffline")

                if token:
                    with _stats_lock:
                        _token_stats["puppeteer_fetched"] += 1

                    with _puppeteer_lock:
                        _puppeteer_cache["token"] = token
                        _puppeteer_cache["token_id"] = token_id
                        _puppeteer_cache["uses"] = 50
                        _puppeteer_cache["max_uses"] = 50
                        _puppeteer_cache["_last_fetched_id"] = token_id

                    offline_tag = " [OFFLINE-DEBUG]" if is_offline else " [ONLINE]"
                    print(
                        f"[GEETOKEN] Puppeteer FRESH #{_token_stats['puppeteer_fetched']} "
                        f"id={token_id} (pool={pool}, gen={elapsed}ms, age={age}ms) | "
                        f"hash={token[:16]}...{token[-8:]}{offline_tag}  [reusável ~50x]"
                    )
                    _token_server_available = True
                    _last_server_check = time.time()
                    return token

            wait = retry_delays[min(attempt, len(retry_delays) - 1)]
            print(f"[POOL] Pool vazio, aguardando {wait}s... (tentativa {attempt + 1}/{max_retries})")
            time.sleep(wait)
        except Exception:
            break

    print(f"[POOL] Pool vazio após {max_retries} tentativas. Pedindo restart ao watchdog...")
    try:
        from main import ensure_token_server

        ensure_token_server()
    except Exception:
        pass

    print("[POOL] Usando fallback legado...")
    with _stats_lock:
        _token_stats["puppeteer_errors"] += 1
    _token_server_available = False
    _last_server_check = time.time()
    return ""


def _generate_dynamic_gee_payload() -> str:
    """Gera payload GeeTest com fingerprint único a cada chamada."""
    header = b"GEE\x00\x06"
    fp_parts = []
    for i in range(76):
        seed = os.urandom(64)
        chunk_input = seed + i.to_bytes(2, "big")
        fp_parts.append(hashlib.md5(chunk_input).hexdigest())

    fingerprint_hex = "".join(fp_parts)
    raw_data = header + fingerprint_hex.encode("ascii")
    b64_payload = base64.b64encode(raw_data).decode("ascii")
    return f'"{b64_payload}"'


def _generate_gee_token_legacy(session, domain: str, gee_appid: str) -> str:
    """Gera gee_token via GeeTest client_report API (método legado)."""
    payload = _generate_dynamic_gee_payload()
    chrome_ver = random.choice(("120", "122", "125", "128", "131", "133", "137", "140", "144"))
    url = "https://riskct.geetest.com/g2/api/v1/client_report"
    headers = {
        "accept": "*/*",
        "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "api-version": "1",
        "appid": gee_appid or "9ia4hndgblg9xihxcwgdjt9ztg8sjwaf",
        "client-type": "3",
        "content-type": "application/x-www-form-urlencoded",
        "origin": f"https://{domain}",
        "referer": f"https://{domain}/",
        "sec-ch-ua": f'"Not(A:Brand";v="8", "Chromium";v="{chrome_ver}", "Google Chrome";v="{chrome_ver}"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{chrome_ver}.0.0.0 Safari/537.36"
        ),
    }

    try:
        response = session.post(
            url,
            data=payload,
            headers=headers,
            timeout=15,
            **get_proxy_kwargs(),
        )
        track_bandwidth(response)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 0 and data.get("status") == "success":
                token = data.get("data", {}).get("gee_token", "")
                if token:
                    return token
    except Exception as e:
        print(f"[GEETOKEN LEGADO] Erro: {e}")
    return ""


def generate_gee_token(session, domain: str, gee_appid: str = None) -> str:
    """Gera gee_token com cache thread-safe (double-checked locking)."""
    with _puppeteer_lock:
        if _puppeteer_cache["token"] and _puppeteer_cache["uses"] > 0:
            _puppeteer_cache["uses"] -= 1
            with _stats_lock:
                _token_stats["puppeteer_reused"] += 1
            token = _puppeteer_cache["token"]
            token_id = _puppeteer_cache.get("token_id", "?")
            uses = _puppeteer_cache["uses"]
            max_uses = _puppeteer_cache["max_uses"]
            print(f"[GEETOKEN] Reusando Puppeteer ({uses}/{max_uses}) id={token_id}: {token[:16]}...{token[-8:]}")
            return token

    with _fetch_lock:
        with _puppeteer_lock:
            if _puppeteer_cache["token"] and _puppeteer_cache["uses"] > 0:
                _puppeteer_cache["uses"] -= 1
                return _puppeteer_cache["token"]

        new_token = fetch_from_token_server()
        if new_token:
            return new_token

        with _legacy_lock:
            if _legacy_cache["token"] and _legacy_cache["uses"] > 0:
                _legacy_cache["uses"] -= 1
                token = _legacy_cache["token"]
                uses = _legacy_cache["uses"]
                max_uses = _legacy_cache["max_uses"]
                print(f"[GEETOKEN] Reusando legado ({uses}/{max_uses}): {token[:20]}...")
                return token

        new_token = _generate_gee_token_legacy(
            session, domain, gee_appid or "9ia4hndgblg9xihxcwgdjt9ztg8sjwaf"
        )
        if new_token:
            with _legacy_lock:
                _legacy_cache["token"] = new_token
                _legacy_cache["uses"] = 100
                _legacy_cache["max_uses"] = 100
            with _stats_lock:
                _token_stats["legacy_fetched"] += 1
            print(f"[GEETOKEN] Novo token legado (1/100): {new_token[:20]}...")
            return new_token

    return ""


def wait_for_token_pool(min_tokens: int = 5, timeout: int = 120) -> bool:
    """Espera o Token Server ter pelo menos min_tokens prontos no pool."""
    print(f"[TokenServer] Aguardando pool ter {min_tokens} tokens...")
    start = time.time()

    while time.time() - start < timeout:
        status = get_token_server_status()
        pool = status.get("pool_size", 0)
        target = status.get("pool_target", "?")
        if pool >= min_tokens:
            print(f"[TokenServer] Pool pronto: {pool}/{target} tokens")
            return True
        print(f"[TokenServer] Pool: {pool} (aguardando {min_tokens}...)")
        time.sleep(3)

    print(f"[TokenServer] Timeout esperando pool ({timeout}s)")
    return False


def bypass_geetest(
    session,
    api_base_url: str,
    captcha_id: str,
    device_id: str,
    headers: Dict[str, str],
    crypto_key: str,
) -> bool:
    """
    Bypass do GeeTest v4 usando modo offline/failback.

    O bloco original é grande e com muitas variações. Aqui o fallback usa o
    `.pyc` original quando ele existir.
    """
    compiled = _compiled_captcha_module()
    if compiled is not None and hasattr(compiled, "bypass_geetest"):
        return compiled.bypass_geetest(
            session, api_base_url, captcha_id, device_id, headers, crypto_key
        )

    geetest_data = {
        "lot_number": _gen_lot_number(),
        "gen_time": _gen_time(),
        "pass_token": _gen_pass_token(),
        "captcha_output": _gen_captcha_output(),
        "isOffline": True,
        "mode": "offline",
    }
    token = headers.get("token", "")
    domain = headers.get("domain", "")
    site_code = headers.get("sitecode", "")
    url = f"{api_base_url}/hall/api/member/geetest/validate/v4"

    payload = {
        "account": {
            "token": token,
            "domain": domain,
            "sitecode": site_code,
            "captcha_id": captcha_id,
            "device": device_id,
            "time": int(time.time()),
        },
        "geetest": geetest_data,
    }
    encrypted_data = encrypt(payload, crypto_key)
    bypass_headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "text/plain",
        "device": device_id,
        "domain": domain,
        "nonce": uuid.uuid4().hex,
        "origin": headers.get("origin", ""),
        "referer": headers.get("referer", ""),
        "sign": md5(encrypted_data),
        "sitecode": site_code,
        "timestamp": str(int(time.time())),
        "token": token,
        "user-agent": headers.get(
            "user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ),
        "x-data-mode": "offline",
        "x-request-id": uuid.uuid4().hex,
    }

    try:
        response = session.post(
            url,
            data=encrypted_data,
            headers=bypass_headers,
            timeout=60,
            **get_proxy_kwargs(),
        )
        track_bandwidth(response)
        if response.status_code == 200:
            result = json.loads(response.text.strip())
            code = result.get("code", result.get("status"))
            return code in (0, 1, 200, "0", "1", "200")
    except Exception:
        pass

    return False
