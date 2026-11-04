"""
Script de automação para compilação do executável standalone (Windows .exe)
do CMaker Photo Commander usando PyInstaller.
Gera um arquivo único .exe independente, sem necessidade de Python ou bibliotecas instaladas.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def create_app_icon(icon_path: Path):
    """Gera um ícone profissional (.ico) para a aplicação caso não exista."""
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    if icon_path.exists():
        return

    print("[*] Gerando icone oficial da aplicacao...")
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo moderno em gradiente escuro arredondado
    draw.rounded_rectangle([8, 8, 248, 248], radius=52, fill="#0f172a")

    # Contorno metálico suave
    draw.rounded_rectangle([12, 12, 244, 244], radius=48, outline="#38bdf8", width=4)

    # Corpo da câmera / dispositivo
    draw.rounded_rectangle([44, 76, 212, 196], radius=24, fill="#1e293b", outline="#0284c7", width=3)

    # Detalhe superior da câmera
    draw.rounded_rectangle([88, 52, 168, 80], radius=10, fill="#0284c7")

    # Lente circular central
    draw.ellipse([84, 96, 172, 184], fill="#0369a1", outline="#38bdf8", width=4)
    draw.ellipse([104, 116, 152, 164], fill="#0ea5e9")
    draw.ellipse([114, 126, 134, 146], fill="#ffffff")

    # LED flash
    draw.ellipse([176, 92, 196, 112], fill="#f59e0b")

    img.save(
        icon_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    )
    print(f"[OK] Icone gerado em: {icon_path}")

def build_executable():
    project_root = Path(__file__).resolve().parent.parent
    scripts_dir = project_root / "scripts"
    main_script = scripts_dir / "app_gui.py"
    assets_dir = project_root / "assets"
    icon_file = assets_dir / "app_icon.ico"
    anim_dir = project_root / "anim"

    print("=" * 65)
    print(" Compilador Standalone - CMaker Photo Commander")
    print("=" * 65)
    print(f"Diretorio raiz do projeto: {project_root}")
    print(f"Script principal:          {main_script}")

    # Garante ícone
    create_app_icon(icon_file)

    # Monta comando do PyInstaller
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "CMakerPhotoCommander",
        "--icon", str(icon_file),
        "--add-data", f"{anim_dir};anim",
        "--collect-all", "pillow_heif",
        "--collect-all", "cv2",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--distpath", str(project_root / "dist"),
        "--workpath", str(project_root / "build"),
        "--specpath", str(project_root / "build"),
        str(main_script)
    ]

    print("\nExecutando PyInstaller...")
    print("Comando:", " ".join(cmd))
    print("\nAguarde, a compilacao e empacotamento levam cerca de 1 a 2 minutos...")

    res = subprocess.run(cmd, cwd=str(project_root))
    if res.returncode != 0:
        print(f"\n[ERRO] Falha durante a compilacao do PyInstaller (codigo {res.returncode}).")
        sys.exit(res.returncode)

    dist_exe = project_root / "dist" / "CMakerPhotoCommander.exe"
    root_exe = project_root / "CMakerPhotoCommander.exe"

    if dist_exe.exists():
        size_mb = dist_exe.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Executavel compilado com sucesso em: {dist_exe} ({size_mb:.1f} MB)")
        try:
            shutil.copy2(dist_exe, root_exe)
            print(f"[OK] Copiado para a raiz do projeto: {root_exe}")
        except Exception as e:
            print(f"Aviso ao copiar para a raiz: {e}")

        print("\n" + "=" * 65)
        print(" EXECUTAVEL PRONTO PARA USO!")
        print(" O executavel e 100% autonomo (nao requer Python nem dependencias).")
        print(f" Arquivo gerado: {root_exe}")
        print("=" * 65)
    else:
        print("\n[ERRO] Executavel nao encontrado na pasta dist.")

if __name__ == "__main__":
    build_executable()
