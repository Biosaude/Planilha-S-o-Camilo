import argparse
from pathlib import Path

from src.models import QuoteError
from src.settings import database_path
from src.tuss_importer import FILENAMES, import_bases, list_versions, restore_version
from src.validators import MAX_UPLOAD


def main():
    parser = argparse.ArgumentParser(description='Gerência local do catálogo TUSS.')
    parser.add_argument('--diretorio', type=Path, default=Path('data'))
    parser.add_argument('--parte-1', type=Path)
    parser.add_argument('--parte-2', type=Path)
    parser.add_argument('--versao')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--listar', action='store_true')
    actions.add_argument('--restaurar', type=int)
    args = parser.parse_args()
    try:
        if args.listar:
            active, versions = list_versions(database_path())
            for version in versions:
                print('*' if active == version.id else ' ', version)
        elif args.restaurar:
            restore_version(database_path(), args.restaurar)
            print(f'Versão {args.restaurar} reativada.')
        else:
            if not args.versao:
                parser.error('Informe --versao para importar uma nova base.')
            paths = (args.parte_1 or args.diretorio / FILENAMES[0], args.parte_2 or args.diretorio / FILENAMES[1])
            payloads = []
            for path in paths:
                if path.stat().st_size > MAX_UPLOAD:
                    raise QuoteError('Cada base deve ter até 25 MB.')
                payloads.append((path.read_bytes(), path.name))
            report = import_bases(database_path(), *payloads, label=args.versao)
            print(report)
    except OSError:
        parser.exit(1, 'Não foi possível ler uma das duas planilhas no caminho informado.\n')
    except QuoteError as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
