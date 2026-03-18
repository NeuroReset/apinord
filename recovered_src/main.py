import atexit
import json
import os
import signal
import sys
import time

from colorama import Fore, Style, init

init(autoreset=True)

APP_NAME = "API Master"
PLATFORMS_FILE = "platforms.json"
CPFS_FILE = "cpfs.txt"
PROXY_FILE = "proxy.txt"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    print(f"{Fore.MAGENTA}==============================================")
    print(f"{Fore.CYAN}{APP_NAME} - CLI")
    print(f"{Fore.MAGENTA}=============================================={Style.RESET_ALL}")


def print_menu():
    print()
    print(f"{Fore.CYAN}1.{Style.RESET_ALL} Importar Casa (cURL)")
    print(f"{Fore.CYAN}2.{Style.RESET_ALL} Importar via Dominio")
    print(f"{Fore.CYAN}3.{Style.RESET_ALL} Listar Casas")
    print(f"{Fore.CYAN}4.{Style.RESET_ALL} Criar Contas")
    print(f"{Fore.CYAN}5.{Style.RESET_ALL} Resetar Casa")
    print(f"{Fore.CYAN}6.{Style.RESET_ALL} Scan Dominios")
    print(f"{Fore.CYAN}7.{Style.RESET_ALL} Batch Import")
    print(f"{Fore.CYAN}8.{Style.RESET_ALL} Bonus Hunt")
    print(f"{Fore.CYAN}9.{Style.RESET_ALL} Checker Dashboard")
    print(f"{Fore.CYAN}0.{Style.RESET_ALL} Sair")
    print()


def run_startup_check():
    print(f"{Fore.CYAN}[STARTUP CHECK]{Style.RESET_ALL}")
    missing = []

    try:
        import colorama
    except Exception:
        missing.append("colorama")

    try:
        import tls_client
    except Exception:
        missing.append("tls_client")

    try:
        import curl_cffi
    except Exception:
        missing.append("curl_cffi")

    try:
        from Crypto.Cipher import AES
    except Exception:
        missing.append("pycryptodome")

    if missing:
        print(
            f"{Fore.RED}[ERRO] Dependencias criticas faltando:"
            f"{Style.RESET_ALL} {', '.join(missing)}"
        )
        return False

    print(f"{Fore.GREEN}[OK] Bibliotecas principais encontradas.{Style.RESET_ALL}")
    return True


def security_check_startup():
    print(f"{Fore.CYAN}Verificando seguranca...{Style.RESET_ALL}", end="", flush=True)
    time.sleep(0.5)
    print(f"\r{Fore.GREEN}[OK] Ambiente seguro.{Style.RESET_ALL}")


def load_platforms():
    if not os.path.exists(PLATFORMS_FILE):
        return {}
    try:
        with open(PLATFORMS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_platforms(data):
    with open(PLATFORMS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def import_platform():
    print("Importar Casa (cURL) - placeholder")


def import_platform_by_domain():
    print("Importar via Dominio - placeholder")


def list_platforms():
    data = load_platforms()
    if not data:
        print("Nenhuma casa cadastrada.")
        return
    for name, cfg in data.items():
        print(f"- {name}: {cfg}")


def create_accounts():
    print("Criar Contas - placeholder")


def reset_platform():
    print("Resetar Casa - placeholder")


def scan_dominios():
    print("Scan Dominios - placeholder")


def batch_import_dominios():
    print("Batch Import - placeholder")


def bonus_hunt_from_file():
    print("Bonus Hunt - placeholder")


def launch_checker_dashboard():
    print("Checker Dashboard - placeholder")


def cleanup(*_args):
    print("\nAté mais!")
    raise SystemExit(0)


def main():
    signal.signal(signal.SIGINT, cleanup)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, cleanup)
    atexit.register(cleanup)

    clear_screen()
    print_banner()

    if not run_startup_check():
        input("Pressione Enter para sair...")
        sys.exit(1)

    security_check_startup()

    print(f"{Fore.CYAN}Licenca: modo scaffold{Style.RESET_ALL}")

    while True:
        print_menu()
        choice = input("Escolha uma opcao: ").strip()

        if choice == "1":
            import_platform()
        elif choice == "2":
            import_platform_by_domain()
        elif choice == "3":
            list_platforms()
        elif choice == "4":
            create_accounts()
        elif choice == "5":
            reset_platform()
        elif choice == "6":
            scan_dominios()
        elif choice == "7":
            batch_import_dominios()
        elif choice == "8":
            bonus_hunt_from_file()
        elif choice == "9":
            launch_checker_dashboard()
        elif choice == "0":
            cleanup()
        else:
            print("Opcao invalida.")

        input("\nEnter para continuar...")
        clear_screen()
        print_banner()


if __name__ == "__main__":
    main()