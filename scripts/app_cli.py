"""
Interface de Linha de Comando (CLI) para Baixar Fotos do iPhone via USB.
Permite executar a busca e o download em lote diretamente pelo terminal.
"""

import sys
from pathlib import Path

# Garante saída compatível com UTF-8 no Windows Console (evita erro cp1252 com emojis)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.iphone_manager import IPhoneManager
from scripts.app_gui import format_size

def parse_args():
    parser = argparse.ArgumentParser(
        description="Baixa fotos do iPhone conectado via USB ou de um diretório local organizando em pastas AAAA-MM-DD-Local."
    )
    parser.add_argument("--source", "-s", type=str, default="iphone", help="Origem das midias: 'iphone' (padrao) ou caminho de um diretorio local/cartao SD.")
    parser.add_argument("--dest", "-d", type=str, help="Diretorio de destino onde as fotos serao salvas.")
    parser.add_argument("--year", "-y", type=str, help="Filtrar por ano (ex: 2026).")
    parser.add_argument("--month", "-m", type=str, help="Filtrar por mes (ex: 2026-05 ou 05).")
    parser.add_argument("--from-date", type=str, help="Data inicial no formato AAAA-MM-DD.")
    parser.add_argument("--to-date", type=str, help="Data final no formato AAAA-MM-DD.")
    parser.add_argument("--local", "-l", type=str, default="", help="Sufixo ou nome do Local (opcional, vazio para usar apenas data ou cidade GPS).")
    parser.add_argument("--no-gps", action="store_true", help="Desativa deteccao automatica de cidade por GPS EXIF.")
    parser.add_argument("--no-videos", action="store_true", help="Exclui videos (.MOV, .MP4), baixando apenas fotos.")
    parser.add_argument("--overwrite", action="store_true", help="Sobrescreve arquivos ja existentes no destino.")
    parser.add_argument("--delete", action="store_true", help="Exclui os arquivos da origem apos serem baixados com sucesso.")
    parser.add_argument("--list-years", action="store_true", help="Lista os anos disponiveis no iPhone e sai.")
    parser.add_argument("--list-months", action="store_true", help="Lista os meses disponiveis no iPhone e sai.")

    return parser.parse_args()

