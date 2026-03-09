import os
import sys
import re
import traceback
import threading
import subprocess
import json
from pathlib import Path
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkcalendar import Calendar

# Importações do Core (Assumindo estrutura correta baseada no seu código original)
from core.db import db
from core import automation, windows_scheduler
from core.automation import contador_execucao 
from core.paths import get_whatsapp_profile_dir, get_app_base_dir

# --- Constantes ---
BASE_DIR = get_app_base_dir()
PROFILE_DIR = get_whatsapp_profile_dir()
THEME_FILE = os.path.join(BASE_DIR, "data", "theme_pref.txt")
GEOMETRY_FILE = os.path.join(BASE_DIR, "data", "window_pos.txt")

DEBUG_LOG = os.path.join(BASE_DIR, "gui_sync_debug.log")

def debug_log(msg):
    """Helper para log de debug de sincronização"""
    try:
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
    except:
        pass

def get_executor_path():
    """
    Retorna o caminho correto do executor.py independente de estar empacotado ou não.
    """
    if getattr(sys, 'frozen', False):
        # Executável empacotado: executor.py está em _internal/
        return Path(sys._MEIPASS) / "executor.py"
    else:
        # Desenvolvimento: executor.py está na raiz
        return Path(BASE_DIR) / "executor.py"

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Configurações Iniciais ---
        self.title("Study Practices - WhatsApp Automation")
        
        # Centralização de cores para facilitar mudanças futuras
        self.colors = {
            "primary": "#b39ddb",
            "hover": "#9575cd",
            "danger": "#CF5252",
            "danger_hover": "#ff0000",
            "success": "#4CAF50",
            "success_hover": "#277e0f",
            "text_disabled": "#d3d3d3",
            "gray": "gray"
        }
        
        # --- Variáveis de Estado ---
        self.file_path = None
        self.cards_agendamentos = {}
        self.temp_edit_file = None # Variável temporária para janela de edição

        # cache de estados para detectar mudança
        self.last_states = {}

        # --- Sequência de Inicialização ---
        self._restaurar_geometria()
        self._carregar_tema_salvo()
        self._aplicar_icone(self) # Aplica ícone na janela principal

        # --- Setup do Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self, 
                                      segmented_button_selected_color=self.colors["primary"], 
                                      segmented_button_selected_hover_color=self.colors["hover"])
        self.tabview.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tabview.add("Novo Envio")
        self.tabview.add("Meus Agendamentos")

        self._setup_envio_tab()
        self._setup_gestao_tab()
        
        # --- Carga Inicial de Dados ---
        self.atualizar_contador_exibicao()
        self._carregar_agendamentos()
        
        # --- Eventos e Loop ---
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        # Inicia loop de atualização após 5s
        self.after(2000, self._loop_atualizacao)

    # =========================================
    #            HELPERS E SISTEMA
    # =========================================

    def _aplicar_icone(self, window_obj):
        """Centraliza a lógica de carregar ícone para evitar repetição."""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        icon_path = os.path.join(base_path, "resources", "Taty_s-English-Logo.ico")
        
        if os.path.exists(icon_path):
            try:
                window_obj.iconbitmap(icon_path)
                # Pequeno delay para garantir que o ícone carregue em TopLevels
                if isinstance(window_obj, ctk.CTkToplevel):
                    window_obj.after(200, lambda: window_obj.iconbitmap(icon_path))
            except Exception:
                pass

    def _restaurar_geometria(self):
        if os.path.exists(GEOMETRY_FILE):
            try:
                with open(GEOMETRY_FILE, "r") as f:
                    geo = f.read().strip()
                    if geo: self.geometry(geo)
            except: self.geometry("500x750")
        else:
            self.geometry("500x750")

    def _ao_fechar(self):
        try:
            os.makedirs(os.path.dirname(GEOMETRY_FILE), exist_ok=True)
            with open(GEOMETRY_FILE, "w") as f:
                f.write(self.geometry())
        except: pass
        self.destroy()

    def _carregar_tema_salvo(self):
        if os.path.exists(THEME_FILE):
            try:
                with open(THEME_FILE, "r") as f: ctk.set_appearance_mode(f.read().strip())
            except: ctk.set_appearance_mode("system")
        else: ctk.set_appearance_mode("system")

    def _salvar_tema(self, modo):
        try:
            os.makedirs(os.path.dirname(THEME_FILE), exist_ok=True)
            with open(THEME_FILE, "w") as f: f.write(modo)
        except Exception as e: print(f"Erro ao salvar tema: {e}")

    def _alternar_tema(self):
        mode = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        ctk.set_appearance_mode(mode)
        self._salvar_tema(mode)

    def _loop_atualizacao(self):
        """Loop silencioso de atualização a cada 2 segundos."""
        try:
            self._carregar_agendamentos()
            self.atualizar_contador_exibicao()
        except Exception as e:
            import traceback
            with open("ui_errors.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] {traceback.format_exc()}\n")
        finally:
            self.after(2000, self._loop_atualizacao)

    def atualizar_contador_exibicao(self):
        try: 
            self.count_label.configure(text=f"🚀 Execuções: {contador_execucao(False)}")
        except: pass

    # =========================================
    #            COMPONENTES DE UI
    # =========================================

    def _aplicar_mascara_hora(self, event):
        """Aplica máscara HH:MM no campo de entrada."""
        entry = event.widget
        # Ignora teclas de navegação
        if event.keysym in ("Left", "Right", "Up", "Down", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return

        texto_atual = entry.get()
        cursor_pos = entry.index("insert")
        
        numeros = "".join([c for c in texto_atual if c.isdigit()])[:4]
        novo_texto = ""
        
        if len(numeros) > 0: novo_texto += numeros[:2]
        if len(numeros) > 2: novo_texto += ":" + numeros[2:]
        
        if texto_atual != novo_texto:
            entry.delete(0, "end")
            entry.insert(0, novo_texto)
            
            if event.keysym == "BackSpace":
                entry.icursor(cursor_pos)
            else:
                # Lógica inteligente para pular o cursor após os dois pontos
                if len(numeros) == 2 and cursor_pos == 2:
                    entry.icursor(3)
                elif len(numeros) == 3 and cursor_pos == 3:
                    entry.icursor(4)
                else:
                    entry.icursor(cursor_pos)

    def _abrir_calendario_custom(self, target_btn):
        top = ctk.CTkToplevel(self)
        top.title("Selecionar Data")
        top.attributes("-topmost", True)
        self._aplicar_icone(top)

        cal = Calendar(top, selectmode='day', date_pattern='dd/mm/yyyy',
                       background=self.colors["hover"],
                       selectbackground=self.colors["hover"],
                       selectforeground='white',
                       normalbackground='#f0f0f0',
                       weekendbackground='#e0e0e0')
        cal.pack(pady=10, padx=10)
        
        ctk.CTkButton(top, text="Confirmar", 
                      fg_color=self.colors["primary"], hover_color=self.colors["hover"], 
                      command=lambda: [target_btn.configure(text=cal.get_date()), top.destroy()]
                      ).pack(pady=5)

    # =========================================
    #            ABA 1: NOVO ENVIO
    # =========================================

    def _setup_envio_tab(self):
        tab = self.tabview.tab("Novo Envio")
        
        # Cabeçalho
        header_frame = ctk.CTkFrame(tab, border_width=1, border_color=("#DBDBDB", "#3d3d3d"))
        header_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        self.count_label = ctk.CTkLabel(header_frame, text="🚀 Execuções: 0", 
                                      font=("Roboto", 13, "bold"), text_color=self.colors["primary"])
        self.count_label.pack(side="left", padx=15, pady=8)
        
        self.theme_btn = ctk.CTkButton(header_frame, text="Alterar tema", width=100, height=28, 
                                     fg_color=self.colors["primary"], hover_color=self.colors["hover"], 
                                     command=self._alternar_tema)
        self.theme_btn.pack(side="right", padx=15)

        # Formulário
        ctk.CTkLabel(tab, text="Contato / Número:", font=("Roboto", 12)).pack(anchor="w", padx=15, pady=(5, 0))
        self.target_input = ctk.CTkEntry(tab, placeholder_text="Ex: 5511999999999 / Tips Basic", height=35)
        self.target_input.pack(fill="x", padx=10, pady=5)

        self.mode_select = ctk.CTkOptionMenu(tab, values=["Somente texto", "Somente arquivo", "Arquivo + texto"], 
                                           command=self._on_mode_change, 
                                           fg_color=self.colors["primary"], button_color=self.colors["primary"], 
                                           button_hover_color=self.colors["hover"])
        self.mode_select.pack(fill="x", padx=10, pady=5)

        self.message_input = ctk.CTkTextbox(tab, height=150, border_width=1)
        self.message_input.pack(fill="both", expand=True, padx=10, pady=5)
        self._setup_placeholder(self.message_input, "Digite sua mensagem aqui...")

        # Área de Arquivo e Data
        action_box = ctk.CTkFrame(tab, border_width=1)
        action_box.pack(fill="x", padx=10, pady=10)

        file_frame = ctk.CTkFrame(action_box, fg_color="transparent")
        file_frame.pack(fill="x", padx=10, pady=10)
        self.file_btn = ctk.CTkButton(file_frame, text="Selecionar Arquivo(s)", state="disabled", 
                                    fg_color=self.colors["text_disabled"], hover_color=self.colors["hover"], 
                                    command=self._select_file)
        self.file_btn.pack(side="left")
        self.file_label = ctk.CTkLabel(file_frame, text="Nenhum arquivo", font=("Roboto", 10), text_color=self.colors["gray"])
        self.file_label.pack(side="left", padx=10)

        # --- Linha de Data/Hora + Checkbox "Todos os dias" ---
        dt_frame = ctk.CTkFrame(action_box, fg_color="transparent")
        dt_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.date_button = ctk.CTkButton(dt_frame, text=datetime.now().strftime("%d/%m/%Y"), 
                                       fg_color=self.colors["primary"], hover_color=self.colors["hover"], 
                                       command=lambda: self._abrir_calendario_custom(self.date_button))
        self.date_button.pack(side="left", padx=(0, 10))
        
        self.time_input = ctk.CTkEntry(dt_frame, width=100)
        self.time_input.pack(side="left")
        self.time_input.bind("<KeyRelease>", self._aplicar_mascara_hora)
        self._reset_time()

        # ── NOVO: Checkbox "Todos os dias" ──
        self.daily_var = ctk.BooleanVar(value=False)
        self.daily_checkbox = ctk.CTkCheckBox(
            dt_frame,
            text="Todos os dias",
            variable=self.daily_var,
            fg_color=self.colors["primary"],
            hover_color=self.colors["hover"],
            command=self._on_daily_toggle
        )
        self.daily_checkbox.pack(side="left", padx=(12, 0))

        # Botões de Ação
        actions_frame = ctk.CTkFrame(tab, fg_color="transparent")
        actions_frame.pack(fill="x", padx=10, pady=10)
        
        # O botão Enviar Agora agora chama uma thread
        ctk.CTkButton(actions_frame, text="Enviar Agora", height=45, 
                      fg_color=self.colors["primary"], hover_color=self.colors["hover"], 
                      command=self._start_send_thread).pack(side="left", expand=True, padx=5)
        
        ctk.CTkButton(actions_frame, text="Agendar", height=45, 
                      fg_color=self.colors["primary"], hover_color=self.colors["hover"], 
                      command=self._schedule_task).pack(side="left", expand=True, padx=5)

    def _on_daily_toggle(self):
        """Quando 'Todos os dias' é marcado, esconde o seletor de data (não faz sentido para recorrente)."""
        if self.daily_var.get():
            self.date_button.configure(state="disabled", fg_color=self.colors["text_disabled"])
        else:
            self.date_button.configure(state="normal", fg_color=self.colors["primary"])

    def _perguntar_fins_de_semana(self):
        """
        Abre uma janela modal perguntando se o envio inclui sábado e domingo.
        Retorna True (incluir) ou False (somente dias úteis).
        """
        resultado = {"include": None}

        dialog = ctk.CTkToplevel(self)
        dialog.title("Fins de semana?")
        dialog.geometry("340x160")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        self._aplicar_icone(dialog)

        ctk.CTkLabel(
            dialog,
            text="Enviar também aos sábados e domingos?",
            font=("Roboto", 13),
            wraplength=300
        ).pack(pady=(25, 15), padx=20)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack()

        def escolher(include):
            resultado["include"] = include
            dialog.grab_release()
            dialog.destroy()

        ctk.CTkButton(
            btn_frame, text="Sim", width=120,
            fg_color=self.colors["primary"], hover_color=self.colors["hover"],
            command=lambda: escolher(True)
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame, text="Não (Seg–Sex)", width=140,
            fg_color=self.colors["gray"], hover_color="#555555",
            command=lambda: escolher(False)
        ).pack(side="left", padx=10)

        # Aguarda o dialog fechar
        self.wait_window(dialog)
        return resultado["include"]

    def _setup_placeholder(self, textbox, placeholder_text):
        """Lógica para placeholder em caixa de texto multiline"""
        textbox.insert("0.0", placeholder_text)
        def on_focus_in(event):
            if textbox.get("1.0", "end-1c") == placeholder_text:
                textbox.delete("1.0", "end")
        def on_focus_out(event):
            if not textbox.get("1.0", "end-1c").strip():
                textbox.insert("0.0", placeholder_text)
        textbox.bind("<FocusIn>", on_focus_in)
        textbox.bind("<FocusOut>", on_focus_out)

    def _on_mode_change(self, choice):
        state = "normal" if choice != "Somente texto" else "disabled"
        color = self.colors["primary"] if choice != "Somente texto" else self.colors["text_disabled"]
        self.file_btn.configure(state=state, fg_color=color)
        
        if choice == "Somente arquivo":
            self.message_input.delete("1.0", "end")
            self.message_input.configure(state="disabled")
        else:
            self.message_input.configure(state="normal")

    def _select_file(self):
        paths = filedialog.askopenfilenames()
        if paths:
            self.file_path = "\n".join(paths)
            self.file_label.configure(text=f"{len(paths)} arquivo(s)" if len(paths) > 1 else os.path.basename(paths[0]))

    def _reset_time(self):
        self.time_input.delete(0, 'end')
        self.time_input.insert(0, (datetime.now() + timedelta(minutes=2)).strftime("%H:%M"))

    def _reset_fields(self):
        self.target_input.delete(0, 'end')
        self.message_input.configure(state="normal")
        self.message_input.delete("1.0", "end")
        self.file_path = None
        self.file_label.configure(text="Nenhum arquivo")
        self.mode_select.set("Somente texto")
        self._on_mode_change("Somente texto")
        self._reset_time()
        self.date_button.configure(text=datetime.now().strftime("%d/%m/%Y"), state="normal", fg_color=self.colors["primary"])
        self.daily_var.set(False)

    # =========================================
    #            LÓGICA: VALIDAÇÃO E AÇÕES
    # =========================================

    def _validar_campos(self, target, mode, message, file_path):
        if not target:
            messagebox.showerror("Campo Vazio", "Por favor, insira o contato ou número.")
            return False
        msg_limpa = message.strip() if message else ""
        
        if mode == "text" and not msg_limpa:
            messagebox.showerror("Mensagem Vazia", "O modo 'Somente texto' exige uma mensagem.")
            return False
        elif mode == "file" and not file_path:
            messagebox.showerror("Arquivo Ausente", "Selecione ao menos um arquivo.")
            return False
        elif mode == "file_text":
            erros = []
            if not file_path: erros.append("- Selecionar ao menos um arquivo")
            if not msg_limpa: erros.append("- Escrever uma mensagem")
            if erros:
                messagebox.showerror("Dados Insuficientes", "Erros:\n" + "\n".join(erros))
                return False
        return True

    def _get_mode_key(self, display_value=None):
        val = display_value if display_value else self.mode_select.get()
        m = {"Somente texto": "text", "Somente arquivo": "file", "Arquivo + texto": "file_text"}
        return m.get(val, "text")

    def _start_send_thread(self):
        """
        Versão MELHORADA - usa thread para não bloquear GUI.
        """
        target = self.target_input.get().strip()
        message = self.message_input.get("1.0", "end-1c").strip()
        mode = self._get_mode_key()
        
        if not self._validar_campos(target, mode, message, self.file_path): 
            return
        
        # Cria JSON
        task_data = {
            "task_id": None,
            "target": target,
            "mode": mode,
            "message": message,
            "file_path": self.file_path
        }
        
        temp_dir = Path(BASE_DIR) / "temp_tasks"
        temp_dir.mkdir(exist_ok=True)
        
        timestamp = int(datetime.now().timestamp())
        json_path = temp_dir / f"manual_{timestamp}.json"
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)
        
        # CORRIGIDO: Usa a função get_executor_path()
        executor_path = get_executor_path()
        
        if not executor_path.exists():
            messagebox.showerror("Erro", f"executor.py não encontrado em {executor_path}")
            return
        
        if getattr(sys, 'frozen', False):
            # No modo .exe, chamamos o próprio executável com a flag que o app.py espera
            comando = [sys.executable, "--executor-json", str(json_path)]
        else:
            # No modo desenvolvimento, chamamos o interpretador + script executor
            comando = [sys.executable, str(executor_path), str(json_path)]
        
        # Inicia processo
        try:
            if sys.platform == 'win32':
                creationflags = subprocess.CREATE_NO_WINDOW
            else:
                creationflags = 0
            
            processo = subprocess.Popen(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                cwd=str(BASE_DIR),
                encoding='utf-8',
                errors='replace'
            )
            
            # Thread separada para monitorar
            monitor_thread = threading.Thread(
                target=self._aguardar_processo_em_thread,
                args=(processo, json_path),
                daemon=False
            )
            monitor_thread.start()
            
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Erro", f"Falha ao iniciar executor:\n{str(e)}")

    def _aguardar_processo_em_thread(self, processo, json_path):
        """
        Roda em thread SEPARADA para não bloquear GUI.
        """
        stdout, stderr = processo.communicate()
        retcode = processo.returncode
        
        # Volta para thread principal para atualizar GUI
        self.after(0, lambda: self._processar_resultado_processo(
            retcode, stdout, stderr, json_path
        ))

    def _processar_resultado_processo(self, retcode, stdout, stderr, json_path):
        """
        Roda na thread PRINCIPAL (seguro para atualizar GUI).
        """
        print(f"[DEBUG] Processo terminou com código: {retcode}")
        print(f"[DEBUG] STDOUT: {stdout if stdout else '(vazio)'}")
        print(f"[DEBUG] STDERR: {stderr if stderr else '(vazio)'}")
        
        status_file = Path(json_path).with_suffix('.status')
        
        if retcode == 0:
            messagebox.showinfo("Sucesso", "Mensagem enviada!")
            self._reset_fields()
            contador_execucao(True)
            self.atualizar_contador_exibicao()
        else:
            erro_msg = "Erro desconhecido"
            
            if status_file.exists():
                with open(status_file, encoding='utf-8') as f:
                    erro_msg = f.read()
            elif stderr:
                erro_msg = stderr
            
            messagebox.showerror("Erro", f"Falha no envio:\n\n{erro_msg}")
        
        # Limpa temp files
        try:
            json_path.unlink()
            if status_file.exists():
                status_file.unlink()
        except Exception as e:
            print(f"[DEBUG] Erro ao limpar: {e}")

    def _schedule_task(self):
        target = self.target_input.get().strip()
        message = self.message_input.get("1.0", "end-1c").strip()
        mode = self._get_mode_key()
        d, t = self.date_button.cget("text"), self.time_input.get().strip()
        is_daily = self.daily_var.get()

        if not self._validar_campos(target, mode, message, self.file_path):
            return
        
        if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', t):
            return messagebox.showerror(
                "Erro", 
                "Hora inválida. Use formato HH:MM (00:00 a 23:59)"
            )

        # ── NOVO: se for diário, pergunta sobre fins de semana antes de continuar ──
        include_weekends = None
        if is_daily:
            include_weekends = self._perguntar_fins_de_semana()
            if include_weekends is None:
                # Usuário fechou o dialog sem escolher
                return

        try:
            if is_daily:
                # Para agendamento diário usa a data de hoje como referência
                dt = datetime.strptime(f"{datetime.now().strftime('%d/%m/%Y')} {t}", "%d/%m/%Y %H:%M")
            else:
                dt = datetime.strptime(f"{d} {t}", "%d/%m/%Y %H:%M")
                if dt < datetime.now():
                    return messagebox.showerror("Erro", "O horário deve ser no futuro.")
            
            task_name = f"ZapTask_{int(datetime.now().timestamp())}"
            t_id = db.adicionar(task_name=task_name, target=target, mode=mode, message=message, 
                                file_path=self.file_path, scheduled_time=dt)

            if not t_id or t_id == -1:
                return messagebox.showerror("Erro", "Falha ao salvar no banco de dados")
            
            # Passa os novos parâmetros de recorrência para a thread
            threading.Thread(
                target=self._criar_tarefa_agendada, 
                args=(t_id, task_name, target, mode, message, self.file_path, t, d,
                      is_daily, include_weekends),
                daemon=True
            ).start()

        except Exception as e: 
            messagebox.showerror("Erro", str(e))

    def _criar_tarefa_agendada(self, t_id, task_name, target, mode, message, file_path,
                                time_str, date_str, daily=False, include_weekends=True):
        try:
            from core import windows_scheduler
            json_cfg = {"target": target, "mode": mode, "message": message, "file_path": file_path}
            windows_scheduler.create_task_bat(t_id, task_name, json_cfg)
            suc, msg = windows_scheduler.create_windows_task(
                t_id, task_name, time_str, date_str,
                daily=daily, include_weekends=include_weekends
            )
            
            if suc:
                if daily:
                    modo_txt = "todos os dias" if include_weekends else "dias úteis (Seg–Sex)"
                    info_msg = f"Tarefa recorrente criada!\nEnvio: {time_str} | {modo_txt}"
                else:
                    info_msg = "Tarefa criada com sucesso!"
                self.after(0, lambda: messagebox.showinfo("Agendado", info_msg))
                self.after(0, self._carregar_agendamentos)
                self.after(0, self._reset_fields)
            else:
                db.deletar(t_id)
                self.after(0, lambda: messagebox.showerror("Erro", f"Falha no Agendador:\n{msg}"))
        except Exception as e:
            db.deletar(t_id)
            self.after(0, lambda: messagebox.showerror("Erro", f"Erro interno:\n{str(e)}"))

    # =========================================
    #            ABA 2: GESTÃO E HISTÓRICO
    # =========================================

    def _setup_gestao_tab(self):
        tab = self.tabview.tab("Meus Agendamentos")
        # header com status sync 
        header = ctk.CTkFrame(tab)
        header.pack(fill="x", padx=10, pady=(10,5))
    
        self.sync_label = ctk.CTkLabel(
        header, 
        text="Sincronizando...", 
        font=("Roboto", 10),
        text_color="gray"
        )
        self.sync_label.pack(side="right", padx=10)

        self.scrollable_frame = ctk.CTkScrollableFrame(tab, label_text="Histórico")
        self.scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)

    def _carregar_agendamentos(self):
        """Atualização Inteligente: Só mexe no DOM se houver mudanças."""
        try:
            if hasattr(self, 'sync_label'):
                self.sync_label.configure(text="🔄 Atualizando...", text_color="orange")
            agendamentos = db.listar_todos()
            ids_atuais = [row[0] for row in agendamentos]
        
            # 1. Remove itens deletados
            for t_id in list(self.cards_agendamentos.keys()):
                if t_id not in ids_atuais:
                    self.cards_agendamentos[t_id]['frame'].destroy()
                    del self.cards_agendamentos[t_id]
            
            status_colors = {
                "pending": self.colors["gray"], 
                "running": "#2196F3", 
                "completed": self.colors["success"], 
                "failed": self.colors["danger"],
                "cancelled": "#ff9800"
            }

            for row in agendamentos:
                t_id, _, target, _, sched_time, status = row[0], row[1], row[2], row[3], row[4], row[5]
                status_lower = str(status).lower()
                cor = status_colors.get(status_lower, self.colors["gray"])
                
                try: dt_amigavel = datetime.fromisoformat(sched_time).strftime("%d/%m/%Y %H:%M")
                except: dt_amigavel = sched_time

                # 2. Atualiza existentes (Sem piscar a tela)
                if t_id in self.cards_agendamentos:
                    card = self.cards_agendamentos[t_id]
                    if card['status_str'] != status_lower:
                        card['label_status'].configure(text=status_lower.upper(), text_color=cor)
                        card['status_str'] = status_lower
                        state = "normal" if status_lower != "running" else "disabled"
                        card['btn_edit'].configure(state=state)
                        card['btn_del'].configure(state=state)
                    
                    if card['label_target'].cget("text") != f"📱 {target}":
                        card['label_target'].configure(text=f"📱 {target}")
                    if card['label_date'].cget("text") != f"📅 {dt_amigavel}":
                        card['label_date'].configure(text=f"📅 {dt_amigavel}")

                # 3. Cria novos
                else:
                    self._criar_card_agendamento(t_id, row, target, dt_amigavel, status_lower, cor)
            if hasattr(self, 'sync_label'):
                self.sync_label.configure(
                    text=f"✅ Última atualização: {datetime.now().strftime('%H:%M:%S')}", 
                    text_color="green"
                )
        except Exception as e:
            self.sync_label.configure(text="❌ Erro na sincronização", text_color="red")
            raise

    def _criar_card_agendamento(self, t_id, row, target, dt_text, status_str, status_color):
        card = ctk.CTkFrame(self.scrollable_frame, border_width=1)
        card.pack(fill="x", pady=5, padx=5)
        
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        lbl_target = ctk.CTkLabel(info, text=f"📱 {target}", font=("Roboto", 12, "bold"))
        lbl_target.pack(anchor="w")
        lbl_date = ctk.CTkLabel(info, text=f"📅 {dt_text}", font=("Roboto", 10), text_color="gray")
        lbl_date.pack(anchor="w")

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(side="right", padx=10)
        
        lbl_status = ctk.CTkLabel(actions, text=status_str.upper(), text_color=status_color, font=("Roboto", 9, "bold"))
        lbl_status.pack()

        btns = ctk.CTkFrame(actions, fg_color="transparent")
        btns.pack()

        btn_state = "normal" if status_str not in ["running", "completed"] else "disabled"

        
        b_edit = ctk.CTkButton(btns, text="📝", width=30, fg_color=self.colors["primary"], hover_color=self.colors["hover"], 
                               command=lambda r=row: self._abrir_edicao(r))
        b_edit.pack(side="left", padx=2)
        
        b_del = ctk.CTkButton(btns, text="🗑️", width=30, fg_color=self.colors["danger"], hover_color=self.colors["danger_hover"], 
                              command=lambda r=row: self._excluir_agendamento(r))
        b_del.pack(side="left", padx=2)
        
        self.cards_agendamentos[t_id] = {
            'frame': card, 'label_status': lbl_status, 'label_target': lbl_target,
            'label_date': lbl_date, 'status_str': status_str, 'btn_edit': b_edit, 'btn_del': b_del
        }

    def _excluir_agendamento(self, row):
        if messagebox.askyesno("Excluir", f"Deseja remover {row[2]}?"):
            try:
                windows_scheduler.delete_windows_task(row[0])
                db.deletar(row[0])
                self._carregar_agendamentos()
            except Exception as e: messagebox.showerror("Erro", str(e))

    def _abrir_edicao(self, row):
        task_data = db.obter_por_id(row[0])
        if not task_data: return

        edit_win = ctk.CTkToplevel(self)
        edit_win.title("Editar Agendamento")
        edit_win.geometry("420x780")
        self._aplicar_icone(edit_win)
        edit_win.transient(self)
        edit_win.lift(); edit_win.focus_force()

        self.temp_edit_file = task_data['file_path']
        dt_original = datetime.fromisoformat(task_data['scheduled_time'])

        # Construção UI Edição
        ctk.CTkLabel(edit_win, text="Contato:").pack(pady=(15,0))
        target_ent = ctk.CTkEntry(edit_win, width=320)
        target_ent.insert(0, task_data['target'])
        target_ent.pack()

        ctk.CTkLabel(edit_win, text="Forma de Envio:").pack(pady=(10,0))
        map_modos = {"text": "Somente texto", "file": "Somente arquivo", "file_text": "Arquivo + texto"}
        rev_map = {v: k for k, v in map_modos.items()}
        
        msg_txt = ctk.CTkTextbox(edit_win, height=120, width=320)
        btn_alt_file = ctk.CTkButton(edit_win, text="Alterar Arquivo(s)", width=150, height=28, fg_color=self.colors["primary"], hover_color=self.colors["hover"])
        lbl_f = ctk.CTkLabel(edit_win, text="", font=("Roboto", 10))

        def atualizar_ui_edicao(choice):
            if choice == "Somente texto":
                btn_alt_file.configure(state="disabled", fg_color=self.colors["text_disabled"])
                msg_txt.configure(state="normal")
            elif choice == "Somente arquivo":
                msg_txt.delete("1.0", "end"); msg_txt.configure(state="disabled")
                btn_alt_file.configure(state="normal", fg_color=self.colors["primary"])
            else:
                msg_txt.configure(state="normal")
                btn_alt_file.configure(state="normal", fg_color=self.colors["primary"])

        mode_select = ctk.CTkOptionMenu(edit_win, values=list(map_modos.values()), 
                                      fg_color=self.colors["primary"], button_color=self.colors["primary"], button_hover_color=self.colors["hover"], width=320, command=atualizar_ui_edicao)
        mode_select.set(map_modos.get(task_data['mode'], "Somente texto"))
        mode_select.pack(pady=5)

        ctk.CTkLabel(edit_win, text="Mensagem:").pack(pady=5)
        msg_txt.insert("1.0", task_data['message'] or ""); msg_txt.pack()

        # Edição Data/Hora
        ctk.CTkLabel(edit_win, text="Data e Horário:").pack(pady=5)
        dt_fr = ctk.CTkFrame(edit_win, fg_color="transparent")
        dt_fr.pack()

        # ── NOVO: Variável de controle para "todos os dias" na edição ──
        edit_daily_var = ctk.BooleanVar(value=False)

        btn_date = ctk.CTkButton(dt_fr, text=dt_original.strftime("%d/%m/%Y"), width=120, 
                               fg_color=self.colors["primary"], hover_color=self.colors["hover"],
                               command=lambda: self._abrir_calendario_custom(btn_date))
        btn_date.pack(side="left", padx=5)
        
        time_ent = ctk.CTkEntry(dt_fr, width=80)
        time_ent.insert(0, dt_original.strftime("%H:%M"))
        time_ent.pack(side="left", padx=5)
        time_ent.bind("<KeyRelease>", self._aplicar_mascara_hora)

        # ── NOVO: Checkbox "Todos os dias" na janela de edição ──
        def _toggle_edit_daily():
            if edit_daily_var.get():
                btn_date.configure(state="disabled", fg_color=self.colors["text_disabled"])
            else:
                btn_date.configure(state="normal", fg_color=self.colors["primary"])

        edit_daily_cb = ctk.CTkCheckBox(
            dt_fr,
            text="Todos os dias",
            variable=edit_daily_var,
            fg_color=self.colors["primary"],
            hover_color=self.colors["hover"],
            command=_toggle_edit_daily
        )
        edit_daily_cb.pack(side="left", padx=(8, 0))

        # Lógica de Arquivo
        def atualizar_lbl_file():
            count = len(self.temp_edit_file.split('\n')) if self.temp_edit_file else 0
            lbl_f.configure(text=f"Arquivos atuais: {count}")
        
        lbl_f.pack()
        atualizar_lbl_file()

        def selecionar_arq_edit():
            p = filedialog.askopenfilenames()
            if p:
                self.temp_edit_file = "\n".join(p)
                atualizar_lbl_file()
        
        btn_alt_file.configure(command=selecionar_arq_edit)
        btn_alt_file.pack(pady=5)
        atualizar_ui_edicao(mode_select.get())

        def salvar_edicao():
            try:
                t_val = target_ent.get().strip()
                m_val = rev_map.get(mode_select.get())
                msg_val = msg_txt.get("1.0", "end-1c").strip()
                h_val = time_ent.get().strip()
                is_daily_edit = edit_daily_var.get()

                if not self._validar_campos(t_val, m_val, msg_val, self.temp_edit_file): return
                if len(h_val) != 5: return messagebox.showerror("Erro", "Hora inválida")

                # ── NOVO: pergunta fins de semana se for recorrente ──
                include_wk = None
                if is_daily_edit:
                    include_wk = self._perguntar_fins_de_semana()
                    if include_wk is None:
                        return  # Usuário cancelou

                if is_daily_edit:
                    nova_dt = datetime.strptime(
                        f"{datetime.now().strftime('%d/%m/%Y')} {h_val}", "%d/%m/%Y %H:%M"
                    )
                else:
                    nova_dt = datetime.strptime(f"{btn_date.cget('text')} {h_val}", "%d/%m/%Y %H:%M")
                    if nova_dt < datetime.now():
                        return messagebox.showerror("Erro", "Data no passado")

                windows_scheduler.delete_windows_task(task_data['id'])
                db.atualizar_agendamento_completo(task_data['id'], t_val, m_val, msg_val, self.temp_edit_file, nova_dt)
                
                json_cfg = {"target": t_val, "mode": m_val, "message": msg_val, "file_path": self.temp_edit_file}
                windows_scheduler.create_task_bat(task_data['id'], task_data['task_name'], json_cfg)
                windows_scheduler.create_windows_task(
                    task_data['id'], task_data['task_name'], h_val,
                    btn_date.cget('text'),
                    daily=is_daily_edit,
                    include_weekends=include_wk if include_wk is not None else True
                )

                if is_daily_edit:
                    modo_txt = "todos os dias" if include_wk else "dias úteis (Seg–Sex)"
                    messagebox.showinfo("Sucesso", f"Atualizado!\nRecorrência: {modo_txt}")
                else:
                    messagebox.showinfo("Sucesso", "Atualizado!")

                edit_win.destroy()
                self._carregar_agendamentos()
            except Exception as e:
                messagebox.showerror("Erro", str(e))

        ctk.CTkButton(edit_win, text="Salvar Alterações", fg_color=self.colors["success"], hover_color=self.colors["success_hover"], 
                      height=45, command=salvar_edicao).pack(pady=25)

if __name__ == "__main__":
    app = App()
    app.mainloop()