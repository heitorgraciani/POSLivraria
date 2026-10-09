import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def conectar() -> psycopg.Connection:
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL não definida no .env")
    return psycopg.connect(url)


def aplicar_arquivo(caminho: str) -> None:
    sql = Path(caminho).read_text(encoding="utf-8")
    with conectar() as conn:
        conn.execute(sql)
    print(f"OK: {caminho} aplicado")


def imprimir_consulta(sql: str) -> None:
    with conectar() as conn:
        cur = conn.execute(sql)
        if cur.description is None:
            print(f"OK: {cur.rowcount} linha(s) afetada(s)")
            return
        colunas = [c.name for c in cur.description]
        print(" | ".join(colunas))
        for linha in cur.fetchall():
            print(" | ".join("" if v is None else str(v) for v in linha))


def main() -> None:
    parser = argparse.ArgumentParser(description="Aplica um arquivo SQL ou executa uma consulta.")
    parser.add_argument("arquivo", nargs="?", help="arquivo .sql a executar")
    parser.add_argument("--query", help="consulta SQL cujo resultado será impresso")
    args = parser.parse_args()

    if args.query:
        imprimir_consulta(args.query)
    elif args.arquivo:
        aplicar_arquivo(args.arquivo)
    else:
        parser.error("informe um arquivo .sql ou --query")


if __name__ == "__main__":
    main()