def main():
    args = parse_args()

    print("\n" + "=" * 60)
    print(" [i] Photo Commander CLI (iPhone USB / Diretorio Local)")
    print("=" * 60)

    manager = IPhoneManager()
    is_local_source = args.source.lower() != "iphone"

    if is_local_source:
        src_path = Path(args.source)
        if not src_path.exists() or not src_path.is_dir():
            print(f"[ERRO] Diretorio de origem nao encontrado: {args.source}")
            sys.exit(1)
        print(f"[OK] Origem local selecionada: {src_path.resolve()}\n")
    else:
        print("Conectando ao iPhone via Windows Shell...")
        if not manager.connect():
            print("[ERRO] iPhone nao encontrado ou bloqueado.")
            print("Verifique se o cabo USB esta conectado, desbloqueie o iPhone")
            print("e toque em 'Confiar neste computador'.")
            sys.exit(1)
        print(f"[OK] Conectado: {manager.device_name}\n")

    # Listagem de anos
    if args.list_years:
        years = manager.get_available_years()
        print(f"Anos disponiveis no iPhone ({len(years)}):")
        for y in years:
            print(f"  * {y}")
        sys.exit(0)

    # Listagem de meses
    if args.list_months:
        months = manager.get_available_months(year=args.year)
        print(f"Meses disponiveis ({len(months)}):")
        for m in months:
            print(f"  * {m}")
        sys.exit(0)

    # Validacao do diretorio de destino
    if not args.dest:
        print("[ERRO] O parametro --dest e obrigatorio para baixar fotos.")
        print("Exemplo: python scripts/app_cli.py --dest 'D:\\FotosBackup' --year 2026 --month 05")
        sys.exit(1)

    # Preparacao de filtros
    filter_years = [args.year] if args.year else None
    filter_months = None

    if args.month:
        if len(args.month) <= 2:
            y = args.year or manager.get_available_years()[0]
            filter_months = [f"{y}-{int(args.month):02d}"]
        else:
            filter_months = [args.month]

    print("[*] Varrendo fotos correspondentes aos filtros...")
    if filter_years:
        print(f"  * Ano: {filter_years}")
    if filter_months:
        print(f"  * Mes: {filter_months}")
    if args.from_date and args.to_date:
        print(f"  * Intervalo: {args.from_date} ate {args.to_date}")
    include_videos = not args.no_videos
    local_str = args.local if args.local else "(vazio: apenas data ou GPS)"
    print(f"  * Destino: {args.dest}")
    print(f"  * Local customizado: {local_str}")
    print(f"  * GPS ativo: {not args.no_gps}")
    print(f"  * Incluir videos: {include_videos}\n")

    if is_local_source:
        items = manager.scan_local_folder(
            folder_path=str(Path(args.source).resolve()),
            recursive=True,
            filter_months=filter_months,
            date_from=args.from_date,
            date_to=args.to_date,
            include_photos=True,
            include_videos=include_videos,
            progress_callback=lambda msg, c, t: print(f"  [{c}/{t}] {msg}", end="\r")
        )
    else:
        items = manager.scan_photos(
            filter_years=filter_years,
            filter_months=filter_months,
            date_from=args.from_date,
            date_to=args.to_date,
            include_photos=True,
            include_videos=include_videos,
            progress_callback=lambda msg, c, t: print(f"  [{c}/{t}] {msg}", end="\r")
        )

    total = len(items)
    print(f"\n[OK] Busca finalizada: {total} arquivo(s) encontrado(s).\n")

    if total == 0:
        print("Nenhum arquivo encontrado para os filtros informados.")
        sys.exit(0)

    total_bytes = sum(it.get("size", 0) for it in items)
    print(f"Tamanho total estimado: {format_size(total_bytes)}")
    confirm = input(f"Deseja iniciar o download de {total} arquivo(s)? (S/N): ").strip().upper()
    if confirm not in ("S", "SIM", "Y", "YES"):
        print("Operacao cancelada pelo usuario.")
        sys.exit(0)

    print("\n[*] Iniciando download...")

    def on_prog(res, cur, tot):
        fname = res.get("file", "")
        folder = res.get("folder", "")
        status = res.get("status", "")
        if status == "success":
            print(f"[{cur}/{tot}] [OK] Baixado: {fname} -> {folder}")
        elif status == "skipped":
            print(f"[{cur}/{tot}] [SKIP] Pulado: {fname} (ja existe)")
        else:
            print(f"[{cur}/{tot}] [ERRO] Falha: {fname} ({res.get('message', '')})")

    stats = manager.download_batch(
        files_to_download=items,
        target_base_dir=args.dest,
        custom_local=args.local,
        use_gps=not args.no_gps,
        skip_existing=not args.overwrite,
        progress_callback=on_prog
    )

    if args.delete and stats["success"] > 0:
        print("\n" + "=" * 60)
        print(" [!] EXCLUSAO SOLICITADA (--delete)")
        print("=" * 60)
        target_del_name = "da pasta de origem" if is_local_source else "do iPhone"
        confirm_del = input(f"Confirma a exclusao dos {stats['success']} arquivo(s) {target_del_name}? (S/N): ").strip().upper()
        if confirm_del in ("S", "SIM", "Y", "YES"):
            print(f"[*] Excluindo {target_del_name}...")
            del_stats = manager.delete_batch(
                items,
                progress_callback=lambda f, c, t, ok: print(f"  [{c}/{t}] {'[OK]' if ok else '[ERRO]'} {f}")
            )
            print(f"[OK] {del_stats['deleted']} arquivo(s) apagado(s) {target_del_name}. Falhas: {del_stats['failed']}\n")
        else:
            print("[*] Exclusao cancelada pelo usuario.\n")

    print("\n" + "=" * 60)
    print(" RELATORIO FINAL DE DOWNLOAD")
    print("=" * 60)
    print(f"Total processados: {stats['total']}")
    print(f"[OK] Baixados com sucesso: {stats['success']} ({format_size(stats['total_bytes'])})")
    print(f"[SKIP] Pulados (ja existentes): {stats['skipped']}")
    print(f"[ERRO] Falhas: {stats['errors']}")
    print(f"Arquivos salvos no padrao AAAA-MM-DD-Local em:\n{args.dest}\n")

if __name__ == "__main__":
    main()
