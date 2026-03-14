'''import multiprocessing
import sys
import os
import io
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import subprocess
#from playwright.sync_api import sync_playwright

# ===== PROTEÇÃO CRÍTICA: BLOQUEIA GUI EM MODO EXECUTOR =====
if os.environ.get("EXECUTOR_MODE") == "1":
    print("[BLOQUEIO] Tentativa de abrir GUI em modo executor - BLOQUEADO")
    sys.exit(1)

def assegurar_navegador():
    """Verifica se o Chromium está instalado, se não, exibe aviso e instala."""
    if "--parent-process" in sys.argv or "install" in sys.argv:
        return
    
    # Checa só o arquivo, sem lançar navegador
    caminhos_chromium = [
        r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    ]
    navegador_existe = any(os.path.exists(c) for c in caminhos_chromium)

    if not navegador_existe:
        # Criar uma janela de aviso temporária
        root = tk.Tk()
        root.title("Study Practices - Configuração")
        root.geometry("400x150")
        # Centralizar a janela
        root.eval('tk::PlaceWindow . center')
        
        label = tk.Label(root, text="Preparando navegador pela primeira vez...\nIsso pode levar um minuto, por favor aguarde.", 
                         padx=20, pady=20, font=("Helvetica", 10))
        label.pack()
        
        root.update() # Força a exibição da janela
        
        try:
            # Comando para instalar apenas o chromium
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True)
        finally:
            root.destroy() # Fecha o aviso após terminar

# --- 1. BLOQUEIO OBRIGATÓRIO ---
if __name__ == "__main__":
    multiprocessing.freeze_support()

    if len(sys.argv) > 1 and sys.argv[1] == "-m":
        sys.exit(0)

    # --- 2. STDOUT SEGURO (APENAS CONSOLE) ---
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        except Exception:
            pass

    # --- 3. IMPORTS BÁSICOS ---
    import json
    import argparse
    from core.paths import get_app_base_dir, get_whatsapp_profile_dir

    BASE_DIR = get_app_base_dir()
    os.chdir(BASE_DIR)

    PROFILE_DIR = get_whatsapp_profile_dir()

    # Log de depuração (ajuda a ver se o agendador abriu no lugar certo)
    with open(os.path.join(BASE_DIR, "last_run_path.txt"), "a") as f:
        f.write(f"{datetime.now()}: Rodando em {BASE_DIR} | Perfil: {PROFILE_DIR}\n")

    # --- 4. ARGUMENTOS ---
    parser = argparse.ArgumentParser(description="WhatsApp Automation App")
    parser.add_argument("--auto", help="Arquivo JSON de automação")
    parser.add_argument("--executor-json", help="Executa automação isolada via executor.py")
    parser.add_argument("--task_id", type=int, help="ID da tarefa")
    args, _ = parser.parse_known_args()

    # --- 5. MODO EXECUTOR (USADO NO EXECUTÁVEL) ---
    if args.executor_json:
        from executor import main as executor_main
        executor_main(args.executor_json)
        sys.exit(0)

    # --- 6. MODO AUTOMÁTICO (NÃO DEVE MAIS SER USADO - MIGRADO PARA EXECUTOR.PY) ---
    if args.auto:
        print("[AVISO] Modo --auto foi migrado para executor.py")
        print("[AVISO] Use: python executor.py <json_path>")
        sys.exit(1)

    # --- 7. MODO GUI ---
    else:
        try:
            assegurar_navegador()
            from ui.main_window import App
            app = App()
            app.mainloop()
        except Exception as e:
            # Isso cria um arquivo de erro se o app fechar sozinho
            with open(os.path.join(BASE_DIR, "erro_fatal.txt"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] Erro ao abrir GUI: {str(e)}\n")
            raise e'''

import multiprocessing
import sys
import os
import io
from datetime import datetime

# ── BLOQUEIO: GUI não abre em modo executor ──────────────────────────
if os.environ.get("EXECUTOR_MODE") == "1":
    print("[BLOQUEIO] Tentativa de abrir GUI em modo executor — BLOQUEADO")
    sys.exit(1)

if __name__ == "__main__":
    multiprocessing.freeze_support()

    if len(sys.argv) > 1 and sys.argv[1] == "-m":
        sys.exit(0)

    # stdout UTF-8
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        except Exception:
            pass

    import json
    import argparse
    from core.paths import get_app_base_dir, get_whatsapp_profile_dir

    BASE_DIR    = get_app_base_dir()
    PROFILE_DIR = get_whatsapp_profile_dir()
    os.chdir(BASE_DIR)

    with open(os.path.join(BASE_DIR, "last_run_path.txt"), "a") as f:
        f.write(f"{datetime.now()}: Rodando em {BASE_DIR} | Perfil: {PROFILE_DIR}\n")

    parser = argparse.ArgumentParser()
    parser.add_argument("--executor-json", help="Executa automação isolada")
    parser.add_argument("--auto",     help="[legado] arquivo JSON de automação")
    parser.add_argument("--task_id",  type=int)
    args, _ = parser.parse_known_args()

    # modo executor (agendador / CLI)
    if args.executor_json:
        from executor import main as executor_main
        executor_main(args.executor_json)
        sys.exit(0)

    if args.auto:
        print("[AVISO] Modo --auto foi migrado para executor.py")
        sys.exit(1)

    # modo GUI (PyWebView)
    try:
        from ui.main_window import App
        app = App()
        app.mainloop()
    except Exception as e:
        import traceback
        with open(os.path.join(BASE_DIR, "erro_fatal.txt"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] {traceback.format_exc()}\n")
        raise