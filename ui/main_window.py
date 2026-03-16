import os
os.environ["PYWEBVIEW_GUI"] = "qt"

import sys
import json
import threading
import subprocess
import time as time_module
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


def _ensure_batch_column():
    """Adiciona coluna batch_id ao banco se não existir."""
    import sqlite3
    from core.paths import get_user_data_dir
    db_path = Path(get_user_data_dir()) / "scheduler.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("ALTER TABLE agendamentos ADD COLUMN batch_id TEXT")
        conn.commit()
    except Exception:
        pass  # coluna já existe
    finally:
        conn.close()


# garante a coluna batch_id ao importar
_ensure_batch_column()

# migração automática do banco CTK
try:
    import importlib.util as _ilu
    # tenta migrate_db.py e migrat_db.py (nome alternativo no projeto)
    for _mig_name in ["migrate_db.py", "migrat_db.py"]:
        _mig_path = Path(BASE_DIR) / _mig_name
        if _mig_path.exists():
            _spec = _ilu.spec_from_file_location("migrate_db", str(_mig_path))
            _mig  = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mig)
            _result = _mig.migrate(Path(BASE_DIR))
            if _result.get("migrated", 0) > 0:
                print(f"[MIGRAÇÃO] {_result['migrated']} agendamentos importados do app anterior.")
            break
except Exception as _e:
    print(f"[MIGRAÇÃO] Ignorada: {_e}")


