"""
CMaker Photo Commander - Interface Gráfica
Gerenciador e Transferência de Fotos e Vídeos do iPhone via USB no Windows.
Recursos:
- Painel Duplo Dual-Pane (iPhone à esquerda, PC Local à direita)
- Painel de Pré-visualização com Miniaturas (Thumbnails) para fotos e vídeos
- Exclusão segura de itens diretamente do iPhone com confirmação
- Nomenclatura no padrão AAAA-MM-DD[-Local] com GPS automático
- Abas inferiores de Fila de Transferência, Concluídos, Falhas e Log de Console
"""

import os
import sys
import time
import io
import json
import shutil
import queue
import threading
import re
import random
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import cv2

# Previne falhas se stdout/stderr forem None (modo sem console) e garante UTF-8 no Windows
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Suporte a execução tanto como script Python quanto executável congelado (PyInstaller)
if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR))
    PROJECT_ROOT = EXE_DIR
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = PROJECT_ROOT

CONFIG_FILE = PROJECT_ROOT / "config.json"
# Busca a pasta anim ao lado do executável ou embutida no pacote PyInstaller
ANIM_DIR = PROJECT_ROOT / "anim" if (PROJECT_ROOT / "anim").exists() else BUNDLE_DIR / "anim"
VIDEO_PATH = ANIM_DIR / "gemini_generated_video_7b48f753.mp4"
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.iphone_manager import IPhoneManager, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS
from scripts.geo_utils import sanitize_name, extract_gps, reverse_geocode

MESES_NOMES = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro"
}

VIEW_MODES = ["📑 Detalhes", "📄 Lista", "🖼️ Miniaturas", "🔍 Miniaturas Gigantes"]
APP_VERSION = "v2.8.0"

