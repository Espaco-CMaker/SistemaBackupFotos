"""
Script de automação para publicação de Releases e upload de binários executáveis
no GitHub para o repositório Espaco-CMaker/SistemaBackupFotos.
Utiliza a autenticação ativa do Git Credential Manager sem salvar tokens em disco.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_OWNER = "Espaco-CMaker"
REPO_NAME = "SistemaBackupFotos"
TAG_NAME = "v2.8.0"
RELEASE_TITLE = "CMaker Photo Commander v2.8.0"

RELEASE_BODY = """## 📱📁 CMaker Photo Commander v2.8.0

Aplicação desktop completa para download, organização automática por data/GPS e exclusão segura de fotos e vídeos diretamente de um iPhone conectado via USB ou de qualquer diretório local.

### 📦 Arquivos para Download (Escolha uma opção):

1. **Instalador Oficial Windows (Recomendado para Clientes):**
   - ⬇️ **`Instalador_CMakerPhotoCommander_v2.8.0.exe`**
   - Assistente passo a passo em português, cria atalhos na Área de Trabalho e Menu Iniciar, com desinstalador nativo do Windows. Não requer privilégios de Administrador.

2. **Versão Standalone Portátil (Executável Único):**
   - ⬇️ **`CMakerPhotoCommander.exe`**
   - Executável 100% autônomo, pronto para rodar direto de um pen drive ou pasta, sem nenhuma instalação prévia.

---

### 🌟 Destaques da Versão v2.8.0:
- **Origem Dupla de Mídias:** Suporte nativo a iPhone (USB WPD/MTP com diagnóstico WMI) e Pastas Locais / Câmeras / Cartões SD.
- **4 Modos de Exibição:** Detalhes, Lista, Miniaturas e Miniaturas Gigantes em ambos os painéis (Origem e Destino).
- **Monitor de Espaço em Disco Livre:** Exibição do espaço restante em tempo real no destino, atualizado a cada cópia com alertas por cor.
- **Tamanho Total Selecionado:** Contador e somatório de bytes dos arquivos marcados na origem em tempo real.
- **Monitor de Vídeo Animado:** Alternância dinâmica entre múltiplos vídeos da pasta `anim/` durante as transferências.
- **Resolução Autônoma de Conflitos:** Checkbox "Fazer isso para todos os arquivos" para transferências em lote sem interrupções.
- **Controle Total:** Botões dedicados de Pausar, Continuar e Cancelar com limpeza imediata de arquivos parciais.
"""

def get_github_token() -> str:
    """Obtém o token de autenticação diretamente do Git Credential Manager."""
    gcm_path = "C:/Users/fgbet/MinGit/mingw64/bin/git-credential-manager.exe"
    if not os.path.exists(gcm_path):
        import shutil
        gcm_path = shutil.which("git-credential-manager") or "git-credential-manager"

    p = subprocess.Popen(
        [gcm_path, "get"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    out, _ = p.communicate("protocol=https\nhost=github.com\n")
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return None

def publish():
    project_root = Path(__file__).resolve().parent.parent
    dist_dir = project_root / "dist"
    installer_file = dist_dir / "Instalador_CMakerPhotoCommander_v2.8.0.exe"
    portable_file = project_root / "CMakerPhotoCommander.exe"

    print("=" * 65)
    print(" 🚀 Publicador de Release no GitHub - CMaker Photo Commander")
    print("=" * 65)

    token = get_github_token()
    if not token:
        print("[ERRO] Não foi possível obter o token de acesso do GitHub via Git Credential Manager.")
        sys.exit(1)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CMaker-Release-Publisher/1.0"
    }

    # 1. Verifica se a release já existe
    rel_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{TAG_NAME}"
    resp = requests.get(rel_url, headers=headers)

    if resp.status_code == 200:
        release_data = resp.json()
        print(f"[*] Release {TAG_NAME} já existe (ID: {release_data['id']}).")
    elif resp.status_code == 404:
        print(f"[*] Criando nova Release {TAG_NAME} no GitHub...")
        create_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases"
        payload = {
            "tag_name": TAG_NAME,
            "target_commitish": "main",
            "name": RELEASE_TITLE,
            "body": RELEASE_BODY,
            "draft": False,
            "prerelease": False
        }
        create_resp = requests.post(create_url, headers=headers, json=payload)
        if create_resp.status_code not in (200, 201):
            print(f"[ERRO] Falha ao criar release: {create_resp.status_code} - {create_resp.text}")
            sys.exit(1)
        release_data = create_resp.json()
        print(f"[OK] Release criada com sucesso! (ID: {release_data['id']})")
    else:
        print(f"[ERRO] Erro ao consultar release: {resp.status_code} - {resp.text}")
        sys.exit(1)

    upload_url_template = release_data.get("upload_url", "").split("{")[0]
    existing_assets = {a["name"]: a["id"] for a in release_data.get("assets", [])}

    # 2. Upload dos arquivos binários
    files_to_upload = []
    if installer_file.exists():
        files_to_upload.append(installer_file)
    else:
        print(f"[AVISO] Instalador não encontrado em: {installer_file}")

    if portable_file.exists():
        files_to_upload.append(portable_file)
    else:
        print(f"[AVISO] Executável portátil não encontrado em: {portable_file}")

    for file_path in files_to_upload:
        fname = file_path.name
        fsize_mb = file_path.stat().st_size / (1024 * 1024)

        if fname in existing_assets:
            print(f"\n[*] Arquivo '{fname}' já existe na release. Substituindo...")
            del_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/assets/{existing_assets[fname]}"
            del_resp = requests.delete(del_url, headers=headers)
            if del_resp.status_code in (200, 204):
                print(f"    ✔ Asset anterior removido.")

        print(f"\n[*] Enviando '{fname}' ({fsize_mb:.1f} MB) para o GitHub Releases...")
        upload_url = f"{upload_url_template}?name={fname}"
        upload_headers = headers.copy()
        upload_headers["Content-Type"] = "application/vnd.microsoft.portable-executable"

        with open(file_path, "rb") as f:
            up_resp = requests.post(upload_url, headers=upload_headers, data=f, timeout=600)

        if up_resp.status_code in (200, 201):
            print(f"    ✔ Upload concluído com sucesso!")
        else:
            print(f"    [ERRO] Falha no upload de '{fname}': {up_resp.status_code} - {up_resp.text}")

    print("\n" + "=" * 65)
    print(" 🎉 BINÁRIOS DISPONIBILIZADOS NO GITHUB RELEASES COM SUCESSO!")
    print(f" URL da Release: {release_data.get('html_url')}")
    print("=" * 65)

if __name__ == "__main__":
    publish()
