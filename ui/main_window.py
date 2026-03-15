import os
os.environ["PYWEBVIEW_GUI"] = "qt"

import sys
import json
import threading
import subprocess
from pathlib import Path
from datetime import datetime

import webview

from core.db import db
from core.automation import contador_execucao
from core.paths import get_whatsapp_profile_dir, get_app_base_dir
from core import windows_scheduler

BASE_DIR    = get_app_base_dir()
PROFILE_DIR = get_whatsapp_profile_dir()


def _get_executor_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "executor.py"
    return Path(BASE_DIR) / "executor.py"


def _get_web_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ui" / "web"
    return Path(__file__).parent / "web"


def _get_icon_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "resources" / "Taty_s-English-Logo.ico")
    return str(Path(get_app_base_dir()) / "resources" / "Taty_s-English-Logo.ico")


# ─────────────────────────────────────────────
#  API exposta ao JS
# ─────────────────────────────────────────────
class Api:
    """
    Cada método público aqui pode ser chamado do JS via:
        window.pywebview.api.nomeDoMetodo(arg)
    """

    def get_execucoes(self):
        return {"count": contador_execucao(False)}

    def listar_agendamentos(self):
        rows = db.listar_todos()
        result = []
        for row in rows:
            t_id, task_name, target, mode, sched_time, status, created_at = row
            try:
                dt_fmt = datetime.fromisoformat(sched_time).strftime("%d/%m/%Y %H:%M")
            except Exception:
                dt_fmt = sched_time
            result.append({
                "id": t_id,
                "task_name": task_name,
                "target": target,
                "mode": mode,
                "scheduled_time": dt_fmt,
                "scheduled_time_iso": sched_time,
                "status": status,
                "created_at": created_at,
            })
        return {"agendamentos": result}

    def obter_agendamento(self, task_id: int):
        data = db.obter_por_id(int(task_id))
        if not data:
            return {"error": "Agendamento nao encontrado"}
        try:
            dt = datetime.fromisoformat(data["scheduled_time"])
            data["date_str"] = dt.strftime("%d/%m/%Y")
            data["time_str"] = dt.strftime("%H:%M")
        except Exception:
            data["date_str"] = ""
            data["time_str"] = ""
        return {"agendamento": data}

    def reenviar_agendamento(self, task_id: int):
        """Reenvia um agendamento com status failed ou completed."""
        try:
            task_id  = int(task_id)
            task_data = db.obter_por_id(task_id)
            if not task_data:
                return {"error": "Agendamento nao encontrado"}

            temp_dir  = Path(BASE_DIR) / "temp_tasks"
            temp_dir.mkdir(exist_ok=True)
            ts        = int(datetime.now().timestamp())
            json_path = temp_dir / f"reenvio_{ts}.json"

            task_json = {
                "task_id":   None,  # não atualiza DB de agendamento
                "target":    task_data["target"],
                "mode":      task_data["mode"],
                "message":   task_data.get("message") or "",
                "file_path": task_data.get("file_path") or None,
            }
            json_path.write_text(
                json.dumps(task_json, ensure_ascii=False, indent=2), encoding="utf-8")

            executor_path = _get_executor_path()
            cmd = ([sys.executable, "--executor-json", str(json_path)]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, str(executor_path), str(json_path)])

            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc  = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=flags, cwd=str(BASE_DIR),
                encoding="utf-8", errors="replace")

            threading.Thread(
                target=self._monitorar_envio,
                args=(proc, json_path),
                daemon=False
            ).start()
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def excluir_agendamento(self, task_id: int):
        try:
            task_id = int(task_id)
            windows_scheduler.delete_windows_task(task_id)
            db.deletar(task_id)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def editar_agendamento(self, dados: dict):
        try:
            t_id      = int(dados["task_id"])
            target    = dados["target"].strip()
            mode      = dados["mode"]
            message   = dados.get("message", "").strip()
            file_path = dados.get("file_path") or None
            time_str  = dados["time_str"].strip()
            is_daily  = dados.get("daily", False)
            incl_wk   = dados.get("include_weekends", True)

            if is_daily:
                nova_dt  = datetime.strptime(
                    f"{datetime.now().strftime('%d/%m/%Y')} {time_str}", "%d/%m/%Y %H:%M")
                date_str = datetime.now().strftime("%d/%m/%Y")
            else:
                date_str = dados["date_str"].strip()
                nova_dt  = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                # só bloqueia data passada se for pendente (completed/failed podem ser reagendados)
                task_atual = db.obter_por_id(t_id)
                if nova_dt < datetime.now() and task_atual and task_atual.get("status") == "pending":
                    return {"error": "Data/hora no passado"}

            task_data = db.obter_por_id(t_id)
            if not task_data:
                return {"error": "Agendamento nao encontrado"}

            windows_scheduler.delete_windows_task(t_id)
            db.atualizar_agendamento_completo(t_id, target, mode, message, file_path, nova_dt)

            json_cfg = {"target": target, "mode": mode,
                        "message": message, "file_path": file_path}
            windows_scheduler.create_task_bat(t_id, task_data["task_name"], json_cfg)
            windows_scheduler.create_windows_task(
                t_id, task_data["task_name"], time_str, date_str,
                daily=is_daily, include_weekends=incl_wk
            )
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def enviar_agora(self, dados: dict):
        try:
            task_data = {
                "task_id":  None,
                "target":   dados["target"].strip(),
                "mode":     dados["mode"],
                "message":  dados.get("message", "").strip(),
                "file_path": dados.get("file_path") or None,
            }
            temp_dir  = Path(BASE_DIR) / "temp_tasks"
            temp_dir.mkdir(exist_ok=True)
            ts        = int(datetime.now().timestamp())
            json_path = temp_dir / f"manual_{ts}.json"
            json_path.write_text(
                json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8")

            executor_path = _get_executor_path()
            cmd = ([sys.executable, "--executor-json", str(json_path)]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, str(executor_path), str(json_path)])

            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc  = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=flags, cwd=str(BASE_DIR),
                encoding="utf-8", errors="replace")

            threading.Thread(target=self._monitorar_envio,
                             args=(proc, json_path), daemon=False).start()
            return {"ok": True, "msg": "Envio iniciado"}
        except Exception as e:
            return {"error": str(e)}

    def _monitorar_envio(self, proc, json_path: Path):
        stdout, stderr = proc.communicate()
        ok = proc.returncode == 0
        status_file = json_path.with_suffix(".status")
        erro_msg = ""
        if not ok:
            erro_msg = (status_file.read_text(encoding="utf-8")
                        if status_file.exists() else stderr or "")
        try:
            window  = webview.windows[0]
            payload = json.dumps({"ok": ok, "error": erro_msg})
            window.evaluate_js(f"window.__onEnvioResult({payload})")
        except Exception:
            pass
        try:
            json_path.unlink(missing_ok=True)
            status_file.unlink(missing_ok=True)
        except Exception:
            pass

    def agendar(self, dados: dict):
        try:
            import re
            target    = dados["target"].strip()
            mode      = dados["mode"]
            message   = dados.get("message", "").strip()
            file_path = dados.get("file_path") or None
            time_str  = dados["time_str"].strip()
            is_daily  = dados.get("daily", False)
            incl_wk   = dados.get("include_weekends", True)

            if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', time_str):
                return {"error": "Hora invalida. Use HH:MM"}

            if is_daily:
                dt       = datetime.strptime(
                    f"{datetime.now().strftime('%d/%m/%Y')} {time_str}", "%d/%m/%Y %H:%M")
                date_str = datetime.now().strftime("%d/%m/%Y")
            else:
                date_str = dados["date_str"].strip()
                dt       = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                if dt < datetime.now():
                    return {"error": "O horario deve ser no futuro"}

            task_name = f"ZapTask_{int(datetime.now().timestamp())}"
            t_id = db.adicionar(task_name=task_name, target=target, mode=mode,
                                message=message, file_path=file_path, scheduled_time=dt)
            if not t_id or t_id == -1:
                return {"error": "Falha ao salvar no banco de dados"}

            json_cfg = {"target": target, "mode": mode,
                        "message": message, "file_path": file_path}
            windows_scheduler.create_task_bat(t_id, task_name, json_cfg)
            suc, msg = windows_scheduler.create_windows_task(
                t_id, task_name, time_str, date_str,
                daily=is_daily, include_weekends=incl_wk)
            if not suc:
                db.deletar(t_id)
                return {"error": f"Falha no Agendador do Windows: {msg}"}
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def enviar_lote(self, dados: dict):
        """
        dados = { itens: [{target, mode, message, filePath}] }
        Dispara envio sequencial em background.
        """
        try:
            itens = dados.get("itens", [])
            if not itens:
                return {"error": "Nenhum item no lote"}

            temp_dir = Path(BASE_DIR) / "temp_tasks"
            temp_dir.mkdir(exist_ok=True)
            ts = int(datetime.now().timestamp())

            # Salva cada item como JSON separado e executa sequencialmente em thread
            threading.Thread(
                target=self._executar_lote_sequencial,
                args=(itens, temp_dir, ts),
                daemon=False
            ).start()
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def _executar_lote_sequencial(self, itens, temp_dir, ts):
        """
        Abre o WhatsApp UMA vez e envia para todos os destinatários
        em sequência, fechando o navegador somente ao final.
        """
        from core.automation import iniciar_driver, enviar_arquivo_com_mensagem
        from core.paths import get_whatsapp_profile_dir
        import time
        import pyperclip

        ok_count = 0
        total    = len(itens)
        erro_msg = ""
        pw = context = page = None

        try:
            profile_dir = get_whatsapp_profile_dir()
            pw, context, page = iniciar_driver(profile_dir, modo_execucao='manual')

            for i, item in enumerate(itens):
                target    = item["target"].strip()
                mode      = item["mode"]
                message   = item.get("message", "").strip()
                file_path = item.get("filePath") or None
                try:
                    # Pesquisa o contato
                    seletores_search = [
                        'input[data-tab="3"]',
                        'input[aria-label="Pesquisar ou comecar uma nova conversa"]',
                        'input[aria-label="Search or start new chat"]',
                        'div[contenteditable="true"][data-tab="3"]',
                    ]
                    search_box = None
                    for sel in seletores_search:
                        try:
                            el = page.locator(sel).first
                            el.wait_for(state='visible', timeout=10000)
                            search_box = el
                            break
                        except Exception:
                            continue

                    if not search_box:
                        raise Exception("Campo de pesquisa nao encontrado")

                    # Limpa pesquisa anterior e digita novo contato
                    search_box.click()
                    time.sleep(0.5)
                    search_box.fill("")
                    time.sleep(0.3)
                    search_box.fill(target)
                    time.sleep(2.5)
                    page.keyboard.press("Enter")
                    time.sleep(3)

                    # Envia
                    if mode == "text":
                        chat_box = page.locator('div[contenteditable="true"][data-tab="10"]')
                        chat_box.wait_for(state="visible", timeout=15000)
                        chat_box.click(force=True)
                        pyperclip.copy(message)
                        page.keyboard.press("Control+V")
                        page.keyboard.press("Enter")
                        time.sleep(4)
                    else:
                        enviar_arquivo_com_mensagem(page, file_path, message)

                    ok_count += 1
                    # incrementa contador uma vez por envio bem-sucedido
                    from core.automation import contador_execucao
                    contador_execucao(incrementar=True)

                except Exception as e:
                    erro_msg = f"Erro em '{target}': {str(e)}"

        except Exception as e:
            erro_msg = str(e)
        finally:
            # Fecha o navegador UMA VEZ ao terminar todos os envios
            try:
                if context:
                    for p in context.pages:
                        try: p.close()
                        except Exception: pass
            except Exception:
                pass
            if pw:
                try: pw.stop()
                except Exception: pass

        try:
            window  = webview.windows[0]
            payload = json.dumps({"ok": ok_count == total, "ok_count": ok_count,
                                  "total": total, "error": erro_msg})
            window.evaluate_js(f"window.__onLoteResult({payload})")
        except Exception:
            pass

    def agendar_lote(self, dados: dict):
        """
        dados = { itens, date_str, time_str, daily, include_weekends }
        Cria um agendamento separado para cada item do lote.
        """
        try:
            import re
            itens     = dados.get("itens", [])
            time_str  = dados["time_str"].strip()
            is_daily  = dados.get("daily", False)
            incl_wk   = dados.get("include_weekends", True)

            if not itens:
                return {"error": "Nenhum item no lote"}
            if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', time_str):
                return {"error": "Hora invalida. Use HH:MM"}

            if is_daily:
                dt       = datetime.strptime(
                    f"{datetime.now().strftime('%d/%m/%Y')} {time_str}", "%d/%m/%Y %H:%M")
                date_str = datetime.now().strftime("%d/%m/%Y")
            else:
                date_str = dados["date_str"].strip()
                dt       = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                if dt < datetime.now():
                    return {"error": "O horario deve ser no futuro"}

            count = 0
            for item in itens:
                target    = item["target"].strip()
                mode      = item["mode"]
                message   = item.get("message", "").strip()
                file_path = item.get("filePath") or None

                task_name = f"ZapTask_{int(datetime.now().timestamp())}_{count}"
                t_id = db.adicionar(task_name=task_name, target=target, mode=mode,
                                    message=message, file_path=file_path, scheduled_time=dt)
                if t_id and t_id != -1:
                    json_cfg = {"target": target, "mode": mode,
                                "message": message, "file_path": file_path}
                    windows_scheduler.create_task_bat(t_id, task_name, json_cfg)
                    windows_scheduler.create_windows_task(
                        t_id, task_name, time_str, date_str,
                        daily=is_daily, include_weekends=incl_wk)
                    count += 1

            return {"ok": True, "count": count}
        except Exception as e:
            return {"error": str(e)}

    def selecionar_arquivo(self):
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Todos os arquivos (*.*)",)
        )
        if result:
            paths = list(result)
            return {"paths": paths, "joined": "\n".join(paths)}
        return {"paths": [], "joined": ""}


# ─────────────────────────────────────────────
#  Entrypoint
# ─────────────────────────────────────────────
class App:
    def __init__(self):
        self.api  = Api()
        self._win = None

    def mainloop(self):
        import time
        web_dir   = _get_web_dir()
        index     = web_dir / "index.html"
        icon_path = _get_icon_path()

        self._win = webview.create_window(
            title     = "Study Practices — WhatsApp Automation",
            url       = str(index) + f"?nocache={int(time.time())}",
            js_api    = self.api,
            width     = 510,
            height    = 790,
            min_size  = (420, 600),
            resizable = True,
        )
        webview.start(debug=False, icon=icon_path)