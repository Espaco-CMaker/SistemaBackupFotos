"""
Script de automação para compilação do Instalador Windows oficial (.exe)
do CMaker Photo Commander usando Inno Setup (ISCC).
Gera um instalador com assistente gráfico, atalhos na Área de Trabalho e Menu Iniciar,
e desinstalador completo registrado no Windows.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def find_iscc() -> Path:
    """Localiza o compilador ISCC.exe do Inno Setup no sistema."""
    # 1. Verifica PATH
    path_iscc = shutil.which("iscc") or shutil.which("ISCC.exe")
    if path_iscc:
        return Path(path_iscc)

    # 2. Caminhos comuns conhecidos
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Antigravity IDE" / "resources" / "app" / "node_modules" / "innosetup" / "bin" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path("C:/InnoSetup/ISCC.exe"),
    ]

    for cand in candidates:
        if cand.exists():
            return cand

    return None

def build_installer():
    project_root = Path(__file__).resolve().parent.parent
    scripts_dir = project_root / "scripts"
    iss_file = scripts_dir / "installer.iss"
    exe_file = project_root / "CMakerPhotoCommander.exe"
    dist_dir = project_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(" 📦 Compilador de Instalador Windows - CMaker Photo Commander")
    print("=" * 65)

    # 1. Verifica se o executável standalone já foi compilado
    if not exe_file.exists():
        print("[!] Executavel standalone nao encontrado na raiz. Compilando primeiro...")
        build_exe_script = scripts_dir / "build_exe.py"
        res = subprocess.run([sys.executable, str(build_exe_script)], cwd=str(project_root))
        if res.returncode != 0:
            print("[ERRO] Falha ao compilar o executavel.")
            sys.exit(1)

    # 2. Localiza o Inno Setup
    iscc_bin = find_iscc()
    if not iscc_bin:
        print("[ERRO] Compilador Inno Setup (ISCC.exe) nao encontrado no sistema.")
        print("Instale o Inno Setup 6 gratuitamente em: https://jrsoftware.org/isdl.php")
        sys.exit(1)

    print(f"[*] Utilizando Inno Setup em: {iscc_bin}")
    print(f"[*] Script de definicao:       {iss_file}")
    print("\nIniciando compilacao do instalador com compressao maxima LZMA2...")

    cmd = [str(iscc_bin), str(iss_file)]
    res = subprocess.run(cmd, cwd=str(scripts_dir))
    if res.returncode != 0:
        print(f"\n[ERRO] Falha ao compilar o instalador (codigo {res.returncode}).")
        sys.exit(res.returncode)

    installer_output = dist_dir / "Instalador_CMakerPhotoCommander_v2.8.0.exe"
    if installer_output.exists():
        size_mb = installer_output.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Instalador compilado com sucesso!")
        print(f"     Arquivo: {installer_output} ({size_mb:.1f} MB)")
        print("\n" + "=" * 65)
        print(" 🎉 INSTALADOR CLIENTE PRONTO PARA DISTRIBUIÇÃO!")
        print(" O cliente pode simplesmente baixar e executar o arquivo de instalacao.")
        print("=" * 65)
    else:
        print("\n[ERRO] Arquivo de instalador nao encontrado em dist/")

if __name__ == "__main__":
    build_installer()

