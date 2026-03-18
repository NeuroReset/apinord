"""
Token Server lifecycle management: start, stop, watchdog, health checks.
Recovered manually from Python 3.12 bytecode.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from colorama import Fore, Style

from core.utils import PROXY_FILE, _kill_stale_port_processes

TOKEN_SERVER_PORT = 3333
_token_server_process = None
_watchdog_thread = None
_watchdog_stop = threading.Event()
_watchdog_platform_config = {}


def _get_base_dir():
    """
    Retorna diretório base (funciona compilado Nuitka ou dev).

    Nuitka --onefile extrai para pasta TEMP, mas o exe real fica na pasta do usuário.
    Precisamos da pasta do exe real (onde estão token_server.exe, platforms.json, etc).
    """
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    markers = ("token_server.exe", "platforms.json", "INICIAR.bat")

    for marker in markers:
        if os.path.exists(os.path.join(exe_dir, marker)):
            return exe_dir

    if os.path.exists(os.path.join(exe_dir, "token_server", "token_server.js")):
        return exe_dir

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_all_base_dirs():
    """Retorna lista de diretórios candidatos para buscar arquivos."""
    dirs = []
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    dirs.append(exe_dir)

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if script_dir != exe_dir:
        dirs.append(script_dir)

    cwd = os.getcwd()
    if cwd not in dirs:
        dirs.append(cwd)

    return dirs


def _find_chromium():
    """Encontra o Chromium bundled para o Puppeteer."""
    chrome_subpaths = [
        os.path.join("chromium", "chrome-win64", "chrome.exe"),
        os.path.join("chromium", "chrome-win", "chrome.exe"),
    ]
    for base in _get_all_base_dirs():
        for subpath in chrome_subpaths:
            full = os.path.join(base, subpath)
            if os.path.exists(full):
                return full
    return None


def find_node():
    """Encontra o executável do Node.js."""
    for base in _get_all_base_dirs():
        local_node = os.path.join(base, "token_server", "node.exe")
        if os.path.exists(local_node):
            return local_node

        local_node2 = os.path.join(base, "node.exe")
        if os.path.exists(local_node2):
            return local_node2

    import shutil

    return shutil.which("node")


def _find_token_server_exe():
    """Encontra token_server.exe compilado (modo distribuição)."""
    candidates = []
    for base in _get_all_base_dirs():
        candidates.append(os.path.join(base, "token_server.exe"))
        candidates.append(os.path.join(base, "token_server", "token_server.exe"))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def _wait_for_token_server(timeout_secs=30):
    """Aguarda Token Server ficar pronto."""
    for _ in range(timeout_secs * 2):
        time.sleep(0.5)

        if _token_server_process and _token_server_process.poll() is not None:
            print(f"\n{Fore.RED}[!] Token Server falhou ao iniciar.{Style.RESET_ALL}")
            return False

        try:
            resp = urllib.request.urlopen(
                f"http://localhost:{TOKEN_SERVER_PORT}/health", timeout=2
            )
            if resp.status == 200:
                print(f" {Fore.GREEN}OK!{Style.RESET_ALL}")
                return True
        except Exception:
            pass

        print(".", end="", flush=True)

    print(f"\n{Fore.YELLOW}timeout{Style.RESET_ALL}")
    return False


def start_token_server():
    """Inicia o Token Server (VM Workers) em background."""
    global _token_server_process

    base = _get_base_dir()

    try:
        resp = urllib.request.urlopen(
            f"http://localhost:{TOKEN_SERVER_PORT}/health", timeout=3
        )
        if resp.status == 200:
            if _token_server_process and _token_server_process.poll() is None:
                print(f"{Fore.GREEN}[OK] Token Server ja ativo (nosso processo).{Style.RESET_ALL}")
                return True

            print(
                f"{Fore.YELLOW}[!] Token Server orfao detectado na porta "
                f"{TOKEN_SERVER_PORT}. Matando...{Style.RESET_ALL}"
            )
            _kill_stale_port_processes(TOKEN_SERVER_PORT)
    except Exception:
        pass

    _kill_stale_port_processes(TOKEN_SERVER_PORT)

    for _retry in range(3):
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            _sock.bind(("127.0.0.1", TOKEN_SERVER_PORT))
            _sock.close()
            break
        except OSError:
            _sock.close()
            if _retry < 2:
                time.sleep(2)
                _kill_stale_port_processes(TOKEN_SERVER_PORT)
            else:
                print(
                    f"{Fore.RED}[!] Porta {TOKEN_SERVER_PORT} ainda ocupada após 3 tentativas."
                    f"{Style.RESET_ALL}"
                )
                return False

    proxy_url_for_server = None
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r", encoding="utf-8") as file:
            proxy_line = file.read().strip().split("\n")[0].strip()
        if proxy_line and not proxy_line.startswith("#"):
            proxy_url_for_server = f"http://{proxy_line}"
            print(f"{Fore.GREEN}[+] Proxy será usado no Token Server{Style.RESET_ALL}")

    ts_exe = _find_token_server_exe()
    if ts_exe:
        print(f"{Fore.CYAN}[+] Iniciando Token Server (compilado)...{Style.RESET_ALL}", end="", flush=True)
        env = os.environ.copy()
        env["PORT"] = str(TOKEN_SERVER_PORT)
        env["POOL_SIZE"] = "150"
        env["JOBS_PER_W"] = "20"
        env["GEE_APPID"] = "9ia4hndgblg9xihxcwgdjt9ztg8sjwaf"
        env["GEE_DOMAIN"] = "d11dm6tasib5wm.cloudfront.net"
        if proxy_url_for_server:
            env["HTTP_PROXY"] = proxy_url_for_server
            env["HTTPS_PROXY"] = proxy_url_for_server

        log_path = os.path.join(base, "server.log")
        log_file = open(log_path, "w", encoding="utf-8")
        _token_server_process = subprocess.Popen(
            [ts_exe],
            cwd=base,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )
        return _wait_for_token_server()

    node_exe = find_node()
    if not node_exe:
        print(f"{Fore.YELLOW}[!] Node.js nao encontrado. Tokens legado.{Style.RESET_ALL}")
        return False

    server_dir = None
    server_js = None
    for candidate_base in _get_all_base_dirs():
        candidate = os.path.join(candidate_base, "token_server", "token_server.js")
        if os.path.exists(candidate):
            server_dir = os.path.join(candidate_base, "token_server")
            server_js = candidate
            break

    if not server_js:
        print(f"{Fore.YELLOW}[!] token_server.js nao encontrado.{Style.RESET_ALL}")
        return False

    node_modules = os.path.join(server_dir, "node_modules")
    if not os.path.exists(node_modules):
        print(f"{Fore.CYAN}[+] Instalando dependencias...{Style.RESET_ALL}")
        import shutil

        npm_exe = shutil.which("npm")
        if not npm_exe:
            print(f"{Fore.RED}[!] npm nao encontrado.{Style.RESET_ALL}")
            return False

        result = subprocess.run(
            [npm_exe, "install"],
            cwd=server_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"{Fore.RED}[!] Erro npm: {result.stderr[:100]}{Style.RESET_ALL}")
            return False

    print(f"{Fore.CYAN}[+] Iniciando Token Server (VM Workers)...{Style.RESET_ALL}", end="", flush=True)
    env = os.environ.copy()
    env["PORT"] = str(TOKEN_SERVER_PORT)
    env["POOL_SIZE"] = "150"
    env["JOBS_PER_W"] = "20"
    env["GEE_APPID"] = "9ia4hndgblg9xihxcwgdjt9ztg8sjwaf"
    env["GEE_DOMAIN"] = "d11dm6tasib5wm.cloudfront.net"
    if proxy_url_for_server:
        env["HTTP_PROXY"] = proxy_url_for_server
        env["HTTPS_PROXY"] = proxy_url_for_server

    log_file = open(os.path.join(server_dir, "server.log"), "w", encoding="utf-8")
    _token_server_process = subprocess.Popen(
        [node_exe, server_js],
        cwd=server_dir,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
    )
    return _wait_for_token_server()


def stop_token_server():
    """Para o Token Server (force kill no Windows para evitar processos órfãos)."""
    global _token_server_process

    if _token_server_process and _token_server_process.poll() is None:
        pid = _token_server_process.pid
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid), "/T"],
                    capture_output=True,
                    timeout=10,
                )
            else:
                _token_server_process.terminate()
                _token_server_process.wait(timeout=5)
        except Exception:
            try:
                _token_server_process.kill()
            except Exception:
                pass

    _token_server_process = None
    _kill_stale_port_processes(TOKEN_SERVER_PORT)


def _is_token_server_alive() -> bool:
    """Verifica se o Token Server está respondendo."""
    try:
        resp = urllib.request.urlopen(
            f"http://localhost:{TOKEN_SERVER_PORT}/health", timeout=3
        )
        return resp.status == 200
    except Exception:
        return False


def _get_token_server_pool_status() -> dict:
    """Retorna status do pool do Token Server (pool size, etc)."""
    try:
        resp = urllib.request.urlopen(
            f"http://localhost:{TOKEN_SERVER_PORT}/status", timeout=5
        )
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def ensure_token_server():
    """Garante que o Token Server está rodando. Reinicia se necessário."""
    if _is_token_server_alive():
        return True

    if _token_server_process and _token_server_process.poll() is None:
        for attempt in range(3):
            print(
                f"{Fore.YELLOW}[!] Token Server offline. Reiniciando... (tentativa "
                f"{attempt + 1}/3){Style.RESET_ALL}"
            )
            time.sleep(2)
            if start_token_server():
                return True
    else:
        print(f"{Fore.YELLOW}[!] Token Server offline. Reiniciando...{Style.RESET_ALL}")

    return start_token_server()


def _token_server_watchdog():
    """Thread watchdog que monitora o Token Server a cada 60s."""
    consecutive_empty_pool = 0

    while not _watchdog_stop.is_set():
        _watchdog_stop.wait(60)
        if _watchdog_stop.is_set():
            return

        try:
            if _token_server_process and _token_server_process.poll() is not None:
                print(f"{Fore.YELLOW}[WATCHDOG] Token Server processo morreu! Reiniciando...{Style.RESET_ALL}")
                start_token_server()
                _reconfigure_token_server()
                continue

            if not _is_token_server_alive():
                print(f"{Fore.YELLOW}[WATCHDOG] Token Server não responde. Reiniciando...{Style.RESET_ALL}")
                stop_token_server()
                time.sleep(2)
                start_token_server()
                _reconfigure_token_server()
                continue

            status = _get_token_server_pool_status()
            pool_size = int(str(status.get("pool_size", status.get("pool", 0))).split("/")[0])
            tokens_off = int(status.get("total_off", status.get("off", 0)))
            tokens_on = int(status.get("total_on", status.get("on", 0)))

            if pool_size <= 0:
                consecutive_empty_pool += 1
            else:
                consecutive_empty_pool = 0

            if consecutive_empty_pool >= 3:
                print(
                    f"{Fore.YELLOW}[WATCHDOG] Token Server pool vazio por "
                    f"{consecutive_empty_pool} min (on={tokens_on}, off={tokens_off}). "
                    f"Reiniciando...{Style.RESET_ALL}"
                )
                stop_token_server()
                time.sleep(2)
                start_token_server()
                _reconfigure_token_server()
        except Exception:
            pass


def _reconfigure_token_server():
    """Reconfigura o Token Server com a plataforma atual após restart."""
    if _watchdog_platform_config:
        try:
            configure_token_server_for_platform(_watchdog_platform_config)
        except Exception:
            pass


def start_token_server_watchdog(platform_config: dict = None):
    """Inicia o watchdog thread do Token Server."""
    global _watchdog_thread, _watchdog_platform_config

    if platform_config:
        _watchdog_platform_config = platform_config

    if _watchdog_thread and _watchdog_thread.is_alive():
        return

    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(
        target=_token_server_watchdog,
        daemon=True,
        name="TokenWatchdog",
    )
    _watchdog_thread.start()


def stop_token_server_watchdog():
    """Para o watchdog thread."""
    _watchdog_stop.set()
    if _watchdog_thread:
        _watchdog_thread.join(timeout=5)


def configure_token_server_for_platform(platform: dict):
    """Configura o Token Server para o domínio da plataforma."""
    domain = platform.get("domain", "")
    gee_appid = platform.get("gee_appid", "9ia4hndgblg9xihxcwgdjt9ztg8sjwaf")
    is_mobile = platform.get("is_mobile", False)

    server_ok = ensure_token_server()
    if not server_ok:
        print(f"{Fore.YELLOW}[!] Token Server indisponivel. Usando tokens legado.{Style.RESET_ALL}")
        return False

    try:
        from services.captcha import configure_token_server_domain

        configure_token_server_domain(domain, gee_appid, mobile_mode=is_mobile)
        return True
    except Exception:
        return False


def get_token_server_info() -> dict:
    """Retorna info resumida do Token Server."""
    try:
        from services.captcha import get_token_server_status

        return get_token_server_status()
    except Exception:
        return {"error": "offline"}
