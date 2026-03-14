"""
main_window.py — PyWebView bridge substituindo CustomTkinter.

Expõe uma API Python para o frontend HTML/JS chamar via
window.pywebview.api.<método>(dados)
"""

import os
import sys
import json
import threading
import subprocess
import traceback
from pathlib import Path
from datetime import datetime, timedelta

import webview

from core.db import db
from core.automation import contador_execucao
from core.paths import get_whatsapp_profile_dir, get_app_base_dir
from core import windows_scheduler

BASE_DIR   = get_app_base_dir()
PROFILE_DIR = get_whatsapp_profile_dir()


def _get_executor_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "executor.py"
    return Path(BASE_DIR) / "executor.py"


def _get_web_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ui" / "web"
    return Path(__file__).parent / "web"


# ─────────────────────────────────────────────
#  API exposta ao JS
# ─────────────────────────────────────────────
class Api:
    """
    Cada método público aqui pode ser chamado do JS via:
        window.pywebview.api.nomeDoMetodo(arg)
    Todos retornam dicts serializáveis (o PyWebView converte para JS objects).
    """

    # ── contadores / tema ──────────────────────────────────────────────

    def get_execucoes(self):
        return {"count": contador_execucao(False)}

    # ── agendamentos ───────────────────────────────────────────────────

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
            return {"error": "Agendamento não encontrado"}
        try:
            dt = datetime.fromisoformat(data["scheduled_time"])
            data["date_str"] = dt.strftime("%d/%m/%Y")
            data["time_str"] = dt.strftime("%H:%M")
        except Exception:
            data["date_str"] = ""
            data["time_str"] = ""
        return {"agendamento": data}

    def excluir_agendamento(self, task_id: int):
        try:
            task_id = int(task_id)
            windows_scheduler.delete_windows_task(task_id)
            db.deletar(task_id)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def editar_agendamento(self, dados: dict):
        """
        dados = {
          task_id, target, mode, message, file_path,
          date_str, time_str, daily, include_weekends
        }
        """
        try:
            t_id        = int(dados["task_id"])
            target      = dados["target"].strip()
            mode        = dados["mode"]
            message     = dados.get("message", "").strip()
            file_path   = dados.get("file_path") or None
            time_str    = dados["time_str"].strip()
            is_daily    = dados.get("daily", False)
            incl_wk     = dados.get("include_weekends", True)

            if is_daily:
                nova_dt = datetime.strptime(
                    f"{datetime.now().strftime('%d/%m/%Y')} {time_str}",
                    "%d/%m/%Y %H:%M"
                )
                date_str = datetime.now().strftime("%d/%m/%Y")
            else:
                date_str = dados["date_str"].strip()
                nova_dt  = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                if nova_dt < datetime.now():
                    return {"error": "Data/hora no passado"}

            task_data = db.obter_por_id(t_id)
            if not task_data:
                return {"error": "Agendamento não encontrado"}

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

    # ── envio imediato ─────────────────────────────────────────────────

    def enviar_agora(self, dados: dict):
        """
        dados = { target, mode, message, file_path }
        Dispara o executor em background e retorna imediatamente.
        O frontend deve ouvir o evento 'envio_resultado'.
        """
        try:
            task_data = {
                "task_id": None,
                "target":    dados["target"].strip(),
                "mode":      dados["mode"],
                "message":   dados.get("message", "").strip(),
                "file_path": dados.get("file_path") or None,
            }
            temp_dir = Path(BASE_DIR) / "temp_tasks"
            temp_dir.mkdir(exist_ok=True)
            ts = int(datetime.now().timestamp())
            json_path = temp_dir / f"manual_{ts}.json"
            json_path.write_text(
                json.dumps(task_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            executor_path = _get_executor_path()
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--executor-json", str(json_path)]
            else:
                cmd = [sys.executable, str(executor_path), str(json_path)]

            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc  = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=flags, cwd=str(BASE_DIR),
                encoding="utf-8", errors="replace"
            )
            threading.Thread(
                target=self._monitorar_envio,
                args=(proc, json_path),
                daemon=False
            ).start()
            return {"ok": True, "msg": "Envio iniciado"}
        except Exception as e:
            return {"error": str(e)}

    def _monitorar_envio(self, proc, json_path: Path):
        stdout, stderr = proc.communicate()
        ok     = proc.returncode == 0
        status_file = json_path.with_suffix(".status")
        erro_msg = ""
        if not ok:
            if status_file.exists():
                erro_msg = status_file.read_text(encoding="utf-8")
            elif stderr:
                erro_msg = stderr
        # dispara evento para o JS
        try:
            window = webview.windows[0]
            payload = json.dumps({"ok": ok, "error": erro_msg})
            window.evaluate_js(f"window.__onEnvioResult({payload})")
        except Exception:
            pass
        # limpeza
        try:
            json_path.unlink(missing_ok=True)
            status_file.unlink(missing_ok=True)
        except Exception:
            pass

    # ── agendar ───────────────────────────────────────────────────────

    def agendar(self, dados: dict):
        """
        dados = { target, mode, message, file_path,
                  date_str, time_str, daily, include_weekends }
        """
        try:
            target    = dados["target"].strip()
            mode      = dados["mode"]
            message   = dados.get("message", "").strip()
            file_path = dados.get("file_path") or None
            time_str  = dados["time_str"].strip()
            is_daily  = dados.get("daily", False)
            incl_wk   = dados.get("include_weekends", True)

            import re
            if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', time_str):
                return {"error": "Hora inválida. Use HH:MM"}

            if is_daily:
                dt = datetime.strptime(
                    f"{datetime.now().strftime('%d/%m/%Y')} {time_str}",
                    "%d/%m/%Y %H:%M"
                )
                date_str = datetime.now().strftime("%d/%m/%Y")
            else:
                date_str = dados["date_str"].strip()
                dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                if dt < datetime.now():
                    return {"error": "O horário deve ser no futuro"}

            task_name = f"ZapTask_{int(datetime.now().timestamp())}"
            t_id = db.adicionar(
                task_name=task_name, target=target, mode=mode,
                message=message, file_path=file_path, scheduled_time=dt
            )
            if not t_id or t_id == -1:
                return {"error": "Falha ao salvar no banco de dados"}

            json_cfg = {"target": target, "mode": mode,
                        "message": message, "file_path": file_path}
            windows_scheduler.create_task_bat(t_id, task_name, json_cfg)
            suc, msg = windows_scheduler.create_windows_task(
                t_id, task_name, time_str, date_str,
                daily=is_daily, include_weekends=incl_wk
            )
            if not suc:
                db.deletar(t_id)
                return {"error": f"Falha no Agendador do Windows: {msg}"}

            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    # ── seleção de arquivo (diálogo nativo) ───────────────────────────

    def selecionar_arquivo(self):
        """Abre diálogo nativo e retorna lista de caminhos."""
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
        self.api    = Api()
        self._win   = None

    def mainloop(self):
        web_dir  = _get_web_dir()
        index    = web_dir / "index.html"
        api_obj  = self.api

        import time

        self._win = webview.create_window(
            title     = "Study Practices — WhatsApp Automation",
            url       = str(index) + f"?nocache={int(time.time())}",
            js_api    = api_obj,
            width     = 520,
            height    = 820,
            min_size  = (420, 600),
            resizable = True,
        )
        webview.start(debug=True)