class Api:

    # ── contadores ────────────────────────────────────────────────────────
    def get_execucoes(self):
        return {"count": contador_execucao(False)}

    # ── agendamentos ──────────────────────────────────────────────────────
    def listar_agendamentos(self):
        """Retorna agendamentos, agrupando lotes pelo batch_id."""
        import sqlite3
        from core.paths import get_user_data_dir
        db_path = Path(get_user_data_dir()) / "scheduler.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, task_name, target, mode, scheduled_time,
                   status, created_at, batch_id, message, file_path
            FROM agendamentos
            ORDER BY scheduled_time DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        # agrupa lotes
        singles = []
        batches = {}
        for row in rows:
            bid = row.get("batch_id")
            try:
                dt_fmt = datetime.fromisoformat(row["scheduled_time"]).strftime("%d/%m/%Y %H:%M")
            except Exception:
                dt_fmt = row["scheduled_time"]
            row["scheduled_time_fmt"] = dt_fmt

            if bid:
                if bid not in batches:
                    batches[bid] = {"batch_id": bid, "itens": [],
                                    "scheduled_time": dt_fmt, "status": row["status"]}
                batches[bid]["itens"].append(row)
                # status do lote = pior status dos itens
                prio = ["running","failed","pending","cancelled","completed"]
                if prio.index(row["status"]) < prio.index(batches[bid]["status"]):
                    batches[bid]["status"] = row["status"]
                    batches[bid]["scheduled_time"] = dt_fmt
            else:
                singles.append(row)

        result = []
        for row in singles:
            result.append({
                "id": row["id"], "task_name": row["task_name"],
                "target": row["target"], "mode": row["mode"],
                "scheduled_time": row["scheduled_time_fmt"],
                "status": row["status"], "batch_id": None,
            })
        for bid, b in batches.items():
            targets = ", ".join(i["target"] for i in b["itens"][:3])
            if len(b["itens"]) > 3:
                targets += f" +{len(b['itens'])-3}"
            result.append({
                "id": None, "batch_id": bid,
                "target": f"Lote: {targets}",
                "mode": "lote", "is_lote": True,
                "count": len(b["itens"]),
                "itens": b["itens"],
                "scheduled_time": b["scheduled_time"],
                "status": b["status"],
            })

        # reordena por data desc
        result.sort(key=lambda x: x["scheduled_time"], reverse=True)
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
            data["date_str"] = data["time_str"] = ""
        return {"agendamento": data}

    def obter_lote(self, batch_id: str):
        """Retorna todos os itens de um lote para edição."""
        import sqlite3
        from core.paths import get_user_data_dir
        db_path = Path(get_user_data_dir()) / "scheduler.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM agendamentos WHERE batch_id=? ORDER BY id", (batch_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        if not rows:
            return {"error": "Lote nao encontrado"}
        try:
            dt = datetime.fromisoformat(rows[0]["scheduled_time"])
            date_str = dt.strftime("%d/%m/%Y")
            time_str = dt.strftime("%H:%M")
        except Exception:
            date_str = time_str = ""
        return {"itens": rows, "date_str": date_str, "time_str": time_str}

    def excluir_agendamento(self, task_id: int):
        try:
            task_id = int(task_id)
            windows_scheduler.delete_windows_task(task_id)
            db.deletar(task_id)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def excluir_lote(self, batch_id: str):
        """Exclui todos os agendamentos de um lote."""
        import sqlite3
        from core.paths import get_user_data_dir
        db_path = Path(get_user_data_dir()) / "scheduler.db"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT id FROM agendamentos WHERE batch_id=?", (batch_id,))
        ids = [r[0] for r in cur.fetchall()]
        conn.close()
        for tid in ids:
            windows_scheduler.delete_windows_task(tid)
            db.deletar(tid)
        return {"ok": True, "count": len(ids)}

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
                task_atual = db.obter_por_id(t_id)
                if nova_dt < datetime.now() and task_atual and task_atual.get("status") == "pending":
                    return {"error": "Data/hora no passado"}

            task_data = db.obter_por_id(t_id)
            if not task_data:
                return {"error": "Agendamento nao encontrado"}

            windows_scheduler.delete_windows_task(t_id)
            db.atualizar_agendamento_completo(t_id, target, mode, message, file_path, nova_dt)
            json_cfg = {"target": target, "mode": mode, "message": message, "file_path": file_path}
            windows_scheduler.create_task_bat(t_id, task_data["task_name"], json_cfg)
            windows_scheduler.create_windows_task(
                t_id, task_data["task_name"], time_str, date_str,
                daily=is_daily, include_weekends=incl_wk)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def editar_lote(self, dados: dict):
        """
        Edita todos os itens de um lote de uma vez.
        dados = { batch_id, itens:[{id,target,mode,message,file_path}],
                  date_str, time_str, daily, include_weekends }
        """
        try:
            import re
            batch_id = dados["batch_id"]
            itens    = dados["itens"]
            time_str = dados["time_str"].strip()
            is_daily = dados.get("daily", False)
            incl_wk  = dados.get("include_weekends", True)

            if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', time_str):
                return {"error": "Hora invalida. Use HH:MM"}

            if is_daily:
                nova_dt  = datetime.strptime(
                    f"{datetime.now().strftime('%d/%m/%Y')} {time_str}", "%d/%m/%Y %H:%M")
                date_str = datetime.now().strftime("%d/%m/%Y")
            else:
                date_str = dados["date_str"].strip()
                nova_dt  = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
                if nova_dt < datetime.now():
                    return {"error": "Data/hora no passado"}

            for item in itens:
                t_id      = int(item["id"])
                target    = item["target"].strip()
                mode      = item["mode"]
                message   = item.get("message", "").strip()
                file_path = item.get("file_path") or None
                task_data = db.obter_por_id(t_id)
                if not task_data:
                    continue
                windows_scheduler.delete_windows_task(t_id)
                db.atualizar_agendamento_completo(t_id, target, mode, message, file_path, nova_dt)
                json_cfg = {"target": target, "mode": mode, "message": message, "file_path": file_path}
                windows_scheduler.create_task_bat(t_id, task_data["task_name"], json_cfg)
                windows_scheduler.create_windows_task(
                    t_id, task_data["task_name"], time_str, date_str,
                    daily=is_daily, include_weekends=incl_wk)

            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def reenviar_agendamento(self, task_id: int):
        try:
            task_id   = int(task_id)
            task_data = db.obter_por_id(task_id)
            if not task_data:
                return {"error": "Agendamento nao encontrado"}
            temp_dir  = Path(BASE_DIR) / "temp_tasks"
            temp_dir.mkdir(exist_ok=True)
            ts        = int(datetime.now().timestamp())
            json_path = temp_dir / f"reenvio_{ts}.json"
            task_json = {
                "task_id":   None,
                "target":    task_data["target"],
                "mode":      task_data["mode"],
                "message":   task_data.get("message") or "",
                "file_path": task_data.get("file_path") or None,
            }
            json_path.write_text(json.dumps(task_json, ensure_ascii=False, indent=2), encoding="utf-8")
            executor_path = _get_executor_path()
            cmd = ([sys.executable, "--executor-json", str(json_path)]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, str(executor_path), str(json_path)])
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc  = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=flags, cwd=str(BASE_DIR),
                                     encoding="utf-8", errors="replace")
            threading.Thread(target=self._monitorar_envio, args=(proc, json_path), daemon=False).start()
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    # ── envio imediato ────────────────────────────────────────────────────
    def enviar_agora(self, dados: dict):
        try:
            task_data = {
                "task_id":   None,
                "target":    dados["target"].strip(),
                "mode":      dados["mode"],
                "message":   dados.get("message", "").strip(),
                "file_path": dados.get("file_path") or None,
            }
            temp_dir  = Path(BASE_DIR) / "temp_tasks"
            temp_dir.mkdir(exist_ok=True)
            ts        = int(datetime.now().timestamp())
            json_path = temp_dir / f"manual_{ts}.json"
            json_path.write_text(json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8")
            executor_path = _get_executor_path()
            cmd = ([sys.executable, "--executor-json", str(json_path)]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, str(executor_path), str(json_path)])
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc  = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=flags, cwd=str(BASE_DIR),
                                     encoding="utf-8", errors="replace")
            threading.Thread(target=self._monitorar_envio, args=(proc, json_path), daemon=False).start()
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

    # ── lote — envio imediato ─────────────────────────────────────────────
    def enviar_lote(self, dados: dict):
        try:
            itens = dados.get("itens", [])
            if not itens:
                return {"error": "Nenhum item no lote"}
            temp_dir = Path(BASE_DIR) / "temp_tasks"
            temp_dir.mkdir(exist_ok=True)
            ts = int(datetime.now().timestamp())
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
        Abre o WhatsApp UMA vez, envia para todos, fecha só no final.
        Velocidade: sleeps reduzidos ao mínimo necessário.
        """
        import pyperclip
        from core.automation import iniciar_driver, enviar_arquivo_com_mensagem
        from core.paths import get_whatsapp_profile_dir

        ok_count = 0
        total    = len(itens)
        erro_msg = ""
        pw = context = page = None

        SELETORES_SEARCH = [
            'input[data-tab="3"]',
            'input[aria-label="Pesquisar ou comecar uma nova conversa"]',
            'input[aria-label="Search or start new chat"]',
            'div[contenteditable="true"][data-tab="3"]',
        ]

        try:
            profile_dir = get_whatsapp_profile_dir()
            pw, context, page = iniciar_driver(profile_dir, modo_execucao='manual')

            for i, item in enumerate(itens):
                target    = item["target"].strip()
                mode      = item["mode"]
                message   = item.get("message", "").strip()
                file_path = item.get("filePath") or None

                try:
                    # ── após o primeiro envio, pressiona Escape para fechar
                    #    o chat e voltar à lista antes de pesquisar o próximo
                    if i > 0:
                        page.keyboard.press("Escape")
                        time_module.sleep(0.5)

                    # ── localiza search box ──────────────────────────────
                    search_box = None
                    for sel in SELETORES_SEARCH:
                        try:
                            el = page.locator(sel).first
                            el.wait_for(state='visible', timeout=8000)
                            search_box = el
                            break
                        except Exception:
                            continue

                    if not search_box:
                        raise Exception(f"Campo de pesquisa nao encontrado para '{target}'")

                    # ── limpa pesquisa anterior e digita novo contato ────
                    search_box.click()
                    time_module.sleep(0.3)
                    search_box.fill("")          # limpa via fill
                    time_module.sleep(0.2)
                    search_box.type(target)      # digita letra a letra (mais confiável)
                    time_module.sleep(1.5)
                    page.keyboard.press("Enter")
                    time_module.sleep(2.0)

                    # ── envia ───────────────────────────────────────────
                    if mode == "text":
                        chat_box = page.locator('div[contenteditable="true"][data-tab="10"]')
                        chat_box.wait_for(state="visible", timeout=12000)
                        chat_box.click(force=True)
                        pyperclip.copy(message)
                        page.keyboard.press("Control+V")
                        time_module.sleep(0.5)
                        page.keyboard.press("Enter")
                        time_module.sleep(2.5)
                    else:
                        enviar_arquivo_com_mensagem(page, file_path, message)

                    ok_count += 1
                    contador_execucao(incrementar=True)

                    # notifica o JS do progresso parcial
                    try:
                        win     = webview.windows[0]
                        partial = json.dumps({"partial": True, "ok_count": ok_count, "total": total, "target": target})
                        win.evaluate_js(f"window.__onLoteProgress && window.__onLoteProgress({partial})")
                    except Exception:
                        pass

                except Exception as e:
                    erro_msg = f"Erro em '{target}': {str(e)}"
                    # continua para o próximo mesmo em caso de erro

        except Exception as e:
            erro_msg = str(e)
        finally:
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

    # ── lote — agendar ────────────────────────────────────────────────────
    def agendar_lote(self, dados: dict):
        try:
            import re
            import uuid
            itens    = dados.get("itens", [])
            time_str = dados["time_str"].strip()
            is_daily = dados.get("daily", False)
            incl_wk  = dados.get("include_weekends", True)

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

            # batch_id único para agrupar todos os itens deste lote
            batch_id = f"batch_{int(datetime.now().timestamp())}"

            count = 0
            for idx, item in enumerate(itens):
                target    = item["target"].strip()
                mode      = item["mode"]
                message   = item.get("message", "").strip()
                file_path = item.get("filePath") or None

                task_name = f"ZapLote_{int(datetime.now().timestamp())}_{idx}"
                t_id = db.adicionar(task_name=task_name, target=target, mode=mode,
                                    message=message, file_path=file_path, scheduled_time=dt)
                if t_id and t_id != -1:
                    # salva batch_id no registro
                    self._set_batch_id(t_id, batch_id)
                    json_cfg = {"target": target, "mode": mode,
                                "message": message, "file_path": file_path}
                    windows_scheduler.create_task_bat(t_id, task_name, json_cfg)
                    windows_scheduler.create_windows_task(
                        t_id, task_name, time_str, date_str,
                        daily=is_daily, include_weekends=incl_wk)
                    count += 1

            return {"ok": True, "count": count, "batch_id": batch_id}
        except Exception as e:
            return {"error": str(e)}

    def _set_batch_id(self, task_id: int, batch_id: str):
        """Salva o batch_id no banco para agrupar itens do lote."""
        import sqlite3
        from core.paths import get_user_data_dir
        db_path = Path(get_user_data_dir()) / "scheduler.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE agendamentos SET batch_id=? WHERE id=?", (batch_id, task_id))
        conn.commit()
        conn.close()

    # ── agendar simples ───────────────────────────────────────────────────
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

            json_cfg = {"target": target, "mode": mode, "message": message, "file_path": file_path}
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

    # ── arquivo ───────────────────────────────────────────────────────────
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


# ── Entrypoint ────────────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.api  = Api()
        self._win = None

    def mainloop(self):
        web_dir   = _get_web_dir()
        index     = web_dir / "index.html"
        icon_path = _get_icon_path()

        self._win = webview.create_window(
            title     = "Study Practices — WhatsApp Automation",
            url       = str(index) + f"?nocache={int(time_module.time())}",
            js_api    = self.api,
            width     = 540,
            height    = 860,
            min_size  = (420, 600),
            resizable = True,
        )
        webview.start(debug=False, icon=icon_path)