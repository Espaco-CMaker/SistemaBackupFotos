"""
Módulo para comunicação com o iPhone conectado via USB no Windows.
Utiliza a API de Windows Shell COM (MTP/WPD) para detecção de dispositivo,
leitura da pasta DCIM, filtragem por data, download e exclusão de fotos e vídeos.
"""

import os
import re
import time
import shutil
import tempfile
import threading
import pythoncom
import win32gui
import win32con
import win32com.client
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable
from PIL import Image

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

from scripts.geo_utils import get_folder_name, extract_gps, reverse_geocode, sanitize_name

def format_size(size_bytes: int) -> str:
    """Retorna o tamanho formatado em B, KB, MB ou GB."""
    if not size_bytes or size_bytes < 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"

# Diretório temporário para cache de miniaturas
THUMB_CACHE_DIR = Path(tempfile.gettempdir()) / "iphone_thumbs_cache"

# Tipos de arquivos suportados
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".png", ".raw", ".dng", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v"}
METADATA_EXTENSIONS = {".aae"}
ALL_MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

def parse_shell_date(raw_date: str, fallback_year_month: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Interpreta strings de datas retornadas pelo Windows Shell (ex: '31/05/2026 18:40').
    Retorna tupla (YYYY-MM-DD, HH:MM).
    """
    if not raw_date:
        if fallback_year_month and len(fallback_year_month) == 6:
            y = fallback_year_month[:4]
            m = fallback_year_month[4:6]
            return f"{y}-{m}-01", "00:00"
        return None, None

    clean = re.sub(r"[^\d/:\-\s]", "", raw_date).strip()

    # Formato DD/MM/AAAA HH:MM ou DD/MM/AAAA HH:MM:SS
    match_br = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:\s+(\d{1,2}):(\d{1,2}))?", clean)
    if match_br:
        day = int(match_br.group(1))
        month = int(match_br.group(2))
        year = int(match_br.group(3))
        hour = int(match_br.group(4)) if match_br.group(4) else 0
        minute = int(match_br.group(5)) if match_br.group(5) else 0
        return f"{year:04d}-{month:02d}-{day:02d}", f"{hour:02d}:{minute:02d}"

    # Formato AAAA-MM-DD HH:MM
    match_iso = re.search(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2}))?", clean)
    if match_iso:
        year = int(match_iso.group(1))
        month = int(match_iso.group(2))
        day = int(match_iso.group(3))
        hour = int(match_iso.group(4)) if match_iso.group(4) else 0
        minute = int(match_iso.group(5)) if match_iso.group(5) else 0
        return f"{year:04d}-{month:02d}-{day:02d}", f"{hour:02d}:{minute:02d}"

    return None, None


def parse_shell_size(raw_size: str) -> int:
    """
    Converte strings de tamanho do Windows Shell (ex: '1,76 MB', '850 KB', '2,4 GB', '512 bytes')
    para quantidade inteira de bytes.
    """
    if not raw_size:
        return 0
    s = raw_size.replace('\u200e', '').replace('\u200f', '').replace('\xa0', ' ').strip()
    s = s.replace('.', '').replace(',', '.') if s.count(',') == 1 and '.' in s else s.replace(',', '.')
    m = re.search(r'([\d.]+)\s*([a-zA-Z]+)?', s)
    if not m:
        return 0
    try:
        num = float(m.group(1))
    except Exception:
        return 0
    unit = (m.group(2) or "").upper()
    if "GB" in unit:
        return int(num * 1024 * 1024 * 1024)
    elif "MB" in unit:
        return int(num * 1024 * 1024)
    elif "KB" in unit:
        return int(num * 1024)
    return int(num)


class IPhoneManager:
    """Gerenciador de conexão, visualização, download e exclusão de fotos e vídeos do iPhone."""

    def __init__(self):
        self.device_name: Optional[str] = None
        self.dcim_folder = None
        self.folders_cache: List[Dict] = []
        self._is_connected: bool = False
        self._date_location_cache: Dict[str, str] = {}

    def check_usb_presence(self) -> bool:
        """
        Verifica via WMI se o hardware do iPhone (Vendor ID 05AC da Apple) está presente
        e ativo na porta USB do Windows, mesmo que o iOS ainda não tenha montado o MTP.
        """
        try:
            pythoncom.CoInitialize()
            wmi = win32com.client.GetObject("winmgmts:")
            devs = wmi.ExecQuery("SELECT Name, Status FROM Win32_PnPEntity WHERE DeviceID LIKE '%VID_05AC%' AND Status = 'OK'")
            return devs.Count > 0
        except Exception:
            return False

    def connect(self) -> bool:
        """
        Detecta e conecta ao iPhone conectado via USB.
        Retorna True se encontrado e acessível com pasta DCIM.
        """
        pythoncom.CoInitialize()
        self._is_connected = False
        self.device_name = None
        self.dcim_folder = None
        self.folders_cache = []

        try:
            shell = win32com.client.Dispatch("Shell.Application")
            pc = shell.NameSpace(17) # ssfDRIVES / Este Computador
            if not pc:
                return False

            for item in pc.Items():
                name = item.Name
                path = getattr(item, "Path", "")
                # Ignora unidades locais e de rede normais (C:\, D:\, G:\, etc.) para máxima velocidade
                if (len(path) >= 2 and path[0].isalpha() and path[1] == ":") or path.startswith(r"\\"):
                    continue

                type_str = ""
                try:
                    type_str = (item.Type or "").lower()
                except Exception:
                    pass
                name_lower = name.lower()
                is_candidate = (
                    "iphone" in name_lower or
                    "apple" in name_lower or
                    "dispositivo portátil" in type_str or
                    "dispositivo portatil" in type_str or
                    "portable device" in type_str
                )
                if not is_candidate:
                    continue

                try:
                    storage = item.GetFolder
                except Exception:
                    continue
                if not storage:
                    continue
                
                for sub in storage.Items():
                    if sub.Name.upper() == "DCIM":
                        self.device_name = name
                        self.dcim_folder = sub.GetFolder
                        self._is_connected = True
                        self._index_folders()
                        return True

                    try:
                        sub_folder = sub.GetFolder
                    except Exception:
                        continue
                    if not sub_folder:
                        continue
                    
                    for dcim_candidate in sub_folder.Items():
                        if dcim_candidate.Name.upper() == "DCIM":
                            self.device_name = name
                            self.dcim_folder = dcim_candidate.GetFolder
                            self._is_connected = True
                            self._index_folders()
                            return True
                        elif re.match(r"^\d{4}\d{2}_", dcim_candidate.Name) or "APPLE" in dcim_candidate.Name.upper():
                            self.device_name = name
                            self.dcim_folder = sub_folder
                            self._is_connected = True
                            self._index_folders()
                            return True
            return False
        except Exception as e:
            print(f"Erro ao conectar com iPhone: {e}")
            return False

    def is_connected(self) -> bool:
        return self._is_connected and self.dcim_folder is not None

    def _index_folders(self) -> None:
        """Lê os nomes das subpastas da pasta DCIM para indexar anos e meses rapidamente."""
        self.folders_cache = []
        if not self.dcim_folder:
            return

        for folder_item in self.dcim_folder.Items():
            f_name = folder_item.Name
            folder_info = {
                "name": f_name,
                "item": folder_item,
                "folder_obj": folder_item.GetFolder,
                "year": None,
                "month": None,
                "ym": None
            }
            # Reconhece padrão YYYYMM_x (ex: 202605_a)
            match = re.match(r"^(\d{4})(\d{2})_", f_name)
            if match:
                folder_info["year"] = match.group(1)
                folder_info["month"] = match.group(2)
                folder_info["ym"] = f"{match.group(1)}-{match.group(2)}"
            
            self.folders_cache.append(folder_info)

    def get_available_years(self) -> List[str]:
        """Retorna lista ordenada descrescente de anos disponíveis (ex: ['2026', '2025'])."""
        years = set()
        for f in self.folders_cache:
            if f["year"]:
                years.add(f["year"])
        return sorted(list(years), reverse=True)

    def get_available_months(self, year: Optional[str] = None) -> List[str]:
        """Retorna lista ordenada descrescente de meses no formato 'AAAA-MM'."""
        months = set()
        for f in self.folders_cache:
            if f["ym"]:
                if year is None or f["year"] == year:
                    months.add(f["ym"])
        return sorted(list(months), reverse=True)

    def scan_photos(
        self,
        filter_years: Optional[List[str]] = None,
        filter_months: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        folder_filter: Optional[str] = None,
        include_photos: bool = True,
        include_videos: bool = True,
        include_aae: bool = False,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cancel_event = None
    ) -> List[Dict]:
        """
        Varre e lista fotos e vídeos do iPhone de acordo com os filtros especificados.
        """
        pythoncom.CoInitialize()
        results: List[Dict] = []
        
        if not self.dcim_folder:
            return results

        target_folders = []
        for f in self.folders_cache:
            ym = f["ym"]
            y = f["year"]
            
            if folder_filter and f["name"] != folder_filter:
                continue

            if not ym:
                target_folders.append(f)
                continue

            if filter_years and y not in filter_years:
                continue

            if filter_months and ym not in filter_months:
                continue

            if date_from and date_to:
                f_ym_prefix = f["ym"]
                month_start = f"{f_ym_prefix}-01"
                month_end = f"{f_ym_prefix}-31"
                if month_end < date_from or month_start > date_to:
                    continue

            target_folders.append(f)

        total_folders = len(target_folders)

        allowed_exts = set()
        if include_photos:
            allowed_exts |= PHOTO_EXTENSIONS
        if include_videos:
            allowed_exts |= VIDEO_EXTENSIONS
        if include_aae:
            allowed_exts |= METADATA_EXTENSIONS

        for f_idx, folder_info in enumerate(target_folders):
            if cancel_event and cancel_event.is_set():
                break

            folder_name = folder_info["name"]
            folder_obj = folder_info["folder_obj"]
            fallback_ym = folder_info["name"][:6] if folder_info["ym"] else None

            if progress_callback:
                progress_callback(f"Lendo pasta {folder_name} ({f_idx+1}/{total_folders})...", f_idx + 1, total_folders)

            # Detecta coluna de tamanho da pasta (geralmente col 2 no Windows)
            size_col = 2
            for c in (2, 1, 3):
                h = (folder_obj.GetDetailsOf(None, c) or "").lower()
                if "tamanho" in h or "size" in h:
                    size_col = c
                    break

            try:
                for item in folder_obj.Items():
                    if cancel_event and cancel_event.is_set():
                        break

                    name = item.Name
                    ext = os.path.splitext(name)[1].lower()

                    if allowed_exts and ext not in allowed_exts:
                        continue

                    raw_date = folder_obj.GetDetailsOf(item, 3) or folder_obj.GetDetailsOf(item, 4)
                    date_ymd, time_hm = parse_shell_date(raw_date, fallback_ym)

                    if not date_ymd:
                        continue

                    if date_from and date_ymd < date_from:
                        continue
                    if date_to and date_ymd > date_to:
                        continue

                    size = getattr(item, "Size", 0)
                    if not size or size == 0:
                        size_raw = folder_obj.GetDetailsOf(item, size_col)
                        size = parse_shell_size(size_raw)

                    results.append({
                        "name": name,
                        "ext": ext,
                        "date": date_ymd,
                        "time": time_hm or "00:00",
                        "size": size,
                        "raw_date": raw_date,
                        "folder_obj": folder_obj,
                        "item_obj": item,
                        "folder_name": folder_name
                    })
            except Exception as e:
                print(f"Erro ao ler itens da pasta {folder_name}: {e}")

        return results

    def scan_local_folder(
        self,
        folder_path: str,
        recursive: bool = True,
        filter_months: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_photos: bool = True,
        include_videos: bool = True,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cancel_event = None
    ) -> List[Dict]:
        """
        Varre e lista fotos e vídeos a partir de uma pasta ou disco local (PC, Cartão SD, Pen Drive).
        """
        results: List[Dict] = []
        base = Path(folder_path)
        if not base.exists() or not base.is_dir():
            return results

        allowed_exts = set()
        if include_photos:
            allowed_exts |= PHOTO_EXTENSIONS
        if include_videos:
            allowed_exts |= VIDEO_EXTENSIONS

        files: List[Path] = []
        try:
            if recursive:
                for root, dirs, fnames in os.walk(str(base)):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("$")]
                    for fname in fnames:
                        ext = os.path.splitext(fname)[1].lower()
                        if ext in allowed_exts:
                            files.append(Path(root) / fname)
            else:
                for entry in base.iterdir():
                    if entry.is_file() and entry.suffix.lower() in allowed_exts:
                        files.append(entry)
        except Exception as e:
            print(f"Erro ao listar pasta local: {e}")
            return results

        total = len(files)
        for idx, fpath in enumerate(files):
            if cancel_event and cancel_event.is_set():
                break

            if progress_callback and (idx % 25 == 0 or idx == total - 1):
                progress_callback(f"Lendo {fpath.name} ({idx+1}/{total})...", idx + 1, total)

            try:
                st = fpath.stat()
                mtime = datetime.fromtimestamp(st.st_mtime)
                date_ymd = mtime.strftime("%Y-%m-%d")
                time_hm = mtime.strftime("%H:%M")

                ext = fpath.suffix.lower()
                if ext in PHOTO_EXTENSIONS:
                    try:
                        with Image.open(str(fpath)) as im:
                            exif = im.getexif()
                            if exif:
                                dt_str = exif.get(306) or exif.get(36867)
                                if dt_str and isinstance(dt_str, str):
                                    parts = dt_str.split(" ")
                                    date_ymd = parts[0].replace(":", "-")
                                    if len(parts) > 1:
                                        time_hm = parts[1][:5]
                    except Exception:
                        pass

                ym = date_ymd[:7] if len(date_ymd) >= 7 else ""
                if filter_months and ym not in filter_months:
                    continue
                if date_from and date_ymd < date_from:
                    continue
                if date_to and date_ymd > date_to:
                    continue

                results.append({
                    "name": fpath.name,
                    "ext": ext,
                    "date": date_ymd,
                    "time": time_hm,
                    "size": st.st_size,
                    "raw_date": f"{date_ymd} {time_hm}",
                    "folder_obj": None,
                    "item_obj": None,
                    "folder_name": fpath.parent.name,
                    "local_path": str(fpath),
                    "is_local": True
                })
            except Exception:
                continue

        return results

    def get_months_from_items(self, items: List[Dict]) -> List[str]:
        """Extrai os meses únicos (AAAA-MM) de uma lista de itens de mídia."""
        months = set()
        for it in items:
            d = it.get("date", "")
            if len(d) >= 7:
                months.add(d[:7])
        return sorted(list(months), reverse=True)

    def _resolve_folder_name(self, date_ymd: str, custom_local: str) -> str:
        """Gera o nome da pasta destino respeitando se há localização em cache ou custom_local."""
        local = self._date_location_cache.get(date_ymd, "")
        if not local and custom_local:
            local = sanitize_name(custom_local)
        
        if local:
            return f"{date_ymd}-{sanitize_name(local)}"
        return date_ymd

    def get_file_thumbnail(self, file_info: Dict, thumb_size: Tuple[int, int] = (240, 240)) -> Optional[str]:
        """
        Gera e retorna o caminho de uma miniatura PNG local para a foto ou vídeo selecionado.
        Utiliza cache no disco para desempenho instantâneo em reexibições.
        """
        pythoncom.CoInitialize()
        filename = file_info["name"]
        ext = file_info["ext"]

        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        thumb_path = THUMB_CACHE_DIR / f"thumb_{Path(filename).stem}_{thumb_size[0]}.png"

        if thumb_path.exists() and thumb_path.stat().st_size > 0:
            return str(thumb_path)

        is_local = file_info.get("is_local") or file_info.get("local_path")
        if is_local:
            staging_file = Path(file_info["local_path"])
            if not staging_file.exists():
                return None
        else:
            staging_file = THUMB_CACHE_DIR / filename
            if not staging_file.exists() or staging_file.stat().st_size == 0:
                try:
                    if staging_file.exists():
                        staging_file.unlink(missing_ok=True)
                    shell_instance = win32com.client.Dispatch("Shell.Application")
                    ns = shell_instance.NameSpace(str(THUMB_CACHE_DIR))
                    ns.CopyHere(file_info["item_obj"], 4 | 16 | 512 | 1024)
                    
                    for _ in range(20):
                        if staging_file.exists() and staging_file.stat().st_size > 0:
                            break
                        time.sleep(0.05)
                except Exception:
                    return None

        if not staging_file.exists():
            return None

        try:
            if ext in VIDEO_EXTENSIONS:
                try:
                    import imageio.v3 as iio
                    frame = iio.imread(str(staging_file), index=0)
                    img = Image.fromarray(frame)
                    img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
                    img.save(str(thumb_path), format="PNG")
                    return str(thumb_path)
                except Exception:
                    pass

            with Image.open(str(staging_file)) as img:
                img = img.convert("RGB")
                img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
                img.save(str(thumb_path), format="PNG")
                return str(thumb_path)
        except Exception as e:
            print(f"Erro ao gerar miniatura de {filename}: {e}")
            return None

    def download_file(
        self,
        file_info: Dict,
        target_base_dir: str,
        custom_local: str = "",
        use_gps: bool = True,
        skip_existing: bool = True,
        conflict_resolver: Optional[Callable[[Dict, Path], str]] = None,
        shell_instance = None,
        file_progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cancel_event = None,
        pause_event = None
    ) -> Dict:
        """
        Baixa um arquivo do iPhone ou copia da pasta de origem local e salva na pasta
        `<target_base_dir>/AAAA-MM-DD[-Local]/<NomeDoArquivo>`.
        Trata conflitos de arquivos existentes de forma autônoma sem disparar
        janelas de diálogo repetitivas do Windows Shell.
        """
        date_ymd = file_info["date"]
        filename = file_info["name"]
        ext = file_info["ext"]
        expected_sz = file_info.get("size", 0)

        # Verificação prévia de espaço em disco no destino
        try:
            free_bytes = shutil.disk_usage(target_base_dir).free
            if expected_sz > 0 and free_bytes < (expected_sz + 20 * 1024 * 1024):
                return {
                    "status": "disk_full",
                    "file": filename,
                    "free_bytes": free_bytes,
                    "required_bytes": expected_sz,
                    "message": f"Espaço em disco insuficiente: {format_size(free_bytes)} livres, necessário {format_size(expected_sz)}"
                }
        except Exception:
            pass

        # 1. Caso seja arquivo de pasta local
        if file_info.get("is_local") or file_info.get("local_path"):
            src_file = Path(file_info["local_path"])
            if not src_file.exists():
                return {"status": "error", "file": filename, "message": "Arquivo local de origem não encontrado"}

            needs_gps_check = use_gps and (date_ymd not in self._date_location_cache)
            if needs_gps_check and (ext in PHOTO_EXTENSIONS or ext in VIDEO_EXTENSIONS):
                gps = extract_gps(str(src_file))
                if gps:
                    city = reverse_geocode(gps[0], gps[1])
                    if city:
                        self._date_location_cache[date_ymd] = city

            final_folder_name = self._resolve_folder_name(date_ymd, custom_local)
            final_folder_dir = Path(target_base_dir) / final_folder_name
            final_folder_dir.mkdir(parents=True, exist_ok=True)
            final_dest_file = final_folder_dir / filename

            # Evita sobrescrever se origem e destino forem idênticos
            try:
                if src_file.resolve() == final_dest_file.resolve():
                    return {"status": "skipped", "file": filename, "folder": final_folder_name, "path": str(final_dest_file)}
            except Exception:
                pass

            if final_dest_file.exists() and final_dest_file.stat().st_size > 0:
                if skip_existing:
                    action = "skip"
                elif conflict_resolver:
                    action = conflict_resolver(file_info, final_dest_file)
                else:
                    action = "overwrite"

                if action == "skip":
                    return {"status": "skipped", "file": filename, "folder": final_folder_name, "path": str(final_dest_file)}
                elif action == "cancel":
                    return {"status": "cancelled", "file": filename, "folder": final_folder_name}
                elif action == "overwrite":
                    try:
                        final_dest_file.unlink(missing_ok=True)
                    except Exception:
                        pass

            total_sz = src_file.stat().st_size
            copied = 0
            chunk_size = 512 * 1024
            if file_progress_callback:
                file_progress_callback(filename, 0, total_sz)

            try:
                with open(src_file, "rb") as fsrc, open(final_dest_file, "wb") as fdst:
                    while True:
                        while pause_event and pause_event.is_set():
                            if cancel_event and cancel_event.is_set():
                                break
                            time.sleep(0.1)
                        if cancel_event and cancel_event.is_set():
                            final_dest_file.unlink(missing_ok=True)
                            return {"status": "cancelled", "file": filename, "folder": final_folder_name}
                        buf = fsrc.read(chunk_size)
                        if not buf:
                            break
                        fdst.write(buf)
                        copied += len(buf)
                        if file_progress_callback and total_sz > 0:
                            file_progress_callback(filename, copied, total_sz)
            except OSError as ex:
                final_dest_file.unlink(missing_ok=True)
                cur_free = 0
                try:
                    cur_free = shutil.disk_usage(target_base_dir).free
                except Exception:
                    pass
                if cur_free < total_sz or getattr(ex, "errno", None) in (28,):
                    return {
                        "status": "disk_full",
                        "file": filename,
                        "free_bytes": cur_free,
                        "required_bytes": total_sz,
                        "message": f"Espaço em disco esgotado ({format_size(cur_free)} livres, necessário {format_size(total_sz)})"
                    }
                return {"status": "error", "file": filename, "message": f"Erro de I/O na gravação: {ex}"}

            try:
                shutil.copystat(str(src_file), str(final_dest_file))
            except Exception:
                pass
            if file_progress_callback and total_sz > 0:
                file_progress_callback(filename, total_sz, total_sz)

            return {"status": "success", "file": filename, "folder": final_folder_name, "path": str(final_dest_file), "size": final_dest_file.stat().st_size}

        # 2. Caso seja arquivo remoto no iPhone (WPD/MTP via Shell COM)
        pythoncom.CoInitialize()
        if not shell_instance:
            shell_instance = win32com.client.Dispatch("Shell.Application")

        item_obj = file_info["item_obj"]

        final_folder_name = self._resolve_folder_name(date_ymd, custom_local)
        final_folder_dir = Path(target_base_dir) / final_folder_name
        final_folder_dir.mkdir(parents=True, exist_ok=True)
        final_dest_file = final_folder_dir / filename

        # Tratamento de conflito prévio: elimina o arquivo de destino antes de CopyHere
        # garantindo que o Windows Shell nunca abra janelas repetitivas de diálogo.
        if final_dest_file.exists() and final_dest_file.stat().st_size > 0:
            if skip_existing:
                action = "skip"
            elif conflict_resolver:
                action = conflict_resolver(file_info, final_dest_file)
            else:
                action = "overwrite"

            if action == "skip":
                return {"status": "skipped", "file": filename, "folder": final_folder_name, "path": str(final_dest_file)}
            elif action == "cancel":
                return {"status": "cancelled", "file": filename, "folder": final_folder_name}
            elif action == "overwrite":
                try:
                    final_dest_file.unlink(missing_ok=True)
                except Exception:
                    pass

        # Dispara cópia nativa assíncrona do Windows Shell
        dest_ns = shell_instance.NameSpace(str(final_folder_dir))
        dest_ns.CopyHere(item_obj, 4 | 16 | 512 | 1024)

        if file_progress_callback:
            file_progress_callback(filename, 0, expected_sz)

        # Monitoramento contínuo inteligente sem limite rígido de tempo (suporta arquivos grandes de 7GB+)
        last_sz = -1
        last_growth_time = time.time()
        max_stall_time = 45.0  # Permite até 45s de buffer do Windows/MTP sem travar

        while True:
            if cancel_event and cancel_event.is_set():
                break
            while pause_event and pause_event.is_set():
                if cancel_event and cancel_event.is_set():
                    break
                time.sleep(0.1)
                last_growth_time = time.time()

            if cancel_event and cancel_event.is_set():
                break

            cur_sz = final_dest_file.stat().st_size if final_dest_file.exists() else 0
            if file_progress_callback and expected_sz > 0:
                file_progress_callback(filename, min(cur_sz, expected_sz), expected_sz)

            # 1. Conclusão da cópia
            if expected_sz > 0 and cur_sz >= expected_sz:
                break

            # 2. Verifica se o arquivo cresceu
            if cur_sz > last_sz:
                last_sz = cur_sz
                last_growth_time = time.time()
            else:
                # Checa continuamente se o espaço em disco esgotou durante a gravação
                try:
                    cur_free = shutil.disk_usage(target_base_dir).free
                    if cur_free < 20 * 1024 * 1024 and (expected_sz <= 0 or cur_sz < expected_sz):
                        final_dest_file.unlink(missing_ok=True)
                        return {
                            "status": "disk_full",
                            "file": filename,
                            "free_bytes": cur_free,
                            "required_bytes": expected_sz,
                            "message": f"Espaço em disco esgotado durante a cópia ({format_size(cur_free)} livres)"
                        }
                except Exception:
                    pass

                now = time.time()
                # Se já gravou dados e parou de crescer por mais de 45s
                if cur_sz > 0 and (now - last_growth_time) >= max_stall_time:
                    # Se atingiu 98% ou mais do tamanho esperado, tolerância aceita
                    if expected_sz > 0 and cur_sz >= (expected_sz * 0.98):
                        break
                    else:
                        break
                elif cur_sz == 0 and (now - last_growth_time) >= 60.0:
                    break

            time.sleep(0.1)

        if cancel_event and cancel_event.is_set():
            final_dest_file.unlink(missing_ok=True)
            return {"status": "cancelled", "file": filename, "folder": final_folder_name}

        cur_sz = final_dest_file.stat().st_size if final_dest_file.exists() else 0

        # Validação estrita de integridade para arquivos grandes
        if expected_sz > 0 and cur_sz < (expected_sz * 0.95):
            try:
                cur_free = shutil.disk_usage(target_base_dir).free
                if cur_free < 50 * 1024 * 1024:
                    final_dest_file.unlink(missing_ok=True)
                    return {
                        "status": "disk_full",
                        "file": filename,
                        "free_bytes": cur_free,
                        "required_bytes": expected_sz,
                        "message": f"Espaço em disco insuficiente: cópia parou em {format_size(cur_sz)} de {format_size(expected_sz)}"
                    }
            except Exception:
                pass

            final_dest_file.unlink(missing_ok=True)
            return {
                "status": "error",
                "file": filename,
                "message": f"Cópia interrompida prematuramente ({format_size(cur_sz)} de {format_size(expected_sz)})"
            }

        if final_dest_file.exists() and cur_sz > 0:
            if file_progress_callback and expected_sz > 0:
                file_progress_callback(filename, cur_sz, expected_sz)

            # Extração de GPS pós-cópia se aplicável
            needs_gps_check = use_gps and (date_ymd not in self._date_location_cache)
            if needs_gps_check and (ext in PHOTO_EXTENSIONS or ext in VIDEO_EXTENSIONS):
                try:
                    gps = extract_gps(str(final_dest_file))
                    if gps:
                        city = reverse_geocode(gps[0], gps[1])
                        if city:
                            self._date_location_cache[date_ymd] = city
                except Exception:
                    pass

            return {"status": "success", "file": filename, "folder": final_folder_name, "path": str(final_dest_file), "size": cur_sz}
        else:
            return {"status": "error", "file": filename, "message": "Falha na cópia do arquivo via Windows Shell"}

    def download_batch(
        self,
        files_to_download: List[Dict],
        target_base_dir: str,
        custom_local: str = "",
        use_gps: bool = True,
        skip_existing: bool = True,
        conflict_resolver: Optional[Callable[[Dict, Path], str]] = None,
        progress_callback: Optional[Callable[[Dict, int, int], None]] = None,
        cancel_event = None,
        pause_event = None,
        file_progress_callback: Optional[Callable[[str, int, int], None]] = None,
        disk_full_resolver: Optional[Callable[[Dict, int, int], str]] = None
    ) -> Dict:
        """
        Executa o download de mídias em lote, ordenando fotos antes de vídeos por data
        para máxima eficiência de compartilhamento de geolocalização.
        """
        pythoncom.CoInitialize()
        shell_instance = win32com.client.Dispatch("Shell.Application")
        total = len(files_to_download)
        stats = {
            "total": total,
            "success": 0,
            "skipped": 0,
            "errors": 0,
            "cancelled": False,
            "total_bytes": 0
        }

        staging_dir = Path(target_base_dir) / "_staging_temp"

        def sort_key(f):
            is_photo = 0 if f["ext"] in PHOTO_EXTENSIONS else 1
            return (f["date"], is_photo, f["name"])

        sorted_files = sorted(files_to_download, key=sort_key)

        try:
            for idx, file_info in enumerate(sorted_files):
                while pause_event and pause_event.is_set():
                    if cancel_event and cancel_event.is_set():
                        stats["cancelled"] = True
                        break
                    time.sleep(0.1)

                if cancel_event and cancel_event.is_set():
                    stats["cancelled"] = True
                    break

                res = self.download_file(
                    file_info,
                    target_base_dir,
                    custom_local=custom_local,
                    use_gps=use_gps,
                    skip_existing=skip_existing,
                    conflict_resolver=conflict_resolver,
                    shell_instance=shell_instance,
                    file_progress_callback=file_progress_callback,
                    cancel_event=cancel_event,
                    pause_event=pause_event
                )

                # Tratamento interativo de disco cheio com suporte a Pausar ou Cancelar
                while res.get("status") == "disk_full":
                    action = "cancel"
                    if disk_full_resolver:
                        action = disk_full_resolver(file_info, res.get("free_bytes", 0), res.get("required_bytes", 0))

                    if action == "pause":
                        if pause_event:
                            pause_event.set()
                        while pause_event and pause_event.is_set():
                            if cancel_event and cancel_event.is_set():
                                break
                            time.sleep(0.2)

                        if cancel_event and cancel_event.is_set():
                            res = {"status": "cancelled", "file": file_info["name"]}
                            break

                        # Usuário liberou espaço e despausou: tenta novamente o mesmo arquivo!
                        res = self.download_file(
                            file_info,
                            target_base_dir,
                            custom_local=custom_local,
                            use_gps=use_gps,
                            skip_existing=skip_existing,
                            conflict_resolver=conflict_resolver,
                            shell_instance=shell_instance,
                            file_progress_callback=file_progress_callback,
                            cancel_event=cancel_event,
                            pause_event=pause_event
                        )
                    elif action == "cancel":
                        res = {"status": "cancelled", "file": file_info["name"]}
                        break
                    else:  # skip
                        res = {"status": "skipped", "file": file_info["name"], "message": "Pulado por falta de espaço em disco"}
                        break

                if res.get("status") == "cancelled":
                    stats["cancelled"] = True
                    if cancel_event:
                        cancel_event.set()
                    break
                elif res["status"] == "success":
                    stats["success"] += 1
                    stats["total_bytes"] += res.get("size", 0)
                elif res["status"] == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["errors"] += 1

                if progress_callback:
                    progress_callback(res, idx + 1, total)

        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

        return stats

    @staticmethod
    def _run_dialog_watcher(stop_event: threading.Event):
        """
        Monitora em segundo plano e confirma automaticamente caixas de diálogo nativas
        do Windows Shell ('Excluir Arquivo' / 'Confirm File Delete'), permitindo exclusão
        rápida e contínua sem exigir confirmação manual para cada foto ou vídeo.
        """
        keywords = ["excluir", "delete", "apagar", "remover", "confirm"]

        while not stop_event.is_set():
            def enum_cb(hwnd, _):
                try:
                    if not win32gui.IsWindowVisible(hwnd):
                        return
                    cls_name = win32gui.GetClassName(hwnd)
                    if cls_name != "#32770":
                        return
                    title = win32gui.GetWindowText(hwnd).strip()
                    # Não interfere em diálogos próprios do aplicativo
                    if "⚠️" in title or "cmaker" in title.lower():
                        return

                    lower_title = title.lower()
                    if not any(k in lower_title for k in keywords):
                        return

                    # Procura o botão IDYES (6) ou com texto 'Sim' / 'Yes'
                    yes_btn = None
                    try:
                        yes_btn = win32gui.GetDlgItem(hwnd, win32con.IDYES)
                    except Exception:
                        pass

                    if not yes_btn:
                        def child_cb(chwnd, _):
                            nonlocal yes_btn
                            txt = win32gui.GetWindowText(chwnd).strip().lower()
                            if txt in ["sim", "&sim", "yes", "&yes", "ok", "&ok"]:
                                yes_btn = chwnd
                        try:
                            win32gui.EnumChildWindows(hwnd, child_cb, None)
                        except Exception:
                            pass

                    if yes_btn:
                        win32gui.PostMessage(yes_btn, win32con.BM_CLICK, 0, 0)
                        win32gui.PostMessage(hwnd, win32con.WM_COMMAND, win32con.IDYES, yes_btn)
                except Exception:
                    pass

            try:
                win32gui.EnumWindows(enum_cb, None)
            except Exception:
                pass
            time.sleep(0.02)

    def delete_file(self, file_info: Dict, auto_confirm: bool = True) -> bool:
        """
        Exclui permanentemente um arquivo (foto ou vídeo) do iPhone ou da pasta local de origem.
        """
        # Caso seja arquivo de pasta local
        if file_info.get("is_local") or file_info.get("local_path"):
            try:
                p = Path(file_info["local_path"])
                if p.exists():
                    p.unlink()
                return True
            except Exception as e:
                print(f"Erro ao excluir arquivo local {file_info.get('name')}: {e}")
                return False

        pythoncom.CoInitialize()
        item_obj = file_info.get("item_obj")
        if not item_obj:
            return False

        stop_watcher = None
        if auto_confirm:
            stop_watcher = threading.Event()
            threading.Thread(target=self._run_dialog_watcher, args=(stop_watcher,), daemon=True).start()

        try:
            for verb in item_obj.Verbs():
                v_name = verb.Name.lower().replace("&", "")
                if "excluir" in v_name or "delete" in v_name:
                    verb.DoIt()
                    return True
            item_obj.InvokeVerb("delete")
            return True
        except Exception as e:
            print(f"Erro ao excluir {file_info.get('name')}: {e}")
            return False
        finally:
            if stop_watcher:
                time.sleep(0.05)
                stop_watcher.set()

    def delete_batch(
        self,
        files_to_delete: List[Dict],
        progress_callback: Optional[Callable[[str, int, int, bool], None]] = None,
        cancel_event = None,
        pause_event = None
    ) -> Dict:
        """
        Exclui uma lista de arquivos do iPhone com acompanhamento de progresso,
        suprimindo caixas de diálogo repetitivas do Windows Shell para cada arquivo individual.
        """
        pythoncom.CoInitialize()
        total = len(files_to_delete)
        stats = {
            "total": total,
            "deleted": 0,
            "failed": 0,
            "cancelled": False
        }

        # Inicia watcher de confirmação automática contínua para todo o lote
        stop_watcher = threading.Event()
        watcher = threading.Thread(target=self._run_dialog_watcher, args=(stop_watcher,), daemon=True)
        watcher.start()

        try:
            for idx, file_info in enumerate(files_to_delete):
                while pause_event and pause_event.is_set():
                    if cancel_event and cancel_event.is_set():
                        stats["cancelled"] = True
                        break
                    time.sleep(0.1)

                if cancel_event and cancel_event.is_set():
                    stats["cancelled"] = True
                    break

                fname = file_info.get("name", "")
                # auto_confirm=False pois o lote já possui seu watcher ativo
                success = self.delete_file(file_info, auto_confirm=False)

                if success:
                    stats["deleted"] += 1
                else:
                    stats["failed"] += 1

                if progress_callback:
                    progress_callback(fname, idx + 1, total, success)
        finally:
            time.sleep(0.05)
            stop_watcher.set()

        return stats
