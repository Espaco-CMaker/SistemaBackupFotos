"""
Módulo de utilitários de geolocalização e manipulação de metadados EXIF/QuickTime.
Permite extrair coordenadas GPS de fotos (JPEG, HEIC, PNG) e vídeos (MOV, MP4)
e resolver o nome da cidade/local via OpenStreetMap Nominatim com cache local persistente.
"""

import os
import sys
import re
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ExifTags

if getattr(sys, "frozen", False):
    CACHE_FILE = Path(sys.executable).resolve().parent / "geo_cache.json"
else:
    CACHE_FILE = Path(__file__).resolve().parent / "geo_cache.json"

def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def sanitize_name(name: str) -> str:
    """Remove caracteres inválidos para nomes de pastas e arquivos no Windows."""
    if not name:
        return ""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

def _convert_to_degrees(value) -> float:
    """Converte tupla (graus, minutos, segundos) EXIF para float decimal."""
    try:
        d = float(value[0])
        m = float(value[1])
        s = float(value[2])
        return d + (m / 60.0) + (s / 3600.0)
    except Exception:
        return 0.0

def extract_image_gps(image_path: str) -> Optional[Tuple[float, float]]:
    """Extrai latitude e longitude decimal a partir do EXIF da imagem."""
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if not exif:
                return None
            
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if not gps_ifd:
                return None

            gps_tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
            
            lat_raw = gps_tags.get("GPSLatitude")
            lat_ref = gps_tags.get("GPSLatitudeRef")
            lon_raw = gps_tags.get("GPSLongitude")
            lon_ref = gps_tags.get("GPSLongitudeRef")

            if not lat_raw or not lon_raw:
                return None

            lat = _convert_to_degrees(lat_raw)
            if lat_ref and lat_ref.upper() == "S":
                lat = -lat

            lon = _convert_to_degrees(lon_raw)
            if lon_ref and lon_ref.upper() == "W":
                lon = -lon

            return (lat, lon)
    except Exception:
        return None

def extract_video_gps(video_path: str) -> Optional[Tuple[float, float]]:
    """
    Extrai coordenadas GPS ISO 6709 de vídeos QuickTime MOV ou MP4 gravados pelo iPhone.
    Verifica o átomo moov/udta nos primeiros e últimos 4 MB do arquivo.
    """
    try:
        size = os.path.getsize(video_path)
        read_size = min(size, 4 * 1024 * 1024)
        
        chunks = []
        with open(video_path, "rb") as f:
            chunks.append(f.read(read_size))
            if size > read_size * 2:
                f.seek(-read_size, os.SEEK_END)
                chunks.append(f.read(read_size))
        
        # Padrão ISO 6709: +XX.XXXX-YYY.YYYY (latitude com 2 dígitos, longitude com 3 dígitos)
        pattern = re.compile(rb"([+-]\d{2}(?:\.\d{2,8})?)([+-]\d{3}(?:\.\d{2,8})?)")
        for chunk in chunks:
            match = pattern.search(chunk)
            if match:
                lat = float(match.group(1).decode("ascii", errors="ignore"))
                lon = float(match.group(2).decode("ascii", errors="ignore"))
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return (lat, lon)
    except Exception:
        pass
    return None

def extract_gps(media_path: str) -> Optional[Tuple[float, float]]:
    """Extrai coordenadas GPS de fotos (JPEG, HEIC, PNG) ou vídeos (MOV, MP4)."""
    ext = os.path.splitext(media_path)[1].lower()
    if ext in {".mov", ".mp4", ".m4v"}:
        return extract_video_gps(media_path)
    return extract_image_gps(media_path)

def reverse_geocode(lat: float, lon: float, timeout: float = 3.0) -> Optional[str]:
    """Converte latitude e longitude em nome de cidade/município usando cache e Nominatim."""
    cache_key = f"{round(lat, 3):.3f},{round(lon, 3):.3f}"
    cache = _load_cache()
    if cache_key in cache:
        return cache[cache_key]

    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=12"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CMaker-IPhoneMediaDownloader/1.1 (edu@cmaker.org)"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            addr = data.get("address", {})
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("municipality")
                or addr.get("village")
                or addr.get("suburb")
                or addr.get("county")
                or addr.get("state")
            )
            if city:
                clean_city = sanitize_name(city)
                cache[cache_key] = clean_city
                _save_cache(cache)
                return clean_city
    except Exception:
        pass

    return None

def get_folder_name(date_ymd: str, custom_local: str = "", media_path: Optional[str] = None, use_gps: bool = True) -> str:
    """
    Gera o nome da pasta no padrão AAAA-MM-DD[-Local].
    1. Se use_gps=True e a mídia possuir coordenadas GPS válidas, o Local será o nome da Cidade.
    2. Caso contrário, se custom_local for fornecido, utiliza o custom_local sanitizado.
    3. Se não houver GPS nem custom_local, retorna apenas AAAA-MM-DD (sem forçar 'Fotos' nem 'Vídeos').
    """
    local = ""
    if use_gps and media_path and os.path.exists(media_path):
        gps = extract_gps(media_path)
        if gps:
            city = reverse_geocode(gps[0], gps[1])
            if city:
                local = city

    if not local and custom_local:
        local = sanitize_name(custom_local)

    if local:
        return f"{date_ymd}-{sanitize_name(local)}"
    return date_ymd