def natural_sort_key(s: str) -> list:
    """Gera chave de ordenação natural do Windows Explorer (ex: 'IMG_2' antes de 'IMG_10')."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s or ""))]

def format_size(bytes_size: int) -> str:
    """Formata bytes para representação legível (KB, MB, GB)."""
    if not bytes_size or bytes_size <= 0:
        return "0 KB"
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


class FileZillaIPhoneApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"CMaker Photo Commander {APP_VERSION} - Transferência USB & Pastas")
        self.root.geometry("1240x820")
        self.root.minsize(1050, 700)

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.manager = IPhoneManager()
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self.ui_queue = queue.Queue()
        self.thumb_queue = queue.Queue()
        self.grid_thumb_queue = queue.Queue()
        self.current_preview_path = None
        self.cached_photo_img = None

        self._photo_cache: Dict[str, ImageTk.PhotoImage] = {}
        self._orig_cards: List[Tuple] = []
        self._dest_cards: List[Tuple] = []
        self._dest_files_cache: List[Dict] = []
        self._last_orig_cols = 0
        self._last_dest_cols = 0

        # Controle de ordenação de colunas (estilo FileZilla / Explorer)
        self._orig_sort_col = None
        self._orig_sort_desc = False
        self._dest_sort_col = None
        self._dest_sort_desc = False

        self.iphone_items = []          # Todos os itens varridos
        self.displayed_items = []       # Itens filtrados visíveis
        self.item_checkboxes = {}       # {idx: bool}

        self._last_normal_geometry = "1240x820"
        self._saved_h_sashes = None
        self._saved_v_sash = None
        self._window_state = "normal"

        self._init_vars()
        self._load_config()
        self._build_filezilla_ui()
        self._update_dest_disk_space()
        self._start_thumb_workers()
        self._apply_orig_view_mode()
        self._apply_dest_view_mode()

        self.root.bind("<Configure>", self._on_root_configure)
        self.root.after(100, self._restore_sash_positions)
        self.root.after(30, self._process_ui_queue)

        if self.var_source_type.get() == "📁 Pasta / Disco Local":
            self.root.after(100, self._on_source_type_changed)
        else:
            self.root.after(100, self._auto_connect_async)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _safe_call(self, fn):
        """Despacha uma função para execução 100% thread-safe na thread principal do Tkinter."""
        self.ui_queue.put(fn)

    def _process_ui_queue(self):
        """Processa as chamadas enfileiradas pelas threads de trabalho dentro do loop principal."""
        while not self.ui_queue.empty():
            try:
                fn = self.ui_queue.get_nowait()
                fn()
            except Exception as e:
                pass
        try:
            if self.root.winfo_exists():
                self.root.after(30, self._process_ui_queue)
        except Exception:
            pass

    def _init_vars(self):
        self.recent_paths = [str(Path.home() / "Pictures" / "Backup_IPhone")]
        self.var_source_type = tk.StringVar(value="📱 Apple iPhone (USB)")
        self.var_source_dir = tk.StringVar(value="")
        self.recent_source_paths: List[str] = []

        self.var_orig_view = tk.StringVar(value="📑 Detalhes")
        self.var_dest_view = tk.StringVar(value="📑 Detalhes")

        self.var_device_status = tk.StringVar(value="Verificando iPhone...")
        self.var_dest_dir = tk.StringVar(value=self.recent_paths[0])
        self.var_filter_text = tk.StringVar(value="")
        self.var_folder_filter = tk.StringVar(value="Todas as Pastas")
        self.var_custom_local = tk.StringVar(value="")
        self.var_use_gps = tk.BooleanVar(value=True)
        self.var_skip_existing = tk.BooleanVar(value=True)

        # Filtros de data (desativados por padrão para não restringir busca)
        self.var_filter_mode = tk.StringVar(value="month")
        self.var_selected_year = tk.StringVar(value="")
        self.var_selected_month = tk.StringVar(value="")
        self.var_filter_by_date = tk.BooleanVar(value=False)
        self.var_date_from = tk.StringVar(value="")
        self.var_date_to = tk.StringVar(value="")

        self.var_inc_photos = tk.BooleanVar(value=True)
        self.var_inc_videos = tk.BooleanVar(value=True)
        self.var_play_sound = tk.BooleanVar(value=True)

        # Status e Progresso (Barra Total e Barra por Arquivo)
        self.var_status_msg = tk.StringVar(value="Pronto.")
        self.var_progress_val = tk.DoubleVar(value=0.0)
        self.var_progress_stats = tk.StringVar(value="")
        self.var_pct_label = tk.StringVar(value="0.0%")

        self.var_file_status = tk.StringVar(value="Pronto para transferir.")
        self.var_file_progress_val = tk.DoubleVar(value=0.0)
        self.var_file_pct_label = tk.StringVar(value="0.0%")
        self.var_summary_iphone = tk.StringVar(value="0 arquivos")
        self.var_orig_sel_size = tk.StringVar(value="📦 Total Selecionado: 0 KB (0 arquivos)")
        self.var_summary_local = tk.StringVar(value="0 arquivos")
        self.var_dest_disk_free = tk.StringVar(value="💾 Livre: --")

        # Detalhes de Preview
        self.var_prev_name = tk.StringVar(value="Nenhum item selecionado")
        self.var_prev_date = tk.StringVar(value="-")
        self.var_prev_size = tk.StringVar(value="-")
        self.var_prev_loc = tk.StringVar(value="-")

    def _load_config(self):
        """Carrega as últimas configurações salvas no config.json."""
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "source_type" in cfg and cfg["source_type"]:
                self.var_source_type.set(cfg["source_type"])
            if "source_dir" in cfg and cfg["source_dir"]:
                self.var_source_dir.set(cfg["source_dir"])
            if "recent_source_paths" in cfg and isinstance(cfg["recent_source_paths"], list):
                self.recent_source_paths = [p for p in cfg["recent_source_paths"] if p]
            if "orig_view_mode" in cfg and cfg["orig_view_mode"] in VIEW_MODES:
                self.var_orig_view.set(cfg["orig_view_mode"])
            if "dest_view_mode" in cfg and cfg["dest_view_mode"] in VIEW_MODES:
                self.var_dest_view.set(cfg["dest_view_mode"])
            if "recent_paths" in cfg and isinstance(cfg["recent_paths"], list):
                self.recent_paths = [p for p in cfg["recent_paths"] if p]
            if "dest_dir" in cfg and cfg["dest_dir"]:
                self.var_dest_dir.set(cfg["dest_dir"])
                if cfg["dest_dir"] not in self.recent_paths:
                    self.recent_paths.insert(0, cfg["dest_dir"])
            # Etiqueta (custom_local) é estritamente temporária e não persistente
            self.var_custom_local.set("")
            if "use_gps" in cfg:
                self.var_use_gps.set(bool(cfg["use_gps"]))
            if "skip_existing" in cfg:
                self.var_skip_existing.set(bool(cfg["skip_existing"]))
            if "inc_photos" in cfg:
                self.var_inc_photos.set(bool(cfg["inc_photos"]))
            if "inc_videos" in cfg:
                self.var_inc_videos.set(bool(cfg["inc_videos"]))
            if "play_sound" in cfg:
                self.var_play_sound.set(bool(cfg["play_sound"]))
            if "filter_by_date" in cfg:
                self.var_filter_by_date.set(bool(cfg["filter_by_date"]))
            if "date_from" in cfg:
                self.var_date_from.set(cfg["date_from"])
            if "date_to" in cfg:
                self.var_date_to.set(cfg["date_to"])
            if "window_geometry" in cfg and cfg["window_geometry"]:
                try:
                    self.root.geometry(cfg["window_geometry"])
                    self._last_normal_geometry = cfg["window_geometry"]
                except Exception:
                    pass
            if cfg.get("window_state") == "zoomed":
                self._window_state = "zoomed"
                try:
                    self.root.state("zoomed")
                except Exception:
                    pass
            if "paned_h_sashes" in cfg and isinstance(cfg["paned_h_sashes"], list):
                self._saved_h_sashes = cfg["paned_h_sashes"]
            if "paned_v_sash" in cfg and isinstance(cfg["paned_v_sash"], (int, float)):
                self._saved_v_sash = cfg["paned_v_sash"]
        except Exception as e:
            print(f"Erro ao carregar configurações: {e}")

    def _on_root_configure(self, event=None):
        """Monitora e atualiza a geometria normal quando a janela não estiver maximizada."""
        if event and event.widget == self.root:
            try:
                if self.root.state() == "normal":
                    self._last_normal_geometry = self.root.geometry()
            except Exception:
                pass

    def _restore_sash_positions(self):
        """Restaura as posições salvas das barras divisórias verticais e horizontais."""
        try:
            self.root.update_idletasks()
            win_w = self.root.winfo_width()
            win_h = self.root.winfo_height()

            if hasattr(self, "paned_main") and self._saved_h_sashes and len(self._saved_h_sashes) >= 2:
                s0, s1 = self._saved_h_sashes[0], self._saved_h_sashes[1]
                if 80 < s0 < win_w and s0 < s1 < win_w:
                    self.paned_main.sash_place(0, int(s0), 0)
                    self.paned_main.sash_place(1, int(s1), 0)

            if hasattr(self, "paned_v") and self._saved_v_sash is not None:
                sv = self._saved_v_sash
                if 80 < sv < (win_h - 60):
                    self.paned_v.sash_place(0, 0, int(sv))
        except Exception as e:
            print(f"Aviso ao restaurar posições dos separadores: {e}")

    def _save_config(self):
        """Salva as configurações atuais no config.json incluindo geometria, estado e barras divisórias."""
        try:
            is_zoomed = False
            try:
                is_zoomed = (self.root.state() == "zoomed")
            except Exception:
                pass

            geom_to_save = self.root.geometry()
            if is_zoomed and self._last_normal_geometry:
                geom_to_save = self._last_normal_geometry

            h_sashes = []
            if hasattr(self, "paned_main"):
                try:
                    h_sashes = [self.paned_main.sash_coord(0)[0], self.paned_main.sash_coord(1)[0]]
                except Exception:
                    pass

            v_sash = None
            if hasattr(self, "paned_v"):
                try:
                    v_sash = self.paned_v.sash_coord(0)[1]
                except Exception:
                    pass

            cfg = {
                "source_type": self.var_source_type.get(),
                "source_dir": self.var_source_dir.get().strip(),
                "recent_source_paths": self.recent_source_paths,
                "orig_view_mode": self.var_orig_view.get(),
                "dest_view_mode": self.var_dest_view.get(),
                "recent_paths": self.recent_paths,
                "dest_dir": self.var_dest_dir.get().strip(),
                "custom_local": "",  # Etiqueta temporária intencionalmente não persistida
                "use_gps": self.var_use_gps.get(),
                "skip_existing": self.var_skip_existing.get(),
                "inc_photos": self.var_inc_photos.get(),
                "inc_videos": self.var_inc_videos.get(),
                "play_sound": self.var_play_sound.get(),
                "filter_by_date": self.var_filter_by_date.get(),
                "date_from": self.var_date_from.get().strip(),
                "date_to": self.var_date_to.get().strip(),
                "window_geometry": geom_to_save,
                "window_state": "zoomed" if is_zoomed else "normal",
                "paned_h_sashes": h_sashes,
                "paned_v_sash": v_sash
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Erro ao salvar configurações: {e}")

    def _play_sound_notification(self):
        """Reproduz um som suave de conclusão se a opção estiver ativada."""
        if not self.var_play_sound.get():
            return
        def sound_thread():
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        threading.Thread(target=sound_thread, daemon=True).start()

    def _on_close(self):
        """Manipulador de fechamento de janela para salvar configurações e encerrar."""
        if hasattr(self, "_set_transfer_anim_active"):
            self._set_transfer_anim_active(False)
        self._save_config()
        self.root.destroy()

    def _build_filezilla_ui(self):
        """Constrói a interface dual-pane estilo FileZilla com toolbar e abas."""
        # 1. Barra de Conexão Rápida / Seleção de Origem (Topo)
        bar_quick = tk.Frame(self.root, bg="#f0f0f0", relief=tk.RAISED, bd=1, padx=6, pady=4)
        bar_quick.pack(fill=tk.X, side=tk.TOP)

        tk.Label(bar_quick, text="Origem:", bg="#f0f0f0", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.cb_source_type = ttk.Combobox(
            bar_quick,
            textvariable=self.var_source_type,
            values=["📱 Apple iPhone (USB)", "📁 Pasta / Disco Local"],
            state="readonly",
            width=22
        )
        self.cb_source_type.pack(side=tk.LEFT, padx=4)
        self.cb_source_type.bind("<<ComboboxSelected>>", lambda e: self._on_source_type_changed())

        # Subframe 1: iPhone (exibido na barra superior quando a origem for o iPhone)
        self.f_src_iphone = tk.Frame(bar_quick, bg="#f0f0f0")
        self.lbl_device = tk.Label(self.f_src_iphone, textvariable=self.var_device_status, bg="#f0f0f0", fg="#d9534f", font=("Segoe UI", 9, "bold"))
        self.lbl_device.pack(side=tk.LEFT, padx=6)
        self.btn_reconnect_iphone = ttk.Button(
            self.f_src_iphone,
            text="🔌 Conectar / Reconectar",
            command=self._manual_reconnect_iphone
        )
        self.btn_reconnect_iphone.pack(side=tk.LEFT, padx=4)

        if self.var_source_type.get() != "📁 Pasta / Disco Local":
            self.f_src_iphone.pack(side=tk.LEFT, padx=2)

        ttk.Separator(bar_quick, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        tk.Label(bar_quick, text="Mês/Pasta:", bg="#f0f0f0", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.cb_months = ttk.Combobox(bar_quick, textvariable=self.var_folder_filter, state="readonly", width=22)
        self.cb_months.pack(side=tk.LEFT, padx=4)
        self.cb_months.bind("<<ComboboxSelected>>", lambda e: self._on_folder_select())

        ttk.Button(bar_quick, text="📅 Filtros Avançados", command=self._open_filter_dialog).pack(side=tk.LEFT, padx=4)

        tk.Label(bar_quick, text="Filtro Rápido:", bg="#f0f0f0", font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(10, 2))
        e_filter = ttk.Entry(bar_quick, textvariable=self.var_filter_text, width=14)
        e_filter.pack(side=tk.LEFT, padx=2)
        e_filter.bind("<KeyRelease>", lambda e: self._apply_quick_filter())

        # 2. Barra de Ferramentas Principal (Toolbar de Ações FileZilla)
        toolbar = tk.Frame(self.root, bg="#e8ecef", relief=tk.RAISED, bd=1, padx=6, pady=5)
        toolbar.pack(fill=tk.X, side=tk.TOP)

        # Botão Baixar (Destaque Fundo Verde Vivo)
        self.btn_download = tk.Button(
            toolbar,
            text=" ⬇️ BAIXAR SELECIONADOS PARA O PC ",
            bg="#198754",
            fg="#ffffff",
            activebackground="#20c997",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.RAISED,
            bd=3,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._start_download_selected
        )
        self.btn_download.pack(side=tk.LEFT, padx=4)

        # Botão Excluir do iPhone (Destaque Fundo Vermelho Vivo Realçado)
        self.btn_delete = tk.Button(
            toolbar,
            text=" 🗑️ EXCLUIR SELECIONADOS DO IPHONE ",
            bg="#cc0000",
            fg="#ffffff",
            activebackground="#ff1a1a",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.RAISED,
            bd=3,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self._confirm_delete_selected
        )
        self.btn_delete.pack(side=tk.LEFT, padx=4)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # Opções de pasta destino
        tk.Label(toolbar, text="Etiqueta (opcional):", bg="#e8ecef", font=("Segoe UI", 8)).pack(side=tk.LEFT)
        ttk.Entry(toolbar, textvariable=self.var_custom_local, width=12).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(toolbar, text="GPS Automático", variable=self.var_use_gps, command=self._save_config).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(toolbar, text="Pular Existentes", variable=self.var_skip_existing, command=self._save_config).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(toolbar, text="🔔 Som ao Concluir", variable=self.var_play_sound, command=self._save_config).pack(side=tk.LEFT, padx=6)

        self.btn_cancel = ttk.Button(toolbar, text="⛔ Cancelar", state=tk.DISABLED, command=self._cancel_task)
        self.btn_cancel.pack(side=tk.RIGHT, padx=4)
        self.btn_pause = ttk.Button(toolbar, text="⏸️ Pausar", state=tk.DISABLED, command=self._toggle_pause_task)
        self.btn_pause.pack(side=tk.RIGHT, padx=2)

        # 3. Barra de Status e Progresso Rica no Rodapé (Barra Total e Barra por Arquivo)
        f_foot = tk.Frame(self.root, bg="#f0f0f0", relief=tk.RAISED, bd=1, padx=6, pady=3)
        f_foot.pack(fill=tk.X, side=tk.BOTTOM)

        # 3.1 Linha do Arquivo Atual: Nome/Detalhes + Barra do Arquivo + %
        f_foot_file_top = tk.Frame(f_foot, bg="#f0f0f0")
        f_foot_file_top.pack(fill=tk.X, pady=(1, 1))

        tk.Label(f_foot_file_top, text="Arquivo:", bg="#f0f0f0", font=("Segoe UI", 8, "bold"), fg="#495057").pack(side=tk.LEFT)
        self.lbl_file_status = tk.Label(f_foot_file_top, textvariable=self.var_file_status, bg="#f0f0f0", font=("Segoe UI", 8), anchor=tk.W)
        self.lbl_file_status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        f_foot_file_bar = tk.Frame(f_foot, bg="#f0f0f0")
        f_foot_file_bar.pack(fill=tk.X, pady=(0, 2))

        self.pbar_file = ttk.Progressbar(f_foot_file_bar, variable=self.var_file_progress_val, maximum=100)
        self.pbar_file.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.lbl_file_pct = tk.Label(
            f_foot_file_bar, textvariable=self.var_file_pct_label, bg="#f0f0f0",
            font=("Consolas", 8, "bold"), fg="#0275d8", width=7, anchor=tk.E
        )
        self.lbl_file_pct.pack(side=tk.LEFT)

        # 3.2 Linha do Progresso Total: Status do Lote + Barra Total + % + Versão
        f_foot_top = tk.Frame(f_foot, bg="#f0f0f0")
        f_foot_top.pack(fill=tk.X, pady=(2, 1))

        tk.Label(f_foot_top, text="Total:", bg="#f0f0f0", font=("Segoe UI", 8, "bold"), fg="#495057").pack(side=tk.LEFT)
        self.lbl_status_msg = tk.Label(f_foot_top, textvariable=self.var_status_msg, bg="#f0f0f0", font=("Segoe UI", 8), anchor=tk.W)
        self.lbl_status_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.lbl_progress_stats = tk.Label(
            f_foot_top, textvariable=self.var_progress_stats, bg="#f0f0f0",
            font=("Segoe UI", 8, "bold"), fg="#0275d8", anchor=tk.E
        )
        self.lbl_progress_stats.pack(side=tk.RIGHT)

        f_foot_bar = tk.Frame(f_foot, bg="#f0f0f0")
        f_foot_bar.pack(fill=tk.X, pady=(0, 1))

        self.pbar_total = ttk.Progressbar(f_foot_bar, variable=self.var_progress_val, maximum=100)
        self.pbar_total.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.pbar = self.pbar_total  # Retrocompatibilidade

        self.lbl_pct = tk.Label(
            f_foot_bar, textvariable=self.var_pct_label, bg="#f0f0f0",
            font=("Consolas", 9, "bold"), fg="#28a745", width=7, anchor=tk.E
        )
        self.lbl_pct.pack(side=tk.LEFT)

        self.lbl_version = tk.Label(
            f_foot_bar, text=f" {APP_VERSION} ", bg="#e4e7ea", fg="#495057",
            font=("Segoe UI", 8, "bold"), relief=tk.SOLID, bd=1
        )
        self.lbl_version.pack(side=tk.RIGHT, padx=(6, 0))

        # 4. Divisória Vertical Principal (Divide área de trabalho superior das abas inferiores)
        self.paned_v = tk.PanedWindow(self.root, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=4, bg="#d0d0d0")
        self.paned_v.pack(fill=tk.BOTH, expand=True, side=tk.TOP, padx=4, pady=(2, 4))

        # 4.1 Painel Triplo Horizontal (PanedWindow com 3 Colunas: Origem | Preview & Vídeo | PC Local)
        self.paned_main = tk.PanedWindow(self.paned_v, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=4, bg="#d0d0d0")
        self.paned_v.add(self.paned_main, minsize=320)

        # 4.1.1 Painel Esquerdo: Origem (iPhone ou Pasta Local)
        self.pane_iphone = ttk.LabelFrame(self.paned_main, text=" 📱 Apple iPhone (Armazenamento Remoto USB) ", padding="4")
        self.paned_main.add(self.pane_iphone, minsize=400, width=540)

        # Barra de caminho de origem local com histórico estilo FileZilla (Posicionada acima da janela de arquivos, igual ao destino)
        self.f_orig_path = ttk.Frame(self.pane_iphone)
        ttk.Label(self.f_orig_path, text="Caminho:", font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.cb_source_dir = ttk.Combobox(
            self.f_orig_path,
            textvariable=self.var_source_dir,
            values=self.recent_source_paths,
            font=("Segoe UI", 8)
        )
        self.cb_source_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.cb_source_dir.bind("<<ComboboxSelected>>", lambda e: self._on_source_folder_selected())
        self.cb_source_dir.bind("<Return>", lambda e: self._on_source_folder_entered())
        ttk.Button(self.f_orig_path, text="...", width=3, command=self._browse_source_dir).pack(side=tk.RIGHT)
        ttk.Button(self.f_orig_path, text="📂", width=3, command=self._open_source_in_explorer).pack(side=tk.RIGHT, padx=2)

        # Controles superiores do painel Origem (Modo de Exibição e Atualizar)
        self.f_ip_ctrl = ttk.Frame(self.pane_iphone)
        self.f_ip_ctrl.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.f_ip_ctrl, text="Exibição:", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(2, 4))
        self.cb_orig_view = ttk.Combobox(
            self.f_ip_ctrl,
            textvariable=self.var_orig_view,
            values=VIEW_MODES,
            state="readonly",
            width=20,
            font=("Segoe UI", 8)
        )
        self.cb_orig_view.pack(side=tk.LEFT)
        self.cb_orig_view.bind("<<ComboboxSelected>>", lambda e: self._on_orig_view_changed())

        self.btn_refresh_orig = ttk.Button(self.f_ip_ctrl, text="🔄 Atualizar", command=self._refresh_orig_view)
        self.btn_refresh_orig.pack(side=tk.RIGHT, padx=2)

        self.lbl_orig_top_sel = ttk.Label(
            self.f_ip_ctrl,
            textvariable=self.var_orig_sel_size,
            font=("Segoe UI", 8, "bold"),
            foreground="#0369a1"
        )
        self.lbl_orig_top_sel.pack(side=tk.RIGHT, padx=(4, 8))

        # Exibe a barra de caminho de origem se o modo inicial for Pasta / Disco Local
        if self.var_source_type.get() == "📁 Pasta / Disco Local":
            self.f_orig_path.pack(fill=tk.X, pady=(0, 4), before=self.f_ip_ctrl)

        # Barra de Ações e Rodapé na base do painel de arquivos (Marcar / Desmarcar e Tamanho Selecionado)
        f_ip_bottom = tk.Frame(self.pane_iphone, bg="#f5f7fa", relief=tk.SOLID, bd=1, padx=4, pady=3)
        f_ip_bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

        ttk.Button(f_ip_bottom, text="☑ Marcar Todos", command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(f_ip_bottom, text="☐ Desmarcar", command=self._deselect_all).pack(side=tk.LEFT, padx=2)

        self.lbl_orig_bottom_sel = ttk.Label(
            f_ip_bottom,
            textvariable=self.var_orig_sel_size,
            font=("Segoe UI", 8, "bold"),
            foreground="#0369a1",
            background="#f5f7fa"
        )
        self.lbl_orig_bottom_sel.pack(side=tk.RIGHT, padx=4)

        self.lbl_orig_summary = ttk.Label(
            f_ip_bottom,
            textvariable=self.var_summary_iphone,
            font=("Segoe UI", 8),
            background="#f5f7fa"
        )
        self.lbl_orig_summary.pack(side=tk.RIGHT, padx=(4, 8))

        # Container de Conteúdo da Origem (Tabela ou Grid de Miniaturas)
        self.f_orig_content = ttk.Frame(self.pane_iphone)
        self.f_orig_content.pack(fill=tk.BOTH, expand=True)

        # Tela / Overlay de Animação de Carregamento na área em branco
        self.f_orig_loading = tk.Frame(self.f_orig_content, bg="#f8f9fa")
        self._setup_loading_overlay()

        # Modo 1: Tabela de Arquivos (Detalhes / Lista)
        self.f_ip_table = ttk.Frame(self.f_orig_content)

        cols_ip = ("check", "name", "type", "date", "time", "size", "folder")
        self.tree_iphone = ttk.Treeview(self.f_ip_table, columns=cols_ip, show="headings", selectmode="extended")
        self.tree_iphone.heading("check", text="Sel", command=lambda: self._sort_orig_by_column("check"))
        self.tree_iphone.heading("name", text="Arquivo", command=lambda: self._sort_orig_by_column("name"))
        self.tree_iphone.heading("type", text="Tipo", command=lambda: self._sort_orig_by_column("type"))
        self.tree_iphone.heading("date", text="Data", command=lambda: self._sort_orig_by_column("date"))
        self.tree_iphone.heading("time", text="Hora", command=lambda: self._sort_orig_by_column("time"))
        self.tree_iphone.heading("size", text="Tamanho", command=lambda: self._sort_orig_by_column("size"))
        self.tree_iphone.heading("folder", text="Pasta Origem", command=lambda: self._sort_orig_by_column("folder"))

        self.tree_iphone.column("check", width=45, anchor=tk.CENTER)
        self.tree_iphone.column("name", width=170, anchor=tk.W)
        self.tree_iphone.column("type", width=55, anchor=tk.CENTER)
        self.tree_iphone.column("date", width=95, anchor=tk.CENTER)
        self.tree_iphone.column("time", width=60, anchor=tk.CENTER)
        self.tree_iphone.column("size", width=80, anchor=tk.E)
        self.tree_iphone.column("folder", width=90, anchor=tk.W)

        sb_ip_y = ttk.Scrollbar(self.f_ip_table, orient=tk.VERTICAL, command=self.tree_iphone.yview)
        self.tree_iphone.configure(yscrollcommand=sb_ip_y.set)
        self.tree_iphone.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_ip_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree_iphone.bind("<Button-1>", self._on_iphone_click)
        self.tree_iphone.bind("<<TreeviewSelect>>", self._on_iphone_select_changed)
        self.tree_iphone.bind("<Double-1>", self._on_iphone_double_click)
        self.tree_iphone.bind("<space>", lambda e: self._toggle_selected_rows())
        self.tree_iphone.bind("<Delete>", lambda e: self._confirm_delete_selected())

        # Modo 2: Grade de Miniaturas (Miniaturas / Miniaturas Gigantes)
        self.f_ip_grid = ttk.Frame(self.f_orig_content)
        self.cv_orig_grid = tk.Canvas(self.f_ip_grid, bg="#1e1e1e", highlightthickness=0)
        self.sb_ip_grid_y = ttk.Scrollbar(self.f_ip_grid, orient=tk.VERTICAL, command=self.cv_orig_grid.yview)
        self.cv_orig_grid.configure(yscrollcommand=self.sb_ip_grid_y.set)
        self.sb_ip_grid_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.cv_orig_grid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner_grid_orig = tk.Frame(self.cv_orig_grid, bg="#1e1e1e")
        self.cv_orig_window = self.cv_orig_grid.create_window((0, 0), window=self.inner_grid_orig, anchor="nw")

        self.inner_grid_orig.bind("<Configure>", lambda e: self._on_orig_inner_configure())
        self.cv_orig_grid.bind("<Configure>", self._on_orig_canvas_configure)
        self.cv_orig_grid.bind("<MouseWheel>", self._on_orig_mousewheel)
        self.inner_grid_orig.bind("<MouseWheel>", self._on_orig_mousewheel)

        # 3.2 Painel Central: Miniatura / Pré-visualização & Inspetor
        pane_preview = ttk.LabelFrame(self.paned_main, text=" 🖼️ Pré-visualização & Inspetor ", padding="6")
        self.paned_main.add(pane_preview, minsize=230, width=250)

        # Moldura da miniatura
        self.f_thumb_box = tk.Frame(pane_preview, bg="#202020", width=220, height=220, relief=tk.SUNKEN, bd=2)
        self.f_thumb_box.pack(pady=4)
        self.f_thumb_box.pack_propagate(False)

        self.lbl_thumb = tk.Label(self.f_thumb_box, text="Selecione um item\npara ver a miniatura", bg="#202020", fg="#888888", font=("Segoe UI", 9))
        self.lbl_thumb.pack(fill=tk.BOTH, expand=True)

        # Inspetor de Metadados
        f_meta = ttk.Frame(pane_preview)
        f_meta.pack(fill=tk.X, pady=6)

        ttk.Label(f_meta, text="Arquivo:", font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(f_meta, textvariable=self.var_prev_name, font=("Segoe UI", 8)).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(f_meta, text="Data:", font=("Segoe UI", 8, "bold")).grid(row=1, column=0, sticky=tk.W)
        ttk.Label(f_meta, textvariable=self.var_prev_date, font=("Segoe UI", 8)).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(f_meta, text="Tamanho:", font=("Segoe UI", 8, "bold")).grid(row=2, column=0, sticky=tk.W)
        ttk.Label(f_meta, textvariable=self.var_prev_size, font=("Segoe UI", 8)).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(f_meta, text="Local GPS:", font=("Segoe UI", 8, "bold")).grid(row=3, column=0, sticky=tk.W)
        ttk.Label(f_meta, textvariable=self.var_prev_loc, font=("Segoe UI", 8, "italic"), foreground="#0275d8").grid(row=3, column=1, sticky=tk.W)

        # Ações Rápidas no Preview
        f_prev_btns = ttk.Frame(pane_preview)
        f_prev_btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(f_prev_btns, text="⬇️ Baixar Este", command=self._download_single_selected).pack(fill=tk.X, pady=2)
        self.btn_prev_delete = tk.Button(
            f_prev_btns,
            text="🗑️ Excluir Este do iPhone",
            bg="#cc0000",
            fg="#ffffff",
            activebackground="#ff1a1a",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.RAISED,
            bd=2,
            pady=3,
            cursor="hand2",
            command=self._delete_single_selected
        )
        self.btn_prev_delete.pack(fill=tk.X, pady=2)

        # 4.1.2 Área Central: Monitor de Vídeo Animado da Transferência (gemini_generated_video_7b48f753.mp4)
        self.f_data_flow = tk.LabelFrame(
            pane_preview,
            text=" ⚡ Transferência de Arquivos ",
            font=("Segoe UI", 8, "bold"),
            bg="#111827",
            fg="#9ca3af",
            padx=4,
            pady=4
        )
        self.f_data_flow.pack(fill=tk.BOTH, expand=True, pady=(8, 2))

        self.cv_video = tk.Canvas(
            self.f_data_flow,
            bg="#111827",
            highlightthickness=0
        )
        self.cv_video.pack(fill=tk.BOTH, expand=True)
        self.cv_bits = self.cv_video  # Aliasing para compatibilidade
        self._init_video_anim()
        self.cv_video.bind("<Configure>", lambda e: self._on_video_canvas_configure())

        # 4.1.3 Painel Direito: PC Local (Destino)
        pane_local = ttk.LabelFrame(self.paned_main, text=" 💻 Meu Computador (Destino Local) ", padding="4")
        self.paned_main.add(pane_local, minsize=350, width=420)

        # Barra de caminho local com histórico estilo FileZilla (Combobox)
        f_loc_path = ttk.Frame(pane_local)
        f_loc_path.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(f_loc_path, text="Caminho:", font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.cb_dest_dir = ttk.Combobox(f_loc_path, textvariable=self.var_dest_dir, values=self.recent_paths, font=("Segoe UI", 8))
        self.cb_dest_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.cb_dest_dir.bind("<<ComboboxSelected>>", lambda e: self._on_recent_path_selected())
        self.cb_dest_dir.bind("<Return>", lambda e: self._on_path_entered())
        ttk.Button(f_loc_path, text="...", width=3, command=self._browse_dest_dir).pack(side=tk.RIGHT)
        ttk.Button(f_loc_path, text="📂", width=3, command=self._open_local_in_explorer).pack(side=tk.RIGHT, padx=2)

        # Controles superiores do painel Destino (Modo de Exibição e Atualizar)
        f_loc_ctrl = ttk.Frame(pane_local)
        f_loc_ctrl.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(f_loc_ctrl, text="Exibição:", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(2, 4))
        self.cb_dest_view = ttk.Combobox(
            f_loc_ctrl,
            textvariable=self.var_dest_view,
            values=VIEW_MODES,
            state="readonly",
            width=20,
            font=("Segoe UI", 8)
        )
        self.cb_dest_view.pack(side=tk.LEFT)
        self.cb_dest_view.bind("<<ComboboxSelected>>", lambda e: self._on_dest_view_changed())

        self.btn_refresh_dest = ttk.Button(f_loc_ctrl, text="🔄 Atualizar", command=self._refresh_local_view)
        self.btn_refresh_dest.pack(side=tk.RIGHT, padx=2)

        # Container de Conteúdo do Destino (Tabela ou Grid de Miniaturas)
        self.f_dest_content = ttk.Frame(pane_local)
        self.f_dest_content.pack(fill=tk.BOTH, expand=True)

        # Modo 1: Tabela de Arquivos Locais (Detalhes / Lista)
        self.f_loc_table = ttk.Frame(self.f_dest_content)

        cols_loc = ("name", "size", "date")
        self.tree_local = ttk.Treeview(self.f_loc_table, columns=cols_loc, show="tree headings", selectmode="browse")
        self.tree_local.heading("#0", text="Pastas AAAA-MM-DD[-Local]", command=lambda: self._sort_dest_by_column("#0"))
        self.tree_local.heading("name", text="Arquivo", command=lambda: self._sort_dest_by_column("name"))
        self.tree_local.heading("size", text="Tamanho", command=lambda: self._sort_dest_by_column("size"))
        self.tree_local.heading("date", text="Data Modificação", command=lambda: self._sort_dest_by_column("date"))

        self.tree_local.column("#0", width=160, anchor=tk.W)
        self.tree_local.column("name", width=110, anchor=tk.W)
        self.tree_local.column("size", width=70, anchor=tk.E)
        self.tree_local.column("date", width=110, anchor=tk.CENTER)

        sb_loc_y = ttk.Scrollbar(self.f_loc_table, orient=tk.VERTICAL, command=self.tree_local.yview)
        self.tree_local.configure(yscrollcommand=sb_loc_y.set)
        self.tree_local.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_loc_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree_local.bind("<<TreeviewSelect>>", self._on_local_select_changed)
        self.tree_local.bind("<Double-1>", self._on_local_double_click)

        # Modo 2: Grade de Miniaturas Locais (Miniaturas / Miniaturas Gigantes)
        self.f_loc_grid = ttk.Frame(self.f_dest_content)
        self.cv_dest_grid = tk.Canvas(self.f_loc_grid, bg="#1e1e1e", highlightthickness=0)
        self.sb_loc_grid_y = ttk.Scrollbar(self.f_loc_grid, orient=tk.VERTICAL, command=self.cv_dest_grid.yview)
        self.cv_dest_grid.configure(yscrollcommand=self.sb_loc_grid_y.set)
        self.sb_loc_grid_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.cv_dest_grid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner_grid_dest = tk.Frame(self.cv_dest_grid, bg="#1e1e1e")
        self.cv_dest_window = self.cv_dest_grid.create_window((0, 0), window=self.inner_grid_dest, anchor="nw")

        self.inner_grid_dest.bind("<Configure>", lambda e: self._on_dest_inner_configure())
        self.cv_dest_grid.bind("<Configure>", self._on_dest_canvas_configure)
        self.cv_dest_grid.bind("<MouseWheel>", self._on_dest_mousewheel)
        self.inner_grid_dest.bind("<MouseWheel>", self._on_dest_mousewheel)

        # Rodapé do painel Destino (com resumo de arquivos e espaço em disco restante)
        f_loc_status = ttk.Frame(pane_local)
        f_loc_status.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(f_loc_status, textvariable=self.var_summary_local, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.lbl_dest_disk_free = ttk.Label(
            f_loc_status,
            textvariable=self.var_dest_disk_free,
            font=("Segoe UI", 8, "bold"),
            foreground="#16a34a"
        )
        self.lbl_dest_disk_free.pack(side=tk.RIGHT, padx=(4, 2))

        # 4.2 Painel Inferior (Abas de Transferência, Fila e Console)
        self.f_bottom = ttk.Frame(self.paned_v, height=160)
        self.paned_v.add(self.f_bottom, minsize=80)

        self.nb_bottom = ttk.Notebook(self.f_bottom)
        self.nb_bottom.pack(fill=tk.BOTH, expand=True)

        # Aba 1: Fila de Transferência
        self.f_queue = ttk.Frame(self.nb_bottom)
        self.nb_bottom.add(self.f_queue, text=" Fila de Transferência (0) ")
        self.tree_queue = ttk.Treeview(self.f_queue, columns=("file", "size", "src", "dest", "status"), show="headings", height=5)
        self.tree_queue.heading("file", text="Arquivo")
        self.tree_queue.heading("size", text="Tamanho")
        self.tree_queue.heading("src", text="Origem (iPhone)")
        self.tree_queue.heading("dest", text="Destino (PC)")
        self.tree_queue.heading("status", text="Status")
        self.tree_queue.pack(fill=tk.BOTH, expand=True)

        # Aba 2: Transferências Concluídas
        self.f_done = ttk.Frame(self.nb_bottom)
        self.nb_bottom.add(self.f_done, text=" Concluídos (0) ")
        self.tree_done = ttk.Treeview(self.f_done, columns=("file", "size", "dest", "time"), show="headings", height=5)
        self.tree_done.heading("file", text="Arquivo")
        self.tree_done.heading("size", text="Tamanho")
        self.tree_done.heading("dest", text="Pasta Destino")
        self.tree_done.heading("time", text="Horário")
        self.tree_done.pack(fill=tk.BOTH, expand=True)

        # Aba 3: Falhas e Pulados
        self.f_failed = ttk.Frame(self.nb_bottom)
        self.nb_bottom.add(self.f_failed, text=" Pulados / Falhas (0) ")
        self.tree_failed = ttk.Treeview(self.f_failed, columns=("file", "status", "reason"), show="headings", height=5)
        self.tree_failed.heading("file", text="Arquivo")
        self.tree_failed.heading("status", text="Tipo")
        self.tree_failed.heading("reason", text="Motivo / Detalhes")
        self.tree_failed.pack(fill=tk.BOTH, expand=True)

        # Aba 4: Console Log Estilo FileZilla
        self.f_console = ttk.Frame(self.nb_bottom)
        self.nb_bottom.add(self.f_console, text=" Log do Console ")
        self.txt_console = tk.Text(self.f_console, height=5, font=("Consolas", 8), bg="#1e1e1e", fg="#dcdcdc")
        self.txt_console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_console = ttk.Scrollbar(self.f_console, orient=tk.VERTICAL, command=self.txt_console.yview)
        self.txt_console.configure(yscrollcommand=sb_console.set)
        sb_console.pack(side=tk.RIGHT, fill=tk.Y)

    def _log_console(self, msg: str, prefix: str = "Status:"):
        t_str = datetime.now().strftime("%H:%M:%S")
        line = f"{t_str} {prefix} {msg}\n"
        def append():
            try:
                if hasattr(self, "txt_console") and self.txt_console.winfo_exists():
                    self.txt_console.insert(tk.END, line)
                    self.txt_console.see(tk.END)
            except Exception:
                pass
        self._safe_call(append)

    def _on_source_type_changed(self):
        self._clear_orig_list("Alternando origem de mídias...")
        self._redraw_data_flow()
        stype = self.var_source_type.get()
        if stype == "📁 Pasta / Disco Local":
            self.var_folder_filter.set("Todos os Meses")
            self.cb_months["values"] = ["Todos os Meses"]
            self.f_src_iphone.pack_forget()
            if hasattr(self, "f_orig_path") and hasattr(self, "f_ip_ctrl"):
                self.f_orig_path.pack(fill=tk.X, pady=(0, 4), before=self.f_ip_ctrl)
            if hasattr(self, "pane_iphone"):
                self.pane_iphone.config(text=" 📁 Pasta de Origem (Fotos e Vídeos Locais) ")
            self.btn_download.config(text=" ⬇️ BAIXAR / ORGANIZAR SELECIONADOS ")
            self.btn_delete.config(text=" 🗑️ EXCLUIR SELECIONADOS DA ORIGEM ")
            if hasattr(self, "btn_prev_delete"):
                self.btn_prev_delete.config(text="🗑️ Excluir da Origem")

            src = self.var_source_dir.get().strip()
            if src and os.path.exists(src):
                self._start_scan_async()
            else:
                self._on_scan_done([])
        else:
            self.var_folder_filter.set("Todas as Pastas")
            self.cb_months["values"] = ["Todas as Pastas"]
            if hasattr(self, "f_orig_path"):
                self.f_orig_path.pack_forget()
            self.f_src_iphone.pack(side=tk.LEFT, padx=2)
            if hasattr(self, "pane_iphone"):
                self.pane_iphone.config(text=" 📱 Apple iPhone (Armazenamento Remoto USB) ")
            self.btn_download.config(text=" ⬇️ BAIXAR SELECIONADOS PARA O PC ")
            self.btn_delete.config(text=" 🗑️ EXCLUIR SELECIONADOS DO IPHONE ")
            if hasattr(self, "btn_prev_delete"):
                self.btn_prev_delete.config(text="🗑️ Excluir Este do iPhone")

            if not self.manager.is_connected():
                self._auto_connect_async()
            else:
                self._start_scan_async()

        self._save_config()

    def _on_source_folder_selected(self):
        p = self.var_source_dir.get().strip()
        if p and os.path.exists(p):
            self.var_folder_filter.set("Todos os Meses")
            self._add_recent_source_path(p)
            self._start_scan_async()

    def _on_source_folder_entered(self):
        p = self.var_source_dir.get().strip()
        if p and os.path.exists(p):
            self.var_folder_filter.set("Todos os Meses")
            self._add_recent_source_path(p)
            self._start_scan_async()

    def _add_recent_source_path(self, path: str):
        p_clean = path.strip()
        if not p_clean:
            return
        if p_clean in self.recent_source_paths:
            self.recent_source_paths.remove(p_clean)
        self.recent_source_paths.insert(0, p_clean)
        self.recent_source_paths = self.recent_source_paths[:12]
        if hasattr(self, "cb_source_dir"):
            self.cb_source_dir["values"] = self.recent_source_paths
        self._save_config()

    def _browse_source_dir(self):
        init = self.var_source_dir.get() or self.var_dest_dir.get()
        chosen = filedialog.askdirectory(initialdir=init, title="Selecione o Diretório de Origem (Fotos/Vídeos)")
        if chosen:
            self.var_source_dir.set(chosen)
            self.var_folder_filter.set("Todos os Meses")
            self._add_recent_source_path(chosen)
            self._start_scan_async()

    def _open_source_in_explorer(self):
        src = self.var_source_dir.get().strip()
        if os.path.exists(src):
            os.startfile(src)
        else:
            messagebox.showinfo("Aviso", f"A pasta de origem informada não existe:\n{src}")

    def _update_months_combo(self, values: List[str]):
        cur = self.var_folder_filter.get()
        self.cb_months["values"] = values
        if cur in values:
            self.var_folder_filter.set(cur)
        elif len(values) > 1:
            self.cb_months.current(0)
        elif values:
            self.cb_months.current(0)

    # --- Animação de Vídeo na Área Central Exclusiva para Transferência em Andamento ---
    def _init_video_anim(self):
        """Inicializa o monitor de vídeo da área central (gemini_generated_video_7b48f753.mp4)."""
        self._is_transferring = False
        self._transfer_speed_str = ""
        self._video_cap = None
        self._video_after_id = None
        self._video_photo = None
        self._current_video_path = None
        self.root.after(50, self._draw_standby_canvas)

    def _get_available_anim_videos(self) -> List[Path]:
        """Retorna todos os vídeos disponíveis na pasta 'anim' ou na raiz."""
        videos = []
        if ANIM_DIR.exists():
            videos.extend([p for p in ANIM_DIR.glob("*") if p.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv") and p.is_file()])
        if not videos and VIDEO_PATH.exists():
            videos.append(VIDEO_PATH)
        return videos

    def _switch_to_next_anim_video(self):
        """Alterna aleatoriamente para outro vídeo da pasta anim (sem repetir o mesmo se houver alternativas)."""
        videos = self._get_available_anim_videos()
        if not videos:
            if self._video_cap:
                self._video_cap.release()
                self._video_cap = None
            return

        if len(videos) > 1 and getattr(self, "_current_video_path", None) in videos:
            candidates = [v for v in videos if v != self._current_video_path]
            next_vid = random.choice(candidates)
        else:
            next_vid = random.choice(videos)

        self._current_video_path = next_vid
        try:
            if self._video_cap is not None:
                self._video_cap.release()
            self._video_cap = cv2.VideoCapture(str(next_vid))
            self._video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        except Exception as e:
            print(f"Erro ao carregar vídeo animado {next_vid}: {e}")
            self._video_cap = None

    def _on_video_canvas_configure(self):
        """Redesenha o standby ao redimensionar se a transferência não estiver ativa."""
        if not self._is_transferring:
            self._draw_standby_canvas()

    def _draw_standby_canvas(self):
        """Desenha a tela de repouso no canvas central quando não há cópia ativa (0% de CPU)."""
        if not hasattr(self, "cv_video") or not self.cv_video.winfo_exists():
            return
        w = max(10, self.cv_video.winfo_width())
        h = max(10, self.cv_video.winfo_height())
        if w < 30 or h < 30:
            return

        self.cv_video.delete("all")

        # Moldura sutil tracejada central
        pad_x = min(25, w // 8)
        pad_y = min(18, h // 8)
        self.cv_video.create_rectangle(
            pad_x, pad_y, w - pad_x, h - pad_y,
            outline="#1f2937", width=1, dash=(3, 3)
        )
        cy = h // 2
        self.cv_video.create_text(
            w // 2, cy - 10,
            text="⚡ Transferência Pronta",
            fill="#9ca3af",
            font=("Segoe UI", 9, "bold")
        )
        self.cv_video.create_text(
            w // 2, cy + 12,
            text="Aguardando início da cópia...",
            fill="#6b7280",
            font=("Segoe UI", 8)
        )

    def _set_transfer_anim_active(self, active: bool):
        """Ativa a reprodução aleatória alternada dos vídeos da pasta 'anim' exclusivamente durante a cópia."""
        self._is_transferring = active
        if active:
            self._switch_to_next_anim_video()
            if self._video_after_id:
                try:
                    self.root.after_cancel(self._video_after_id)
                except Exception:
                    pass
                self._video_after_id = None
            self._render_video_frame()
        else:
            self._transfer_speed_str = ""
            if self._video_after_id:
                try:
                    self.root.after_cancel(self._video_after_id)
                except Exception:
                    pass
                self._video_after_id = None
            if self._video_cap:
                try:
                    self._video_cap.release()
                except Exception:
                    pass
                self._video_cap = None
            self._video_photo = None
            self._draw_standby_canvas()

    def _render_video_frame(self):
        """Renderiza cada frame do vídeo alternando aleatoriamente entre vídeos da pasta 'anim' ao término de cada um."""
        if not self._is_transferring:
            self._draw_standby_canvas()
            return

        if not hasattr(self, "cv_video") or not self.cv_video.winfo_exists():
            return

        if self._video_cap is None or not self._video_cap.isOpened():
            # Tenta carregar o próximo vídeo da pasta anim ou exibe fallback
            self._switch_to_next_anim_video()
            if self._video_cap is None or not self._video_cap.isOpened():
                self.cv_video.delete("all")
                w = max(10, self.cv_video.winfo_width())
                h = max(10, self.cv_video.winfo_height())
                spd = self._transfer_speed_str or "Transferindo mídias..."
                self.cv_video.create_text(w // 2, h // 2, text=f"⚡ {spd}", fill="#38bdf8", font=("Segoe UI", 9, "bold"))
                self._video_after_id = self.root.after(100, self._render_video_frame)
                return

        if hasattr(self, "pause_event") and self.pause_event.is_set():
            # Processo pausado: congela o vídeo e exibe telemetria de pausa
            w = max(10, self.cv_video.winfo_width())
            h = max(10, self.cv_video.winfo_height())
            if w > 30 and h > 30:
                self.cv_video.delete("status_bg")
                self.cv_video.delete("status_text")
                self.cv_video.create_rectangle(0, h - 26, w, h, fill="#451a03", outline="#78350f", tags="status_bg")
                self.cv_video.create_text(
                    w // 2, h - 13,
                    text="⏸️ PAUSADO | Processo em espera",
                    fill="#facc15",
                    font=("Segoe UI", 8, "bold"),
                    tags="status_text"
                )
            self._video_after_id = self.root.after(100, self._render_video_frame)
            return

        ret, frame = self._video_cap.read()
        if not ret:
            # Vídeo terminou: troca aleatoriamente para o próximo vídeo da pasta anim!
            self._switch_to_next_anim_video()
            if self._video_cap and self._video_cap.isOpened():
                ret, frame = self._video_cap.read()

        if ret and frame is not None:
            w = max(10, self.cv_video.winfo_width())
            h = max(10, self.cv_video.winfo_height())
            if w > 30 and h > 30:
                h_video = max(10, h - 26)
                fh, fw = frame.shape[:2]
                scale = min(w / float(fw), h_video / float(fh))
                tw = max(10, int(fw * scale))
                th = max(10, int(fh * scale))
                try:
                    resized = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
                    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                    self._video_photo = ImageTk.PhotoImage(Image.fromarray(rgb))
                    self.cv_video.delete("all")
                    self.cv_video.create_image(w // 2, h_video // 2, image=self._video_photo)
                    # Rodapé translúcido de telemetria
                    self.cv_video.create_rectangle(0, h - 26, w, h, fill="#0f172a", outline="#1e293b")
                    spd_txt = self._transfer_speed_str or "Transferindo mídias..."
                    self.cv_video.create_text(
                        w // 2, h - 13,
                        text=f"⚡ {spd_txt}",
                        fill="#38bdf8",
                        font=("Segoe UI", 8, "bold"),
                        tags="status_text"
                    )
                except Exception:
                    pass

        self._video_after_id = self.root.after(41, self._render_video_frame)

    def _update_transfer_speed(self, speed_str: str):
        """Atualiza a taxa de transferência exibida na legenda do vídeo."""
        self._transfer_speed_str = speed_str
        if hasattr(self, "cv_video") and self.cv_video.winfo_exists():
            try:
                self.cv_video.itemconfigure("status_text", text=f"⚡ {speed_str} | Copiando...")
            except Exception:
                pass

    def _toggle_pause_task(self):
        """Alterna entre pausar e retomar a transferência ou exclusão em andamento."""
        if not hasattr(self, "pause_event"):
            return
        if not self.pause_event.is_set():
            self.pause_event.set()
            if hasattr(self, "btn_pause"):
                self.btn_pause.config(text="▶️ Continuar")
            self.var_status_msg.set("⏸️ Processo pausado pelo usuário.")
            self._log_console("Processo pausado pelo usuário.", "Pausa:")
            if hasattr(self, "_update_transfer_speed"):
                self._update_transfer_speed("PAUSADO")
        else:
            self.pause_event.clear()
            if hasattr(self, "btn_pause"):
                self.btn_pause.config(text="⏸️ Pausar")
            self.var_status_msg.set("▶️ Retomando processo...")
            self._log_console("Processo retomado.", "Retomada:")

    # Aliases retrocompatíveis
    def _init_bit_particles(self):
        self._init_video_anim()

    def _redraw_data_flow(self):
        self._draw_standby_canvas()

    def _animate_bits(self):
        pass

    # --- Animação Visual de Carregamento na Área em Branco ---
    def _setup_loading_overlay(self):
        """Constrói os widgets centrais da animação de carregamento."""
        self._is_loading = False
        self._spinner_angle = 0
        self._spinner_step = 0
        self._spinner_after_id = None
        self._loading_base_msg = "Carregando arquivos"

        # Painel centralizador
        f_center = tk.Frame(self.f_orig_loading, bg="#f8f9fa")
        f_center.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Spinner rotativo circular em Canvas
        self.cv_spinner = tk.Canvas(f_center, width=64, height=64, bg="#f8f9fa", highlightthickness=0)
        self.cv_spinner.pack(pady=(0, 12))

        # Trilha de fundo sutil
        self.cv_spinner.create_oval(10, 10, 54, 54, outline="#e2e8f0", width=4)
        # Arco animado rotativo
        self.cv_spinner.create_arc(
            10, 10, 54, 54,
            start=0, extent=100,
            style=tk.ARC,
            outline="#0078d4",
            width=4,
            tags="arc"
        )

        self.lbl_loading_title = tk.Label(
            f_center,
            text="Carregando Mídias",
            font=("Segoe UI", 11, "bold"),
            bg="#f8f9fa",
            fg="#212529"
        )
        self.lbl_loading_title.pack(pady=(0, 4))

        self.lbl_loading_dots = tk.Label(
            f_center,
            text="Aguarde, lendo informações...",
            font=("Segoe UI", 9),
            bg="#f8f9fa",
            fg="#6c757d"
        )
        self.lbl_loading_dots.pack(pady=(0, 12))

        self.pbar_loading = ttk.Progressbar(f_center, mode="indeterminate", length=220)
        self.pbar_loading.pack()

    def _start_loading_animation(self, msg: str = "Carregando arquivos..."):
        """Exibe a animação de carregamento na área em branco da origem."""
        self._is_loading = True
        self._loading_base_msg = msg
        if hasattr(self, "lbl_loading_dots"):
            self.lbl_loading_dots.config(text=f"{msg}...")

        # Esconde visualizações de dados enquanto carrega
        if hasattr(self, "f_ip_table"):
            self.f_ip_table.pack_forget()
        if hasattr(self, "f_ip_grid"):
            self.f_ip_grid.pack_forget()
        if hasattr(self, "f_orig_loading"):
            self.f_orig_loading.pack(fill=tk.BOTH, expand=True)

        try:
            self.pbar_loading.start(14)
        except Exception:
            pass

        if self._spinner_after_id:
            try:
                self.root.after_cancel(self._spinner_after_id)
            except Exception:
                pass
            self._spinner_after_id = None

        self._animate_spinner()

    def _animate_spinner(self):
        """Ciclo contínuo de rotação a 35ms (~28 FPS) com pontinhos dinâmicos."""
        if not self._is_loading:
            return

        self._spinner_angle = (self._spinner_angle + 12) % 360
        self._spinner_step = (self._spinner_step + 1) % 4
        dots = "." * (self._spinner_step + 1)

        try:
            self.cv_spinner.delete("arc")
            self.cv_spinner.create_arc(
                10, 10, 54, 54,
                start=self._spinner_angle,
                extent=105,
                style=tk.ARC,
                outline="#0078d4",
                width=4,
                tags="arc"
            )
            if self._spinner_step == 0:
                self.lbl_loading_dots.config(text=f"{self._loading_base_msg}{dots}")
        except Exception:
            pass

        self._spinner_after_id = self.root.after(35, self._animate_spinner)

    def _update_loading_status(self, msg: str):
        """Atualiza o texto da animação em tempo real durante varreduras longas."""
        if self._is_loading and hasattr(self, "lbl_loading_dots"):
            self._loading_base_msg = msg
            self.lbl_loading_dots.config(text=f"{msg}...")

    def _stop_loading_animation(self):
        """Finaliza a animação de carregamento e restaura a visualização ativa."""
        self._is_loading = False
        if self._spinner_after_id:
            try:
                self.root.after_cancel(self._spinner_after_id)
            except Exception:
                pass
            self._spinner_after_id = None

        try:
            self.pbar_loading.stop()
        except Exception:
            pass

        if hasattr(self, "f_orig_loading"):
            self.f_orig_loading.pack_forget()

        # Restaura a tabela ou grade conforme o modo selecionado
        mode = self.var_orig_view.get()
        if mode in ("📑 Detalhes", "📄 Lista"):
            if hasattr(self, "f_ip_grid"):
                self.f_ip_grid.pack_forget()
            if hasattr(self, "f_ip_table"):
                self.f_ip_table.pack(fill=tk.BOTH, expand=True)
        else:
            if hasattr(self, "f_ip_table"):
                self.f_ip_table.pack_forget()
            if hasattr(self, "f_ip_grid"):
                self.f_ip_grid.pack(fill=tk.BOTH, expand=True)

    def _clear_orig_list(self, msg: str = "Carregando arquivos..."):
        """
        Limpa imediatamente a lista visual e os dados da origem (tabela, miniaturas, memória e inspetor)
        enquanto a nova lista de arquivos está sendo varrida ou o dispositivo reconectado.
        Ativa a animação fluida na área em branco durante processos ativos.
        """
        self.iphone_items = []
        self.displayed_items = []
        self.item_checkboxes = {}
        self.var_custom_local.set("")  # Limpa a etiqueta temporária ao mudar de pasta/origem

        if hasattr(self, "tree_iphone"):
            for row in list(self.tree_iphone.get_children()):
                self.tree_iphone.delete(row)

        if hasattr(self, "inner_grid_orig"):
            for w in list(self.inner_grid_orig.winfo_children()):
                w.destroy()

        if hasattr(self, "grid_thumb_queue"):
            while not self.grid_thumb_queue.empty():
                try:
                    self.grid_thumb_queue.get_nowait()
                except Exception:
                    break

        self.var_prev_name.set("Nenhum item selecionado")
        self.var_prev_date.set("-")
        self.var_prev_size.set("-")
        self.var_prev_loc.set("-")
        if hasattr(self, "lbl_thumb"):
            self.lbl_thumb.config(image="", text="Aguarde...\nCarregando arquivos")

        self.var_summary_iphone.set("0 arquivos (Carregando...)")
        self.var_orig_sel_size.set("📦 Total Selecionado: 0 KB (0 arquivos)")
        self.var_status_msg.set(msg)
        self.var_progress_val.set(10)
        self.var_pct_label.set("10.0%")
        self.var_file_progress_val.set(0.0)
        self.var_file_pct_label.set("0.0%")
        self.var_file_status.set("Pronto para transferir.")

        # Inicia a animação na parte em branco caso seja uma operação em andamento
        is_active_op = any(k in msg.lower() for k in ("carregando", "varrendo", "conectando", "alternando"))
        if is_active_op:
            self._start_loading_animation(msg)
        else:
            self._stop_loading_animation()

    def _manual_reconnect_iphone(self):
        """Disparado pelo botão '🔌 Conectar / Reconectar' com aviso visual caso não conecte."""
        self._auto_connect_async(manual=True)

    def _auto_connect_async(self, manual: bool = False):
        self._clear_orig_list("Conectando ao iPhone...")
        self.var_device_status.set("Conectando ao iPhone...")
        self.lbl_device.config(fg="#f0ad4e")
        self._log_console("Procurando dispositivo iPhone conectado via USB...", "Comando:")
        threading.Thread(target=self._auto_connect_worker, args=(manual,), daemon=True).start()

    def _auto_connect_worker(self, manual: bool = False):
        ok = False
        attempts = 3 if manual else 1
        for i in range(attempts):
            ok = self.manager.connect()
            if ok:
                break
            if manual and i < attempts - 1:
                time.sleep(0.4)

        if ok:
            name = self.manager.device_name or "Apple iPhone"
            self._safe_call(lambda: self._on_connected(name, manual))
        else:
            usb_present = self.manager.check_usb_presence()
            self._safe_call(lambda: self._on_disconnected(manual, usb_present))

    def _on_connected(self, device_name: str, manual: bool = False):
        self.var_device_status.set(f"● {device_name} (Conectado)")
        self.lbl_device.config(fg="#28a745")
        self._log_console(f"Dispositivo reconhecido: {device_name} (Acesso DCIM concedido)", "Resposta:")

        # Popula combobox de pastas/meses
        months = self.manager.get_available_months()
        cb_values = ["Todas as Pastas"]
        for m in months:
            m_num = m.split("-")[1]
            cb_values.append(f"{m} ({MESES_NOMES.get(m_num, m_num)})")

        self.cb_months["values"] = cb_values
        if len(cb_values) > 1:
            self.cb_months.current(1) # Primeiro mês mais recente
        else:
            self.cb_months.current(0)

        self._refresh_local_view()
        self._start_scan_async()
        if manual:
            messagebox.showinfo("Conectado", f"iPhone conectado com sucesso!\n\nDispositivo: {device_name}\nAcesso às fotos e vídeos liberado.")

    def _on_disconnected(self, manual: bool = False, usb_present: bool = False):
        self._stop_loading_animation()
        if usb_present:
            self.var_device_status.set("● iPhone USB Conectado (Tela Bloqueada no iOS)")
            self.lbl_device.config(fg="#f0ad4e")
            self._log_console("iPhone detectado na USB, mas o acesso MTP está bloqueado pelo iOS. Desbloqueie a tela.", "Aviso:")
        else:
            self.var_device_status.set("● Desconectado")
            self.lbl_device.config(fg="#dc3545")
            self._log_console("Nenhum iPhone detectado na porta USB. Verifique o cabo.", "Erro:")

        self._refresh_local_view()
        if manual:
            if usb_present:
                messagebox.showwarning(
                    "iPhone Bloqueado no iOS",
                    "Identificamos que seu iPhone ESTÁ fisicamente conectado na porta USB do computador, mas o sistema iOS está bloqueando o acesso aos arquivos!\n\n"
                    "Para liberar o acesso agora:\n"
                    "1. Pegue o iPhone e DESBLOQUEIE A TELA com sua senha ou FaceID.\n"
                    "2. Se a tela já estava acesa, desconecte o cabo USB do iPhone e conecte-o novamente com a tela desbloqueada.\n"
                    "3. Se aparecer a pergunta 'Confiar neste computador?', toque em 'Confiar' e digite o código do iPhone.\n\n"
                    "Assim que desbloquear, clique no botão '🔌 Conectar / Reconectar'!"
                )
            else:
                messagebox.showwarning(
                    "iPhone Não Detectado",
                    "Nenhum iPhone foi detectado na porta USB.\n\n"
                    "Por favor, verifique:\n"
                    "1. O cabo USB está bem conectado ao computador e ao iPhone.\n"
                    "2. Experimente trocar de porta USB no computador.\n"
                    "3. Desbloqueie a tela do iPhone e clique novamente no botão '🔌 Conectar / Reconectar'."
                )

    def _on_folder_select(self):
        self._start_scan_async()

    def _start_scan_async(self):
        stype = self.var_source_type.get()
        src = self.var_source_dir.get().strip()
        folder_selection = self.var_folder_filter.get()
        filter_by_date = self.var_filter_by_date.get()
        date_from = self.var_date_from.get().strip() if filter_by_date else None
        date_to = self.var_date_to.get().strip() if filter_by_date else None
        date_from = date_from or None
        date_to = date_to or None
        inc_photos = self.var_inc_photos.get()
        inc_videos = self.var_inc_videos.get()

        if stype == "📁 Pasta / Disco Local":
            if not src or not os.path.exists(src):
                self._clear_orig_list("Pasta de origem local não encontrada.")
                return
            msg = f"Varrendo mídias na pasta local: {src}..."
        else:
            if not self.manager.is_connected():
                self._clear_orig_list("iPhone não conectado.")
                return
            msg = f"Varrendo mídias no iPhone ({folder_selection})..."

        # Limpa imediatamente a lista anterior enquanto varre os novos arquivos
        self._clear_orig_list(msg)
        threading.Thread(
            target=self._scan_worker,
            args=(stype, src, folder_selection, date_from, date_to, inc_photos, inc_videos),
            daemon=True
        ).start()

    def _scan_worker(self, stype, src, folder_selection, date_from, date_to, inc_photos, inc_videos):
        filter_months = None
        if folder_selection and folder_selection not in ("Todas as Pastas", "Todos os Meses"):
            m_code = folder_selection.split(" ")[0]
            filter_months = [m_code]

        self._safe_call(lambda: self._log_console(f"Varrendo arquivos para: {folder_selection}", "Comando:"))

        if stype == "📁 Pasta / Disco Local":
            if not src or not os.path.exists(src):
                self._safe_call(lambda: self._on_scan_done([]))
                return

            def on_scan_prog(msg, cur, tot):
                pct = (cur / tot) * 100 if tot > 0 else 0
                self._safe_call(lambda p=pct, m=msg: (
                    self.var_progress_val.set(p),
                    self.var_pct_label.set(f"{p:.1f}%"),
                    self.var_status_msg.set(m),
                    self._update_loading_status(m)
                ))

            items = self.manager.scan_local_folder(
                folder_path=src,
                recursive=True,
                filter_months=filter_months,
                date_from=date_from,
                date_to=date_to,
                include_photos=inc_photos,
                include_videos=inc_videos,
                progress_callback=on_scan_prog,
                cancel_event=self.cancel_event
            )
            months = self.manager.get_months_from_items(items)
            cb_values = ["Todos os Meses"]
            for m in months:
                m_num = m.split("-")[1] if "-" in m else m
                cb_values.append(f"{m} ({MESES_NOMES.get(m_num, m_num)})")
            self._safe_call(lambda vals=cb_values: self._update_months_combo(vals))
        else:
            def on_ip_scan_prog(msg, cur, tot):
                pct = (cur / tot) * 100 if tot > 0 else 0
                self._safe_call(lambda p=pct, m=msg: (
                    self.var_progress_val.set(p),
                    self.var_pct_label.set(f"{p:.1f}%"),
                    self.var_status_msg.set(m),
                    self._update_loading_status(m)
                ))

            items = self.manager.scan_photos(
                filter_months=filter_months,
                date_from=date_from,
                date_to=date_to,
                include_photos=inc_photos,
                include_videos=inc_videos,
                progress_callback=on_ip_scan_prog,
                cancel_event=self.cancel_event
            )

        self._safe_call(lambda: self._on_scan_done(items))

    def _on_scan_done(self, items):
        self._stop_loading_animation()
        self.iphone_items = items
        self.item_checkboxes = {}
        self.var_progress_val.set(100)
        self.var_pct_label.set("100%")
        self.var_status_msg.set(f"Pronto: {len(items)} arquivos carregados.")
        self._log_console(f"Listagem de diretório concluída ({len(items)} arquivos recebidos)", "Resposta:")
        self._apply_quick_filter()

    def _apply_quick_filter(self):
        q = self.var_filter_text.get().strip().lower()
        for row in self.tree_iphone.get_children():
            self.tree_iphone.delete(row)

        self.displayed_items = []
        for idx, it in enumerate(self.iphone_items):
            if q and q not in it["name"].lower() and q not in it["date"].lower():
                continue
            self.displayed_items.append((idx, it))

        if self._orig_sort_col:
            self._apply_orig_sort_to_displayed()

        for idx, it in self.displayed_items:
            icon = "🎬" if it["ext"] in VIDEO_EXTENSIONS else "📷"
            is_chk = self.item_checkboxes.get(idx, False)
            self.tree_iphone.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    "☑" if is_chk else "☐",
                    f"{icon} {it['name']}",
                    it["ext"].upper(),
                    it["date"],
                    it["time"],
                    format_size(it["size"]),
                    it["folder_name"]
                )
            )

        self._update_selection_summary()
        if self.var_orig_view.get() in ("🖼️ Miniaturas", "🔍 Miniaturas Gigantes"):
            self._render_orig_grid()

    def _apply_orig_sort_to_displayed(self):
        col = self._orig_sort_col
        if not col:
            return

        def get_key(item_tuple):
            idx, it = item_tuple
            if col == "check":
                return 1 if self.item_checkboxes.get(idx, False) else 0
            elif col == "name":
                return natural_sort_key(it.get("name", ""))
            elif col == "type":
                return it.get("ext", "").lower()
            elif col == "date":
                return (it.get("date", ""), it.get("time", ""))
            elif col == "time":
                return it.get("time", "")
            elif col == "size":
                return it.get("size", 0)
            elif col == "folder":
                return natural_sort_key(it.get("folder_name", ""))
            return 0

        self.displayed_items.sort(key=get_key, reverse=self._orig_sort_desc)

    def _sort_orig_by_column(self, col: str):
        """Alterna a ordenação da coluna da origem (A->Z ou Z->A) e atualiza a interface."""
        if self._orig_sort_col == col:
            self._orig_sort_desc = not self._orig_sort_desc
        else:
            self._orig_sort_col = col
            self._orig_sort_desc = (col in ("date", "time", "size", "check"))

        headers = {
            "check": "Sel",
            "name": "Arquivo",
            "type": "Tipo",
            "date": "Data",
            "time": "Hora",
            "size": "Tamanho",
            "folder": "Pasta Origem"
        }
        arrow = " ▼" if self._orig_sort_desc else " ▲"
        for c, title in headers.items():
            txt = title + (arrow if c == col else "")
            self.tree_iphone.heading(c, text=txt)

        self._apply_orig_sort_to_displayed()

        for row in self.tree_iphone.get_children():
            self.tree_iphone.delete(row)

        for idx, it in self.displayed_items:
            icon = "🎬" if it["ext"] in VIDEO_EXTENSIONS else "📷"
            is_chk = self.item_checkboxes.get(idx, False)
            self.tree_iphone.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    "☑" if is_chk else "☐",
                    f"{icon} {it['name']}",
                    it["ext"].upper(),
                    it["date"],
                    it["time"],
                    format_size(it["size"]),
                    it["folder_name"]
                )
            )

        if self.var_orig_view.get() in ("🖼️ Miniaturas", "🔍 Miniaturas Gigantes"):
            self._render_orig_grid()

    def _get_selected_items(self) -> List[Tuple[int, Dict]]:
        """
        Retorna todos os arquivos selecionados para download ou exclusão.
        1. Prioridade absoluta para todos os itens marcados com a caixa [☑].
        2. Se nenhuma caixa estiver marcada com [☑], utiliza as linhas destacadas na tabela.
        """
        checked_dict = {}
        for idx, it in self.displayed_items:
            if self.item_checkboxes.get(idx, False):
                checked_dict[idx] = it

        for iid in self.tree_iphone.get_children():
            vals = self.tree_iphone.item(iid, "values")
            if vals and len(vals) > 0 and vals[0] == "☑":
                if iid.isdigit():
                    idx = int(iid)
                    if idx < len(self.iphone_items):
                        checked_dict[idx] = self.iphone_items[idx]

        if checked_dict:
            return sorted(list(checked_dict.items()), key=lambda x: x[0])

        # Fallback para linhas destacadas (se o usuário selecionou linhas sem marcar checkboxes)
        sel = self.tree_iphone.selection()
        if sel:
            res = []
            for iid in sel:
                if iid.isdigit():
                    idx = int(iid)
                    if idx < len(self.iphone_items):
                        res.append((idx, self.iphone_items[idx]))
            return res

        return []

    def _update_selection_summary(self):
        """Atualiza o resumo do painel Origem (exibidos e tamanho total dos arquivos selecionados)."""
        selected_items = self._get_selected_items()
        total_sel_bytes = sum(it.get("size", 0) for _, it in selected_items)
        total_disp_bytes = sum(it.get("size", 0) for _, it in self.displayed_items)
        n_sel = len(selected_items)
        n_disp = len(self.displayed_items)

        if total_disp_bytes > 0:
            self.var_summary_iphone.set(f"{n_disp} arquivos ({format_size(total_disp_bytes)})")
        else:
            self.var_summary_iphone.set(f"{n_disp} arquivos")

        arq_label = "arquivo" if n_sel == 1 else "arquivos"
        self.var_orig_sel_size.set(f"📦 Total Selecionado: {format_size(total_sel_bytes)} ({n_sel} {arq_label})")

    def _on_iphone_click(self, event):
        """Alterna a caixa de seleção [☑ / ☐] ao clicar diretamente na coluna 'Sel' (#1)."""
        region = self.tree_iphone.identify("region", event.x, event.y)
        col = self.tree_iphone.identify_column(event.x)
        iid = self.tree_iphone.identify_row(event.y)
        if region == "cell" and col == "#1" and iid:
            vals = list(self.tree_iphone.item(iid, "values"))
            new_state = (vals[0] != "☑")
            vals[0] = "☑" if new_state else "☐"
            self.tree_iphone.item(iid, values=vals)
            if iid.isdigit():
                self.item_checkboxes[int(iid)] = new_state
            self._update_selection_summary()

    def _on_iphone_select_changed(self, event):
        """Carrega miniatura e metadados no inspetor ao navegar pelas linhas sem limpar seleções."""
        sel = self.tree_iphone.selection()
        if not sel:
            return

        active_iid = self.tree_iphone.focus() or sel[0]
        if active_iid.isdigit():
            idx = int(active_iid)
            if idx < len(self.iphone_items):
                it = self.iphone_items[idx]
                self.var_prev_name.set(it["name"])
                self.var_prev_date.set(f"{it['date']} {it['time']}")
                self.var_prev_size.set(format_size(it["size"]))
                self.var_prev_loc.set("Carregando GPS...")
                self.lbl_thumb.config(image="", text="Carregando\nminiatura...")
                self.thumb_queue.put((idx, it))

        self._update_selection_summary()

    def _on_iphone_double_click(self, event):
        """Duplo clique em uma linha alterna a marcação [☑ / ☐]."""
        iid = self.tree_iphone.identify_row(event.y)
        if iid:
            vals = list(self.tree_iphone.item(iid, "values"))
            new_state = (vals[0] != "☑")
            vals[0] = "☑" if new_state else "☐"
            self.tree_iphone.item(iid, values=vals)
            if iid.isdigit():
                self.item_checkboxes[int(iid)] = new_state
            self._update_selection_summary()

    def _toggle_selected_rows(self):
        """Barra de espaço: alterna a marcação de todas as linhas atualmente destacadas."""
        sel = self.tree_iphone.selection()
        if not sel:
            return
        for iid in sel:
            vals = list(self.tree_iphone.item(iid, "values"))
            new_state = (vals[0] != "☑")
            vals[0] = "☑" if new_state else "☐"
            self.tree_iphone.item(iid, values=vals)
            if iid.isdigit():
                self.item_checkboxes[int(iid)] = new_state
        self._update_selection_summary()

    def _select_all(self):
        """Marca todos os itens exibidos com [☑]."""
        for idx, it in self.displayed_items:
            self.item_checkboxes[idx] = True

        for iid in self.tree_iphone.get_children():
            vals = list(self.tree_iphone.item(iid, "values"))
            vals[0] = "☑"
            self.tree_iphone.item(iid, values=vals)

        for idx, card, var_chk in self._orig_cards:
            var_chk.set(True)
            self._on_card_checkbox_toggled(idx, var_chk, card)

        self._update_selection_summary()

    def _deselect_all(self):
        """Desmarca todos os itens exibidos."""
        for idx, it in self.displayed_items:
            self.item_checkboxes[idx] = False

        for iid in self.tree_iphone.get_children():
            vals = list(self.tree_iphone.item(iid, "values"))
            vals[0] = "☐"
            self.tree_iphone.item(iid, values=vals)

        for idx, card, var_chk in self._orig_cards:
            var_chk.set(False)
            self._on_card_checkbox_toggled(idx, var_chk, card)

        self.tree_iphone.selection_remove(self.tree_iphone.selection())
        self._update_selection_summary()

    # --- Métodos de Alternância de Exibição (Detalhes, Lista, Miniaturas, Miniaturas Gigantes) ---
    def _on_orig_view_changed(self):
        self._apply_orig_view_mode()
        self._save_config()

    def _apply_orig_view_mode(self):
        if getattr(self, "_is_loading", False):
            return
        mode = self.var_orig_view.get()
        if mode in ("📑 Detalhes", "📄 Lista"):
            self.f_ip_grid.pack_forget()
            self.f_ip_table.pack(fill=tk.BOTH, expand=True)
            if mode == "📑 Detalhes":
                self.tree_iphone.column("check", width=45, minwidth=40, stretch=False)
                self.tree_iphone.column("name", width=170, minwidth=120, stretch=True)
                self.tree_iphone.column("type", width=55, minwidth=45, stretch=False)
                self.tree_iphone.column("date", width=95, minwidth=80, stretch=False)
                self.tree_iphone.column("time", width=60, minwidth=50, stretch=False)
                self.tree_iphone.column("size", width=80, minwidth=60, stretch=False)
                self.tree_iphone.column("folder", width=90, minwidth=70, stretch=False)
            else:  # "📄 Lista"
                self.tree_iphone.column("check", width=45, minwidth=40, stretch=False)
                self.tree_iphone.column("name", width=280, minwidth=150, stretch=True)
                self.tree_iphone.column("type", width=0, minwidth=0, stretch=False)
                self.tree_iphone.column("date", width=0, minwidth=0, stretch=False)
                self.tree_iphone.column("time", width=0, minwidth=0, stretch=False)
                self.tree_iphone.column("size", width=85, minwidth=60, stretch=False)
                self.tree_iphone.column("folder", width=0, minwidth=0, stretch=False)
        else:
            self.f_ip_table.pack_forget()
            self.f_ip_grid.pack(fill=tk.BOTH, expand=True)
            self._render_orig_grid()

    def _on_dest_view_changed(self):
        self._apply_dest_view_mode()
        self._save_config()

    def _apply_dest_view_mode(self):
        mode = self.var_dest_view.get()
        if mode in ("📑 Detalhes", "📄 Lista"):
            self.f_loc_grid.pack_forget()
            self.f_loc_table.pack(fill=tk.BOTH, expand=True)
            if mode == "📑 Detalhes":
                self.tree_local.column("#0", width=160, minwidth=100, stretch=True)
                self.tree_local.column("name", width=110, minwidth=80, stretch=True)
                self.tree_local.column("size", width=70, minwidth=50, stretch=False)
                self.tree_local.column("date", width=110, minwidth=80, stretch=False)
            else:  # "📄 Lista"
                self.tree_local.column("#0", width=180, minwidth=100, stretch=True)
                self.tree_local.column("name", width=180, minwidth=100, stretch=True)
                self.tree_local.column("size", width=75, minwidth=50, stretch=False)
                self.tree_local.column("date", width=0, minwidth=0, stretch=False)
        else:
            self.f_loc_table.pack_forget()
            self.f_loc_grid.pack(fill=tk.BOTH, expand=True)
            self._render_dest_grid()

    # --- Configurações de Canvas e Rolagem das Grades ---
    def _on_orig_inner_configure(self):
        self.inner_grid_orig.update_idletasks()
        self.cv_orig_grid.configure(scrollregion=self.cv_orig_grid.bbox("all"))

    def _on_orig_canvas_configure(self, event):
        self.cv_orig_grid.itemconfig(self.cv_orig_window, width=event.width)
        mode = self.var_orig_view.get()
        if mode in ("🖼️ Miniaturas", "🔍 Miniaturas Gigantes"):
            card_w = 110 if mode == "🖼️ Miniaturas" else 210
            cols = max(1, (event.width - 20) // (card_w + 10))
            if cols != self._last_orig_cols:
                self._last_orig_cols = cols
                self._regrid_orig_cards(cols)

    def _on_orig_mousewheel(self, event):
        self.cv_orig_grid.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_dest_inner_configure(self):
        self.inner_grid_dest.update_idletasks()
        self.cv_dest_grid.configure(scrollregion=self.cv_dest_grid.bbox("all"))

    def _on_dest_canvas_configure(self, event):
        self.cv_dest_grid.itemconfig(self.cv_dest_window, width=event.width)
        mode = self.var_dest_view.get()
        if mode in ("🖼️ Miniaturas", "🔍 Miniaturas Gigantes"):
            card_w = 110 if mode == "🖼️ Miniaturas" else 210
            cols = max(1, (event.width - 20) // (card_w + 10))
            if cols != self._last_dest_cols:
                self._last_dest_cols = cols
                self._regrid_dest_cards(cols)

    def _on_dest_mousewheel(self, event):
        self.cv_dest_grid.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # --- Renderização das Grades de Miniaturas (Origem e Destino) ---
    def _render_orig_grid(self):
        for w in self.inner_grid_orig.winfo_children():
            w.destroy()
        self._orig_cards = []

        mode = self.var_orig_view.get()
        is_giant = (mode == "🔍 Miniaturas Gigantes")
        card_w = 215 if is_giant else 115
        card_h = 270 if is_giant else 165
        thumb_sz = (180, 180) if is_giant else (90, 90)

        # Esvazia fila anterior da grade para priorizar os itens visíveis atuais
        while not self.grid_thumb_queue.empty():
            try:
                self.grid_thumb_queue.get_nowait()
            except Exception:
                break

        for idx, it in self.displayed_items:
            is_checked = self.item_checkboxes.get(idx, False)
            bg_col = "#e6f2ff" if is_checked else "#ffffff"

            card = tk.Frame(self.inner_grid_orig, bg=bg_col, relief=tk.SOLID, bd=1, width=card_w, height=card_h)
            card.pack_propagate(False)

            # Topo do card: Ícone e tipo de mídia
            f_card_top = tk.Frame(card, bg=bg_col)
            f_card_top.pack(fill=tk.X, padx=3, pady=(2, 1))

            icon = "🎬 Vídeo" if it.get("ext", "").lower() in VIDEO_EXTENSIONS else "📷 Foto"
            tk.Label(f_card_top, text=icon, bg=bg_col, font=("Segoe UI", 7, "bold"), fg="#495057").pack(side=tk.LEFT)
            ext_clean = it.get("ext", "").upper().replace(".", "")
            tk.Label(f_card_top, text=ext_clean, bg=bg_col, font=("Segoe UI", 7), fg="#6c757d").pack(side=tk.RIGHT)

            # BASE do card: Botão de Marcar / Desmarcar
            f_card_bottom = tk.Frame(card, bg=bg_col)
            f_card_bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=3, pady=(1, 3))

            var_chk = tk.BooleanVar(value=is_checked)
            btn_chk = tk.Checkbutton(
                f_card_bottom,
                text="☑ Selecionado" if is_checked else "☐ Marcar",
                variable=var_chk,
                bg="#cce5ff" if is_checked else "#f0f0f0",
                activebackground="#b8daff",
                selectcolor="#ffffff",
                relief=tk.RAISED,
                bd=1,
                font=("Segoe UI", 7, "bold" if is_checked else "normal"),
                command=lambda i=idx, v=var_chk, c=card: self._on_card_checkbox_toggled(i, v, c)
            )
            btn_chk.pack(fill=tk.X, expand=True)

            # Centro do card: Miniatura da foto / vídeo
            f_img = tk.Frame(card, bg="#202020", width=thumb_sz[0], height=thumb_sz[1])
            f_img.pack(pady=1)
            f_img.pack_propagate(False)

            lbl_img = tk.Label(f_img, bg="#202020", text="...", fg="#888888", font=("Segoe UI", 7))
            lbl_img.pack(fill=tk.BOTH, expand=True)

            cache_key = f"orig_{it['name']}_{thumb_sz[0]}"
            if cache_key in self._photo_cache:
                lbl_img.config(image=self._photo_cache[cache_key], text="")
            else:
                self.grid_thumb_queue.put(("orig", it, thumb_sz, lbl_img, cache_key))

            # Nome e tamanho do arquivo
            s_name = it["name"]
            if not is_giant and len(s_name) > 13:
                s_name = s_name[:10] + "..."
            elif is_giant and len(s_name) > 26:
                s_name = s_name[:23] + "..."

            lbl_name = tk.Label(card, text=s_name, bg=bg_col, font=("Segoe UI", 8, "bold" if is_giant else "normal"))
            lbl_name.pack(fill=tk.X, padx=2)

            lbl_sz = tk.Label(card, text=format_size(it["size"]), bg=bg_col, fg="#666666", font=("Segoe UI", 7))
            lbl_sz.pack(fill=tk.X, padx=2)

            for widget in (card, f_card_top, f_card_bottom, f_img, lbl_img, lbl_name, lbl_sz):
                widget.bind("<Button-1>", lambda e, i=idx, itm=it, c=card: self._on_orig_card_clicked(i, itm, c))
                widget.bind("<Double-1>", lambda e, i=idx, v=var_chk, c=card: self._on_card_double_clicked(i, v, c))
                widget.bind("<MouseWheel>", self._on_orig_mousewheel)

            self._orig_cards.append((idx, card, var_chk))

        c_width = self.cv_orig_grid.winfo_width() or 500
        cols = max(1, (c_width - 20) // (card_w + 10))
        self._last_orig_cols = cols
        self._regrid_orig_cards(cols)

    def _regrid_orig_cards(self, cols: int):
        for i, (idx, card, var_chk) in enumerate(self._orig_cards):
            card.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="nw")
        self.inner_grid_orig.update_idletasks()
        self.cv_orig_grid.configure(scrollregion=self.cv_orig_grid.bbox("all"))

    def _on_card_checkbox_toggled(self, idx: int, var_chk: tk.BooleanVar, card: tk.Frame):
        val = var_chk.get()
        self.item_checkboxes[idx] = val
        card.config(bg="#e6f2ff" if val else "#ffffff")
        for child in card.winfo_children():
            if isinstance(child, tk.Frame):
                child.config(bg="#e6f2ff" if val else "#ffffff")
                for sub in child.winfo_children():
                    if isinstance(sub, tk.Checkbutton):
                        sub.config(
                            text="☑ Selecionado" if val else "☐ Marcar",
                            bg="#cce5ff" if val else "#f0f0f0",
                            font=("Segoe UI", 7, "bold" if val else "normal")
                        )
                    elif isinstance(sub, tk.Label):
                        sub.config(bg="#e6f2ff" if val else "#ffffff")
            elif isinstance(child, tk.Label):
                child.config(bg="#e6f2ff" if val else "#ffffff")

        if self.tree_iphone.exists(str(idx)):
            vals = list(self.tree_iphone.item(str(idx), "values"))
            if vals:
                vals[0] = "☑" if val else "☐"
                self.tree_iphone.item(str(idx), values=vals)
        self._update_selection_summary()

    def _on_card_double_clicked(self, idx: int, var_chk: tk.BooleanVar, card: tk.Frame):
        var_chk.set(not var_chk.get())
        self._on_card_checkbox_toggled(idx, var_chk, card)

    def _on_orig_card_clicked(self, idx: int, item: Dict, card: tk.Frame):
        self.var_prev_name.set(item["name"])
        self.var_prev_date.set(f"{item.get('date', '-')} {item.get('time', '-')}")
        self.var_prev_size.set(format_size(item.get("size", 0)))
        self.var_prev_loc.set("Carregando GPS...")
        self.lbl_thumb.config(image="", text="Carregando\nminiatura...")
        self.thumb_queue.put((idx, item))

        if self.tree_iphone.exists(str(idx)):
            self.tree_iphone.selection_set(str(idx))
            self.tree_iphone.see(str(idx))

    def _render_dest_grid(self):
        for w in self.inner_grid_dest.winfo_children():
            w.destroy()
        self._dest_cards = []

        mode = self.var_dest_view.get()
        is_giant = (mode == "🔍 Miniaturas Gigantes")
        card_w = 210 if is_giant else 110
        card_h = 240 if is_giant else 140
        thumb_sz = (180, 180) if is_giant else (90, 90)

        for it in self._dest_files_cache:
            card = tk.Frame(self.inner_grid_dest, bg="#ffffff", relief=tk.SOLID, bd=1, width=card_w, height=card_h)
            card.pack_propagate(False)

            f_card_top = tk.Frame(card, bg="#ffffff")
            f_card_top.pack(fill=tk.X, padx=2, pady=1)
            ext = Path(it["name"]).suffix.lower()
            icon = "🎬" if ext in VIDEO_EXTENSIONS else "📷"
            tk.Label(f_card_top, text=f"📁 {it['folder']}", bg="#ffffff", font=("Segoe UI", 7), fg="#555555").pack(side=tk.LEFT)
            tk.Label(f_card_top, text=icon, bg="#ffffff", font=("Segoe UI", 8)).pack(side=tk.RIGHT)

            f_img = tk.Frame(card, bg="#202020", width=thumb_sz[0], height=thumb_sz[1])
            f_img.pack(pady=2)
            f_img.pack_propagate(False)

            lbl_img = tk.Label(f_img, bg="#202020", text="...", fg="#888888", font=("Segoe UI", 7))
            lbl_img.pack(fill=tk.BOTH, expand=True)

            cache_key = f"dest_{it['name']}_{thumb_sz[0]}"
            if cache_key in self._photo_cache:
                lbl_img.config(image=self._photo_cache[cache_key], text="")
            else:
                self.grid_thumb_queue.put(("dest", it["path"], thumb_sz, lbl_img, cache_key))

            s_name = it["name"]
            if not is_giant and len(s_name) > 13:
                s_name = s_name[:10] + "..."
            elif is_giant and len(s_name) > 26:
                s_name = s_name[:23] + "..."

            lbl_name = tk.Label(card, text=s_name, bg="#ffffff", font=("Segoe UI", 8, "bold" if is_giant else "normal"))
            lbl_name.pack(fill=tk.X, padx=2)

            lbl_sz = tk.Label(card, text=format_size(it["size"]), bg="#ffffff", fg="#666666", font=("Segoe UI", 7))
            lbl_sz.pack(fill=tk.X, padx=2)

            for widget in (card, f_card_top, f_img, lbl_img, lbl_name, lbl_sz):
                widget.bind("<Button-1>", lambda e, item=it: self._on_dest_card_clicked(item))
                widget.bind("<Double-1>", lambda e, p=it["path"]: self._open_dest_file(p))
                widget.bind("<MouseWheel>", self._on_dest_mousewheel)

            self._dest_cards.append(card)

        c_width = self.cv_dest_grid.winfo_width() or 400
        cols = max(1, (c_width - 20) // (card_w + 10))
        self._last_dest_cols = cols
        self._regrid_dest_cards(cols)

    def _regrid_dest_cards(self, cols: int):
        for i, card in enumerate(self._dest_cards):
            card.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="nw")
        self.inner_grid_dest.update_idletasks()
        self.cv_dest_grid.configure(scrollregion=self.cv_dest_grid.bbox("all"))

    def _on_dest_card_clicked(self, item: Dict):
        self.var_prev_name.set(item["name"])
        self.var_prev_date.set(item.get("mtime", "-"))
        self.var_prev_size.set(format_size(item.get("size", 0)))
        self.var_prev_loc.set(f"Pasta: {item.get('folder', '-')}")
        self.lbl_thumb.config(image="", text="Carregando\nminiatura...")
        dest_item_info = {
            "name": item["name"],
            "ext": Path(item["name"]).suffix.lower(),
            "local_path": item["path"],
            "is_local": True
        }
        self.thumb_queue.put((0, dest_item_info))

    def _open_dest_file(self, path: str):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível abrir o arquivo:\n{e}")

    def _on_local_select_changed(self, event):
        sel = self.tree_local.selection()
        if not sel:
            return
        node = sel[0]
        vals = self.tree_local.item(node, "values")
        if vals and len(vals) >= 3:
            fname = vals[0]
            fsize = vals[1]
            fmtime = vals[2]
            parent = self.tree_local.parent(node)
            parent_text = self.tree_local.item(parent, "text").replace("📁 ", "").strip()
            dest_dir = Path(self.var_dest_dir.get())
            full_path = dest_dir / parent_text / fname
            if full_path.exists():
                self._on_dest_card_clicked({
                    "name": fname,
                    "path": str(full_path),
                    "size": full_path.stat().st_size,
                    "mtime": fmtime,
                    "folder": parent_text
                })

    def _on_local_double_click(self, event):
        sel = self.tree_local.selection()
        if not sel:
            return
        node = sel[0]
        vals = self.tree_local.item(node, "values")
        if vals and len(vals) >= 1:
            fname = vals[0]
            parent = self.tree_local.parent(node)
            parent_text = self.tree_local.item(parent, "text").replace("📁 ", "").strip()
            dest_dir = Path(self.var_dest_dir.get())
            full_path = dest_dir / parent_text / fname
            if full_path.exists():
                self._open_dest_file(str(full_path))

    # --- Workers de Miniaturas (Inspetor e Grades) ---
    def _start_thumb_workers(self):
        threading.Thread(target=self._thumb_worker_loop, daemon=True).start()
        threading.Thread(target=self._grid_thumb_worker_loop, daemon=True).start()

    def _grid_thumb_worker_loop(self):
        while True:
            try:
                task = self.grid_thumb_queue.get()
                if not task:
                    time.sleep(0.05)
                    continue
                owner_type, item_ref, target_size, target_widget, key = task
                if key in self._photo_cache:
                    photo_img = self._photo_cache[key]
                    self._safe_call(lambda w=target_widget, img=photo_img: self._set_widget_image(w, img))
                    continue

                thumb_path = None
                if owner_type == "orig":
                    thumb_path = self.manager.get_file_thumbnail(item_ref, target_size)
                else:
                    thumb_path = self._get_local_dest_thumbnail(item_ref, target_size)

                if thumb_path and os.path.exists(thumb_path):
                    try:
                        pil_img = Image.open(thumb_path)
                        pil_img.thumbnail(target_size, Image.Resampling.LANCZOS)
                        photo_img = ImageTk.PhotoImage(pil_img)
                        self._photo_cache[key] = photo_img
                        self._safe_call(lambda w=target_widget, img=photo_img: self._set_widget_image(w, img))
                    except Exception:
                        pass
            except Exception:
                time.sleep(0.05)

    def _set_widget_image(self, widget, photo_img):
        try:
            if widget.winfo_exists():
                widget.config(image=photo_img, text="")
        except Exception:
            pass

    def _get_local_dest_thumbnail(self, file_path: str, thumb_size: Tuple[int, int]) -> Optional[str]:
        p = Path(file_path)
        if not p.exists():
            return None
        file_info = {
            "name": p.name,
            "ext": p.suffix.lower(),
            "local_path": str(p),
            "is_local": True
        }
        return self.manager.get_file_thumbnail(file_info, thumb_size)

    def _thumb_worker_loop(self):
        while True:
            try:
                idx, file_info = self.thumb_queue.get()
                # Descarta itens antigos se o usuário navegou rápido
                while not self.thumb_queue.empty():
                    idx, file_info = self.thumb_queue.get_nowait()

                thumb_path = self.manager.get_file_thumbnail(file_info, (210, 210))
                
                # Resolução de GPS para o inspetor
                city = None
                if thumb_path:
                    gps = extract_gps(thumb_path)
                    if gps:
                        city = reverse_geocode(gps[0], gps[1])

                self._safe_call(lambda tp=thumb_path, c=city: self._display_thumbnail(tp, c))
            except Exception:
                time.sleep(0.1)

    def _display_thumbnail(self, thumb_path: Optional[str], city: Optional[str]):
        if city:
            self.var_prev_loc.set(city)
        else:
            self.var_prev_loc.set("Sem GPS / Local Padrão")

        if not thumb_path or not os.path.exists(thumb_path):
            self.lbl_thumb.config(image="", text="Miniatura\nindisponível")
            return

        try:
            pil_img = Image.open(thumb_path)
            self.cached_photo_img = ImageTk.PhotoImage(pil_img)
            self.lbl_thumb.config(image=self.cached_photo_img, text="")
        except Exception:
            self.lbl_thumb.config(image="", text="Erro ao carregar\nminiatura")

    # --- Painel PC Local e Histórico de Caminhos ---
    def _add_recent_path(self, path: str):
        """Adiciona um caminho ao topo do histórico de caminhos recentes e salva."""
        p_clean = path.strip()
        if not p_clean:
            return
        # Remove duplicatas preservando a ordem
        if p_clean in self.recent_paths:
            self.recent_paths.remove(p_clean)
        self.recent_paths.insert(0, p_clean)
        self.recent_paths = self.recent_paths[:12] # Mantém os 12 mais recentes
        if hasattr(self, "cb_dest_dir"):
            self.cb_dest_dir["values"] = self.recent_paths
        self._save_config()

    def _on_recent_path_selected(self):
        """Executado quando o usuário escolhe um caminho no dropdown do histórico."""
        self.var_custom_local.set("")
        path = self.var_dest_dir.get().strip()
        if path:
            self._add_recent_path(path)
            self._refresh_local_view()

    def _on_path_entered(self):
        """Executado quando o usuário digita ou cola um caminho e pressiona Enter."""
        self.var_custom_local.set("")
        path = self.var_dest_dir.get().strip()
        if path:
            self._add_recent_path(path)
            self._refresh_local_view()

    def _browse_dest_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.var_dest_dir.get(), title="Selecione o Diretório Local")
        if chosen:
            self.var_custom_local.set("")
            self.var_dest_dir.set(chosen)
            self._add_recent_path(chosen)
            self._refresh_local_view()

    def _open_local_in_explorer(self):
        dest = self.var_dest_dir.get()
        if os.path.exists(dest):
            os.startfile(dest)
        else:
            messagebox.showinfo("Aviso", f"A pasta local ainda não existe:\n{dest}")

    def _sort_dest_by_column(self, col: str):
        """Alterna a ordenação do painel de destino (crescente/decrescente) e atualiza a interface."""
        if self._dest_sort_col == col:
            self._dest_sort_desc = not self._dest_sort_desc
        else:
            self._dest_sort_col = col
            self._dest_sort_desc = (col in ("size", "date"))

        headers = {
            "#0": "Pastas AAAA-MM-DD[-Local]",
            "name": "Arquivo",
            "size": "Tamanho",
            "date": "Data Modificação"
        }
        arrow = " ▼" if self._dest_sort_desc else " ▲"
        for c, title in headers.items():
            txt = title + (arrow if c == col else "")
            self.tree_local.heading(c, text=txt)

        if col == "#0":
            parents = list(self.tree_local.get_children(""))
            parents.sort(
                key=lambda p: natural_sort_key(self.tree_local.item(p, "text")),
                reverse=self._dest_sort_desc
            )
            for idx, p in enumerate(parents):
                self.tree_local.move(p, "", idx)
        else:
            for parent in self.tree_local.get_children(""):
                children = list(self.tree_local.get_children(parent))
                def get_local_val(item_id):
                    vals = self.tree_local.item(item_id, "values")
                    if not vals:
                        return 0
                    if col == "name":
                        return natural_sort_key(vals[0])
                    elif col == "size":
                        fname = vals[0]
                        for fc in self._dest_files_cache:
                            if fc["name"] == fname:
                                return fc["size"]
                        return 0
                    elif col == "date":
                        try:
                            return datetime.strptime(vals[2], "%d/%m/%Y %H:%M")
                        except Exception:
                            return vals[2]
                    return 0

                children.sort(key=get_local_val, reverse=self._dest_sort_desc)
                for idx, ch in enumerate(children):
                    self.tree_local.move(ch, parent, idx)

        # Atualiza a ordenação no cache para o modo de miniaturas
        if self._dest_files_cache:
            if col == "name":
                self._dest_files_cache.sort(key=lambda x: natural_sort_key(x["name"]), reverse=self._dest_sort_desc)
            elif col == "size":
                self._dest_files_cache.sort(key=lambda x: x["size"], reverse=self._dest_sort_desc)
            elif col == "date":
                self._dest_files_cache.sort(key=lambda x: x.get("mtime", ""), reverse=self._dest_sort_desc)
            elif col == "#0":
                self._dest_files_cache.sort(key=lambda x: natural_sort_key(x.get("folder", "")), reverse=self._dest_sort_desc)

        if self.var_dest_view.get() in ("🖼️ Miniaturas", "🔍 Miniaturas Gigantes"):
            self._render_dest_grid()

    def _update_dest_disk_space(self):
        """Atualiza a exibição de espaço livre restante no disco de destino."""
        dest = self.var_dest_dir.get().strip()
        if not dest:
            self.var_dest_disk_free.set("💾 Livre: --")
            return

        check_path = Path(dest)
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent

        if not check_path.exists():
            self.var_dest_disk_free.set("💾 Livre: --")
            return

        try:
            usage = shutil.disk_usage(check_path)
            free_str = format_size(usage.free)
            total_str = format_size(usage.total)
            self.var_dest_disk_free.set(f"💾 Livre: {free_str} (de {total_str})")

            if hasattr(self, "lbl_dest_disk_free") and self.lbl_dest_disk_free:
                if usage.free < 2 * 1024 * 1024 * 1024:  # < 2 GB
                    self.lbl_dest_disk_free.config(foreground="#dc2626")
                elif usage.free < 10 * 1024 * 1024 * 1024:  # < 10 GB
                    self.lbl_dest_disk_free.config(foreground="#d97706")
                else:
                    self.lbl_dest_disk_free.config(foreground="#16a34a")
        except Exception:
            self.var_dest_disk_free.set("💾 Livre: --")

    def _refresh_local_view(self):
        self._update_dest_disk_space()
        dest = Path(self.var_dest_dir.get())
        for row in self.tree_local.get_children():
            self.tree_local.delete(row)

        self._dest_files_cache = []

        if not dest.exists():
            self.var_summary_local.set("Diretório local inexistente.")
            if self.var_dest_view.get() in ("🖼️ Miniaturas", "🔍 Miniaturas Gigantes"):
                self._render_dest_grid()
            return

        total_files = 0
        total_size = 0

        # Lista pastas AAAA-MM-DD[-Local]
        try:
            subfolders = [p for p in dest.iterdir() if p.is_dir() and not p.name.startswith("_")]
            rev_folders = self._dest_sort_desc if self._dest_sort_col == "#0" else True
            for sdir in sorted(subfolders, key=lambda p: natural_sort_key(p.name), reverse=rev_folders):
                node_id = self.tree_local.insert("", tk.END, text=f"📁 {sdir.name}", open=False)
                files = [f for f in sdir.iterdir() if f.is_file()]

                if self._dest_sort_col == "name":
                    files.sort(key=lambda f: natural_sort_key(f.name), reverse=self._dest_sort_desc)
                elif self._dest_sort_col == "size":
                    files.sort(key=lambda f: f.stat().st_size, reverse=self._dest_sort_desc)
                elif self._dest_sort_col == "date":
                    files.sort(key=lambda f: f.stat().st_mtime, reverse=self._dest_sort_desc)
                else:
                    files.sort(key=lambda f: natural_sort_key(f.name))

                for f in files:
                    total_files += 1
                    f_size = f.stat().st_size
                    total_size += f_size
                    mtime_str = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
                    self.tree_local.insert(node_id, tk.END, values=(f.name, format_size(f_size), mtime_str))
                    self._dest_files_cache.append({
                        "name": f.name,
                        "path": str(f),
                        "size": f_size,
                        "mtime": mtime_str,
                        "folder": sdir.name
                    })
        except Exception as e:
            self._log_console(f"Erro ao ler diretório local: {e}", "Erro:")

        self.var_summary_local.set(f"{len(subfolders)} pastas | {total_files} arquivos salvos ({format_size(total_size)})")

        if self.var_dest_view.get() in ("🖼️ Miniaturas", "🔍 Miniaturas Gigantes"):
            self._render_dest_grid()

    # --- Download Estilo FileZilla ---
    def _start_download_selected(self):
        selected_pairs = self._get_selected_items()
        if not selected_pairs:
            messagebox.showwarning("Aviso", "Nenhum arquivo selecionado na lista do iPhone.")
            return

        selected_files = [it for idx, it in selected_pairs]
        dest = self.var_dest_dir.get().strip()
        if not dest:
            messagebox.showwarning("Aviso", "Informe a pasta local de destino.")
            return

        self._add_recent_path(dest)

        total_batch_bytes = sum(f.get("size", 0) for f in selected_files)
        try:
            free_disk = shutil.disk_usage(dest).free
            if total_batch_bytes > free_disk:
                self._log_console(
                    f"⚠️ AVISO DE ESPAÇO: O lote total requer {format_size(total_batch_bytes)}, mas o disco possui apenas {format_size(free_disk)} livres em '{dest}'.",
                    "Aviso Disco:"
                )
        except Exception:
            pass

        # Preenche a aba Fila de Transferência
        for row in self.tree_queue.get_children():
            self.tree_queue.delete(row)
        for it in selected_files:
            self.tree_queue.insert("", tk.END, values=(it["name"], format_size(it["size"]), it["folder_name"], dest, "Na Fila"))

        self.nb_bottom.tab(0, text=f" Fila de Transferência ({len(selected_files)}) ")
        self.nb_bottom.select(0)

        self.btn_download.config(state=tk.DISABLED)
        self.btn_delete.config(state=tk.DISABLED)
        self.btn_cancel.config(state=tk.NORMAL)
        if hasattr(self, "btn_pause"):
            self.btn_pause.config(state=tk.NORMAL, text="⏸️ Pausar")
        self.cancel_event.clear()
        self.pause_event.clear()
        self._save_config()

        custom_local = self.var_custom_local.get().strip()
        use_gps = self.var_use_gps.get()
        skip_existing = self.var_skip_existing.get()

        threading.Thread(
            target=self._download_worker,
            args=(selected_files, dest, custom_local, use_gps, skip_existing),
            daemon=True
        ).start()

    def _download_single_selected(self):
        sel = self.tree_iphone.selection()
        if not sel:
            return
        idx = int(sel[0])
        it = self.iphone_items[idx]
        dest = self.var_dest_dir.get().strip()
        if dest:
            self._add_recent_path(dest)
        self.btn_cancel.config(state=tk.NORMAL)
        if hasattr(self, "btn_pause"):
            self.btn_pause.config(state=tk.NORMAL, text="⏸️ Pausar")
        self.cancel_event.clear()
        self.pause_event.clear()
        self._save_config()

        custom_local = self.var_custom_local.get().strip()
        use_gps = self.var_use_gps.get()
        skip_existing = self.var_skip_existing.get()

        threading.Thread(
            target=self._download_worker,
            args=([it], dest, custom_local, use_gps, skip_existing),
            daemon=True
        ).start()

    def _download_worker(self, files, dest, custom_local, use_gps, skip_existing):
        total_files = len(files)
        total_bytes = sum(f.get("size", 0) for f in files)
        downloaded_bytes = 0
        start_time = time.time()

        self._safe_call(lambda: self.var_progress_val.set(0.0))
        self._safe_call(lambda: self.var_pct_label.set("0.0%"))
        self._safe_call(lambda: self.var_file_progress_val.set(0.0))
        self._safe_call(lambda: self.var_file_pct_label.set("0.0%"))
        self._safe_call(lambda: self.var_file_status.set("Preparando transferência..."))

        self._log_console(f"Iniciando transferência de {total_files} arquivos ({format_size(total_bytes)}) para {dest}...", "Transferência:")
        self._safe_call(lambda: self._set_transfer_anim_active(True))

        # Estado da decisão de conflito para este lote ("Fazer isso para todos os arquivos")
        batch_conflict_state = {
            "remember": False,
            "action": None
        }

        def resolve_conflict(file_info: dict, dest_path: Path) -> str:
            # Se o usuário já marcou "Fazer isso para todos os arquivos" anteriormente neste lote
            if batch_conflict_state["remember"] and batch_conflict_state["action"]:
                return batch_conflict_state["action"]

            resp_q = queue.Queue()
            self._safe_call(lambda: self._show_conflict_dialog(file_info, dest_path, resp_q))
            action, remember = resp_q.get()

            if remember:
                batch_conflict_state["remember"] = True
                batch_conflict_state["action"] = action

            return action

        def resolve_disk_full(file_info: dict, free_b: int, req_b: int) -> str:
            fname = file_info.get("name", "arquivo")
            diff_b = max(0, req_b - free_b)
            self._log_console(
                f"❌ ESPAÇO EM DISCO INSUFICIENTE: '{fname}' requer {format_size(req_b)}, mas restam apenas {format_size(free_b)} em '{dest}' (faltam {format_size(diff_b)}).",
                "Disco Cheio:"
            )
            self._safe_call(lambda: self._add_failed_entry(fname, "Disco Cheio", f"{format_size(free_b)} livres / requer {format_size(req_b)}"))

            resp_q = queue.Queue()
            self._safe_call(lambda: self._show_disk_full_dialog(file_info, free_b, req_b, dest, resp_q))
            action = resp_q.get()

            if action == "pause":
                self._safe_call(lambda: self.btn_pause.config(state=tk.NORMAL, text="▶️ Continuar"))
                self._safe_call(lambda: self.var_status_msg.set(f"⏸️ Transferência pausada: falta espaço em disco para '{fname}'."))
                self._safe_call(lambda: self._log_console(
                    f"Transferência pausada. Libere pelo menos {format_size(diff_b)} em '{dest}' e clique em '▶️ Continuar' na barra de ferramentas.",
                    "Aguardando Espaço:"
                ))
            elif action == "cancel":
                self._safe_call(lambda: self._cancel_task())

            return action

        def on_file_prog(cur_fname: str, cur_bytes: int, tot_bytes: int):
            if self.cancel_event.is_set():
                return
            if tot_bytes > 0:
                f_pct = min(100.0, (cur_bytes / tot_bytes) * 100.0)
                f_pct_str = f"{f_pct:.1f}%"
                f_status = f"{cur_fname} ({format_size(cur_bytes)} / {format_size(tot_bytes)})"
            else:
                f_pct = 100.0
                f_pct_str = "100%"
                f_status = cur_fname
            self._safe_call(lambda p=f_pct, ps=f_pct_str, st=f_status: self._update_file_progress(p, ps, st))

        def on_prog(res, cur, tot):
            if self.cancel_event.is_set():
                return
            nonlocal downloaded_bytes
            fname = res.get("file", "")
            folder = res.get("folder", "")
            status = res.get("status", "")
            fsize = res.get("size", 0)
            if status == "success":
                downloaded_bytes += fsize

            elapsed = max(0.001, time.time() - start_time)
            speed = downloaded_bytes / elapsed if elapsed > 0.3 else 0.0
            speed_str = f"{format_size(speed)}/s"

            pct = (cur / tot) * 100 if tot > 0 else 0

            if speed > 0 and total_bytes > downloaded_bytes:
                eta_sec = (total_bytes - downloaded_bytes) / speed
                eta_str = f"Restante: {int(eta_sec // 60):02d}:{int(eta_sec % 60):02d}"
            else:
                eta_str = "--:--"

            stats_str = f"{cur}/{tot} arquivos | {speed_str} | {eta_str}"
            pct_str = f"{pct:.1f}%"

            if status == "success":
                self._log_console(f"✔ Transferência concluída: {fname} -> {folder} ({speed_str})", "226:")
                self._safe_call(lambda: self._add_done_entry(fname, fsize, folder))
                self._safe_call(lambda fn=fname: self._update_file_progress(100.0, "100%", f"{fn} (Concluído)"))
                self._safe_call(self._update_dest_disk_space)
            elif status == "skipped":
                self._log_console(f"⏭️ Arquivo já existe no destino: {fname}", "Aviso:")
                self._safe_call(lambda: self._add_failed_entry(fname, "Pulado", "Arquivo já existe no destino"))
                self._safe_call(lambda fn=fname: self._update_file_progress(100.0, "100%", f"{fn} (Pulado)"))
            else:
                self._log_console(f"❌ Falha ao transferir {fname}: {res.get('message', '')}", "550 Erro:")
                self._safe_call(lambda: self._add_failed_entry(fname, "Erro", res.get("message", "Falha")))
                self._safe_call(lambda fn=fname: self._update_file_progress(0.0, "Erro", f"{fn} (Falha)"))

            self._safe_call(lambda: self._update_transfer_progress(cur, tot, pct, pct_str, stats_str, fname))
            self._safe_call(lambda s=speed_str: self._update_transfer_speed(s))

        try:
            stats = self.manager.download_batch(
                files_to_download=files,
                target_base_dir=dest,
                custom_local=custom_local,
                use_gps=use_gps,
                skip_existing=skip_existing,
                conflict_resolver=resolve_conflict,
                progress_callback=on_prog,
                cancel_event=self.cancel_event,
                pause_event=self.pause_event,
                file_progress_callback=on_file_prog,
                disk_full_resolver=resolve_disk_full
            )
            self._safe_call(lambda: self._on_download_complete(stats))
        finally:
            self._safe_call(lambda: self.var_custom_local.set(""))

    def _update_file_progress(self, val: float, pct_str: str, status_str: str):
        self.var_file_progress_val.set(val)
        self.var_file_pct_label.set(pct_str)
        self.var_file_status.set(status_str)

    def _update_transfer_progress(self, cur, tot, pct, pct_str, stats_str, fname):
        self.var_progress_val.set(pct)
        self.var_pct_label.set(pct_str)
        self.var_progress_stats.set(stats_str)
        self.var_status_msg.set(f"Baixando ({cur}/{tot}): {fname}")

    def _add_done_entry(self, fname, size, folder):
        t_str = datetime.now().strftime("%H:%M:%S")
        self.tree_done.insert("", 0, values=(fname, format_size(size), folder, t_str))
        count = len(self.tree_done.get_children())
        self.nb_bottom.tab(1, text=f" Concluídos ({count}) ")

    def _add_failed_entry(self, fname, status, reason):
        self.tree_failed.insert("", 0, values=(fname, status, reason))
        count = len(self.tree_failed.get_children())
        self.nb_bottom.tab(2, text=f" Pulados / Falhas ({count}) ")

    def _on_download_complete(self, stats):
        self._set_transfer_anim_active(False)
        self.btn_download.config(state=tk.NORMAL)
        self.btn_delete.config(state=tk.NORMAL)
        self.btn_cancel.config(state=tk.DISABLED)
        if hasattr(self, "btn_pause"):
            self.btn_pause.config(state=tk.DISABLED, text="⏸️ Pausar")
        self.pause_event.clear()
        self.var_custom_local.set("")  # Limpa a etiqueta ao término da cópia

        is_cancelled = stats.get("cancelled", False) or self.cancel_event.is_set()
        self.cancel_event.clear()

        # Atualiza itens restantes na fila de transferência para "Cancelado"
        if is_cancelled:
            for item_id in self.tree_queue.get_children():
                vals = list(self.tree_queue.item(item_id, "values"))
                if len(vals) >= 5 and vals[4] == "Na Fila":
                    vals[4] = "Cancelado"
                    self.tree_queue.item(item_id, values=vals)

        self._refresh_local_view()

        if is_cancelled:
            self.var_progress_val.set(0.0)
            self.var_pct_label.set("0.0%")
            self.var_file_progress_val.set(0.0)
            self.var_file_pct_label.set("0.0%")
            self.var_file_status.set("Pronto para transferir.")
            self.var_progress_stats.set("")
            self.var_status_msg.set(f"Operação cancelada ({stats['success']}/{stats['total']} baixados).")
            self._log_console(
                f"Transferência cancelada pelo usuário. Baixados: {stats['success']}/{stats['total']}.",
                "Cancelado:"
            )
            messagebox.showwarning(
                "Transferência Cancelada",
                f"A transferência foi cancelada pelo usuário.\n\n"
                f"✔ Baixados antes do cancelamento: {stats['success']} ({format_size(stats['total_bytes'])})\n"
                f"⏭️ Pulados: {stats['skipped']}\n"
                f"⏹️ Restantes não baixados: {stats['total'] - stats['success'] - stats['skipped']}"
            )
        else:
            self.var_progress_val.set(100)
            self.var_pct_label.set("100%")
            self.var_file_progress_val.set(100.0)
            self.var_file_pct_label.set("100%")
            self.var_file_status.set("Concluído.")
            self.var_progress_stats.set(f"Concluído: {stats['success']}/{stats['total']} arquivos ({format_size(stats['total_bytes'])})")
            self.var_status_msg.set("Transferência finalizada.")
            self._play_sound_notification()

            msg = f"Transferência finalizada!\n\n✔ Baixados: {stats['success']} ({format_size(stats['total_bytes'])})\n⏭️ Pulados: {stats['skipped']}\n❌ Falhas: {stats['errors']}"
            self._log_console(f"Lote finalizado: {stats['success']} baixados, {stats['skipped']} pulados, {stats['errors']} falhas.", "Status:")
            messagebox.showinfo("Transferência Concluída", msg)

    def _show_conflict_dialog(self, file_info: dict, dest_path: Path, resp_q: queue.Queue):
        """
        Exibe janela modal de confirmação de conflito de arquivo no destino.
        Oferece opções de Substituir, Pular/Ignorar ou Cancelar, com checkbox
        'Fazer isso para todos os arquivos' perfeitamente funcional em lote.
        """
        fname = file_info.get("name", dest_path.name)
        top = tk.Toplevel(self.root)
        top.title("Arquivo Já Existe no Destino")
        top.geometry("530x290")
        top.resizable(False, False)
        top.transient(self.root)
        top.grab_set()

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - 530) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - 290) // 2
            top.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        f_main = ttk.Frame(top, padding=16)
        f_main.pack(fill=tk.BOTH, expand=True)

        f_header = ttk.Frame(f_main)
        f_header.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(f_header, text="⚠️", font=("Segoe UI", 26)).pack(side=tk.LEFT, padx=(0, 12))
        lbl_title = ttk.Label(
            f_header,
            text=f"O arquivo '{fname}' já existe na pasta de destino.",
            font=("Segoe UI", 10, "bold"),
            wraplength=420
        )
        lbl_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        f_info = ttk.LabelFrame(f_main, text=" Detalhes do Arquivo ", padding=8)
        f_info.pack(fill=tk.X, pady=(0, 10))

        orig_size_str = format_size(file_info.get("size", 0))
        orig_date_str = file_info.get("date", "")
        dest_size = dest_path.stat().st_size if dest_path.exists() else 0
        dest_size_str = format_size(dest_size)
        try:
            dest_mtime = datetime.fromtimestamp(dest_path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        except Exception:
            dest_mtime = "Desconhecido"

        ttk.Label(f_info, text=f"• Origem: {fname} ({orig_size_str}) - Data: {orig_date_str}", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=1)
        ttk.Label(f_info, text=f"• Destino: {dest_path.name} ({dest_size_str}) - Modificado: {dest_mtime}", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=1)

        # Checkbox "Fazer isso para todos os arquivos" (marcado por padrão)
        var_remember = tk.BooleanVar(value=True)
        chk_remember = ttk.Checkbutton(
            f_main,
            text="Fazer isso para todos os arquivos (aplicar aos próximos conflitos)",
            variable=var_remember
        )
        chk_remember.pack(anchor=tk.W, pady=(4, 14))

        f_buttons = ttk.Frame(f_main)
        f_buttons.pack(fill=tk.X, side=tk.BOTTOM)

        def on_action(act: str):
            top.grab_release()
            top.destroy()
            resp_q.put((act, var_remember.get()))

        btn_cancel = tk.Button(
            f_buttons,
            text="Cancelar",
            command=lambda: on_action("cancel"),
            padx=10,
            pady=4,
            relief=tk.RAISED
        )
        btn_cancel.pack(side=tk.RIGHT, padx=4)

        btn_skip = tk.Button(
            f_buttons,
            text="Pular / Ignorar",
            command=lambda: on_action("skip"),
            padx=12,
            pady=4,
            relief=tk.RAISED
        )
        btn_skip.pack(side=tk.RIGHT, padx=4)

        btn_replace = tk.Button(
            f_buttons,
            text="Substituir",
            command=lambda: on_action("overwrite"),
            bg="#0275d8",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=4,
            relief=tk.RAISED
        )
        btn_replace.pack(side=tk.RIGHT, padx=4)

        top.protocol("WM_DELETE_WINDOW", lambda: on_action("cancel"))

    def _show_disk_full_dialog(self, file_info: dict, free_bytes: int, required_bytes: int, dest_dir: str, resp_q: queue.Queue):
        """
        Exibe janela modal de aviso quando o espaço em disco é insuficiente para copiar um arquivo.
        Oferece opções para Pausar a transferência (permitindo liberar espaço e continuar) ou Cancelar.
        """
        fname = file_info.get("name", "Arquivo")
        top = tk.Toplevel(self.root)
        top.title("⚠️ Espaço em Disco Insuficiente")
        top.geometry("540x310")
        top.resizable(False, False)
        top.transient(self.root)
        top.grab_set()

        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - 540) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - 310) // 2
            top.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        f_main = ttk.Frame(top, padding=16)
        f_main.pack(fill=tk.BOTH, expand=True)

        f_header = ttk.Frame(f_main)
        f_header.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(f_header, text="💾 ⚠️", font=("Segoe UI", 24)).pack(side=tk.LEFT, padx=(0, 12))
        lbl_title = ttk.Label(
            f_header,
            text=f"Espaço insuficiente no disco para copiar '{fname}'!",
            font=("Segoe UI", 10, "bold"),
            foreground="#d9534f",
            wraplength=420
        )
        lbl_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        f_info = ttk.LabelFrame(f_main, text=" Detalhes do Disco de Destino ", padding=10)
        f_info.pack(fill=tk.X, pady=(0, 12))

        diff_bytes = max(0, required_bytes - free_bytes)
        ttk.Label(f_info, text=f"• Destino: {dest_dir}", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=1)
        ttk.Label(f_info, text=f"• Tamanho do arquivo: {format_size(required_bytes)}", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=1)
        ttk.Label(f_info, text=f"• Espaço livre no disco: {format_size(free_bytes)}", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=1)
        ttk.Label(f_info, text=f"• Espaço adicional necessário: {format_size(diff_bytes)}", font=("Segoe UI", 9, "bold"), foreground="#c9302c").pack(anchor=tk.W, pady=1)

        ttk.Label(
            f_main,
            text="Você pode PAUSAR para liberar espaço no disco (apagar arquivos/esvaziar lixeira)\ne depois clicar em '▶️ Continuar' na barra de ferramentas, ou CANCELAR a operação.",
            font=("Segoe UI", 8),
            foreground="#555555",
            wraplength=500
        ).pack(anchor=tk.W, pady=(0, 12))

        f_buttons = ttk.Frame(f_main)
        f_buttons.pack(fill=tk.X, side=tk.BOTTOM)

        def on_action(act: str):
            top.grab_release()
            top.destroy()
            resp_q.put(act)

        btn_cancel = tk.Button(
            f_buttons,
            text="⛔ Cancelar Transferência",
            command=lambda: on_action("cancel"),
            padx=12,
            pady=4,
            relief=tk.RAISED
        )
        btn_cancel.pack(side=tk.RIGHT, padx=4)

        btn_pause = tk.Button(
            f_buttons,
            text="⏸️ Pausar Transferência (Liberar Espaço)",
            command=lambda: on_action("pause"),
            bg="#f0ad4e",
            fg="#222222",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=4,
            relief=tk.RAISED
        )
        btn_pause.pack(side=tk.RIGHT, padx=4)

        top.protocol("WM_DELETE_WINDOW", lambda: on_action("cancel"))

    # --- Exclusão da Origem (iPhone ou Pasta Local) ---
    def _confirm_delete_selected(self):
        selected_pairs = self._get_selected_items()
        if not selected_pairs:
            messagebox.showwarning("Aviso", "Nenhum arquivo selecionado na lista de origem.")
            return

        selected_files = [it for idx, it in selected_pairs]
        count = len(selected_files)
        sample_names = ", ".join([f["name"] for f in selected_files[:3]])
        if count > 3:
            sample_names += f" e mais {count - 3} arquivos..."

        is_ip = self.var_source_type.get() == "📱 Apple iPhone (USB)"
        target_name = "do seu iPhone" if is_ip else "da pasta de origem local"
        title = "⚠️ Confirmar Exclusão no iPhone" if is_ip else "⚠️ Confirmar Exclusão de Arquivos"

        confirm = messagebox.askyesno(
            title,
            f"ATENÇÃO: Você tem certeza de que deseja EXCLUIR PERMANENTEMENTE {count} arquivo(s) selecionado(s) {target_name}?\n\n"
            f"Arquivos: {sample_names}\n\n"
            f"Esta operação removerá os arquivos e NÃO poderá ser desfeita.",
            icon=messagebox.WARNING
        )

        if not confirm:
            return

        self.btn_download.config(state=tk.DISABLED)
        self.btn_delete.config(state=tk.DISABLED)
        self.btn_cancel.config(state=tk.NORMAL)
        if hasattr(self, "btn_pause"):
            self.btn_pause.config(state=tk.NORMAL, text="⏸️ Pausar")
        self.cancel_event.clear()
        self.pause_event.clear()

        threading.Thread(target=self._delete_worker, args=(selected_files,), daemon=True).start()

    def _delete_single_selected(self):
        sel = self.tree_iphone.selection()
        if not sel:
            return
        idx = int(sel[0])
        it = self.iphone_items[idx]

        is_ip = self.var_source_type.get() == "📱 Apple iPhone (USB)"
        target_name = "do iPhone" if is_ip else "da pasta de origem"
        title = "⚠️ Excluir do iPhone" if is_ip else "⚠️ Excluir da Origem"

        confirm = messagebox.askyesno(
            title,
            f"Deseja excluir permanentemente o arquivo '{it['name']}' {target_name}?",
            icon=messagebox.WARNING
        )
        if confirm:
            self.btn_cancel.config(state=tk.NORMAL)
            if hasattr(self, "btn_pause"):
                self.btn_pause.config(state=tk.NORMAL, text="⏸️ Pausar")
            self.cancel_event.clear()
            self.pause_event.clear()
            threading.Thread(target=self._delete_worker, args=([it],), daemon=True).start()

    def _remove_file_from_view(self, fname: str):
        """Remove o arquivo apagado imediatamente da tabela visual e da memória."""
        for iid in list(self.tree_iphone.get_children()):
            vals = self.tree_iphone.item(iid, "values")
            if vals and len(vals) > 1 and fname in vals[1]:
                self.tree_iphone.delete(iid)
                break

        self.iphone_items = [it for it in self.iphone_items if it["name"] != fname]
        self.displayed_items = [(idx, it) for idx, it in self.displayed_items if it["name"] != fname]

        if self.var_prev_name.get() == fname:
            self.var_prev_name.set("Nenhum item selecionado")
            self.var_prev_date.set("-")
            self.var_prev_size.set("-")
            self.var_prev_loc.set("-")
            self.lbl_thumb.config(image="", text="Selecione um item\npara ver a miniatura")

        self._update_selection_summary()

    def _delete_worker(self, files):
        self._log_console(f"Iniciando exclusão de {len(files)} arquivo(s) no iPhone...", "Comando DELE:")
        start_time = time.time()

        def on_prog(fname, cur, tot, success):
            pct = (cur / tot) * 100 if tot > 0 else 0
            elapsed = max(0.001, time.time() - start_time)
            speed = cur / elapsed if elapsed > 0.3 else 0.0
            stats_str = f"{cur}/{tot} arquivos | {speed:.1f} arq/s"

            if success:
                self._log_console(f"✔ 250 Excluído com sucesso: {fname}", "iPhone:")
                self._safe_call(lambda f=fname: self._remove_file_from_view(f))
            else:
                self._log_console(f"❌ 550 Falha ao excluir: {fname}", "iPhone:")

            self._safe_call(lambda: (
                self.var_progress_val.set(pct),
                self.var_pct_label.set(f"{pct:.1f}%"),
                self.var_progress_stats.set(stats_str),
                self.var_status_msg.set(f"Excluindo ({cur}/{tot}): {fname}")
            ))

        try:
            stats = self.manager.delete_batch(files, progress_callback=on_prog, cancel_event=self.cancel_event, pause_event=self.pause_event)
            self._safe_call(lambda: self._on_delete_complete(stats))
        finally:
            self._safe_call(lambda: self.var_custom_local.set(""))

    def _on_delete_complete(self, stats):
        self.btn_download.config(state=tk.NORMAL)
        self.btn_delete.config(state=tk.NORMAL)
        self.btn_cancel.config(state=tk.DISABLED)
        if hasattr(self, "btn_pause"):
            self.btn_pause.config(state=tk.DISABLED, text="⏸️ Pausar")
        self.pause_event.clear()
        self.var_custom_local.set("")  # Limpa a etiqueta temporária

        is_cancelled = stats.get("cancelled", False) or self.cancel_event.is_set()
        self.cancel_event.clear()

        if is_cancelled:
            self.var_progress_val.set(0.0)
            self.var_pct_label.set("0.0%")
            self.var_file_progress_val.set(0.0)
            self.var_file_pct_label.set("0.0%")
            self.var_file_status.set("Pronto para transferir.")
            self.var_progress_stats.set("")
            self.var_status_msg.set(f"Exclusão cancelada ({stats['deleted']}/{stats['total']} apagados).")
            self._log_console(f"Exclusão cancelada pelo usuário: {stats['deleted']} apagados, {stats['total'] - stats['deleted']} mantidos.", "Cancelado:")
            messagebox.showwarning(
                "Exclusão Cancelada",
                f"A exclusão foi cancelada pelo usuário.\n\n"
                f"🗑️ Apagados antes do cancelamento: {stats['deleted']}\n"
                f"⏹️ Restantes mantidos: {stats['total'] - stats['deleted']}"
            )
        else:
            self.var_progress_val.set(100)
            self.var_pct_label.set("100%")
            self.var_progress_stats.set(f"{stats['deleted']}/{stats['total']} apagados")
            self.var_status_msg.set(f"Exclusão finalizada: {stats['deleted']} arquivos apagados.")
            self._play_sound_notification()

            self._log_console(f"Fim da exclusão: {stats['deleted']} apagados com sucesso, {stats['failed']} falhas.", "Status:")
            messagebox.showinfo(
                "Exclusão Concluída",
                f"Exclusão finalizada!\n\n🗑️ Apagados do iPhone: {stats['deleted']}\n❌ Falhas: {stats['failed']}"
            )

    def _cancel_task(self):
        """Cancela a operação em andamento, despausa se necessário e limpa a etiqueta temporária."""
        self.cancel_event.set()
        if hasattr(self, "pause_event"):
            self.pause_event.clear()
        if hasattr(self, "btn_pause"):
            self.btn_pause.config(state=tk.DISABLED, text="⏸️ Pausar")
        self.btn_cancel.config(state=tk.DISABLED)
        self.btn_download.config(state=tk.NORMAL)
        self.btn_delete.config(state=tk.NORMAL)
        self.var_custom_local.set("")
        self.var_file_progress_val.set(0.0)
        self.var_file_pct_label.set("0.0%")
        self.var_file_status.set("Cancelado.")
        self._set_transfer_anim_active(False)
        self._log_console("Cancelamento solicitado pelo usuário. Finalizando operação...", "ABOR:")
        self.var_status_msg.set("Cancelando...")

    def _refresh_orig_view(self):
        """Atualiza os arquivos do visualizador da Origem (iPhone ou Pasta Local)."""
        if self.var_source_type.get() == "📁 Pasta / Disco Local":
            self._start_scan_async()
        else:
            self._auto_connect_async()

    def _refresh_all(self):
        """Atualiza ambos os visualizadores (Origem e Destino)."""
        self._refresh_orig_view()
        self._refresh_local_view()

    # --- Filtros Avançados ---
    def _open_filter_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Filtros Avançados de Mídia & Período")
        dlg.geometry("380x300")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        f = ttk.Frame(dlg, padding="15")
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="Tipos de Mídia:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 4))
        ttk.Checkbutton(f, text="Incluir Fotos (JPG, HEIC, PNG)", variable=self.var_inc_photos).pack(anchor=tk.W)
        ttk.Checkbutton(f, text="Incluir Vídeos (MOV, MP4)", variable=self.var_inc_videos).pack(anchor=tk.W)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        ttk.Label(f, text="Intervalo de Datas (AAAA-MM-DD):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 4))
        ttk.Checkbutton(f, text="Ativar Filtro por Intervalo de Datas", variable=self.var_filter_by_date).pack(anchor=tk.W, pady=(0, 4))
        f_dates = ttk.Frame(f)
        f_dates.pack(fill=tk.X, pady=4)
        ttk.Label(f_dates, text="De:").pack(side=tk.LEFT)
        ttk.Entry(f_dates, textvariable=self.var_date_from, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(f_dates, text="Até:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(f_dates, textvariable=self.var_date_to, width=12).pack(side=tk.LEFT, padx=5)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        def apply_and_close():
            self._save_config()
            dlg.destroy()
            self._start_scan_async()

        f_btn = ttk.Frame(f)
        f_btn.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(f_btn, text="Aplicar Filtros", command=apply_and_close).pack(side=tk.RIGHT)
        ttk.Button(f_btn, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=5)


def main():
    root = tk.Tk()
    app = FileZillaIPhoneApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
