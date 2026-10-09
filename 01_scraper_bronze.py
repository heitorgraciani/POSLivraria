import argparse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from psycopg.types.json import Jsonb

from aplicar_sql import conectar

URL_LISTAGEM = "https://books.toscrape.com/catalogue/page-{n}.html"
MAX_PARALELO = 8
SQL_BRONZE = Path(__file__).parent / "sql" / "00_bronze.sql"

sessao = requests.Session()
sessao.headers["User-Agent"] = "LivrariaInteligente-Scraper/1.0 (estudo)"


def baixar_html(url: str) -> BeautifulSoup:
    resposta = sessao.get(url, timeout=30)
    resposta.raise_for_status()
    return BeautifulSoup(resposta.text, "html.parser")


def links_da_pagina(n: int) -> list[str]:
    url = URL_LISTAGEM.format(n=n)
    pagina = baixar_html(url)
    return [urljoin(url, a["href"]) for a in pagina.select("article.product_pod h3 a")]


def texto_ou_none(elemento) -> str | None:
    return elemento.get_text() if elemento else None


def ler_tabela(pagina: BeautifulSoup) -> dict[str, str]:
    return {
        linha.th.get_text(): linha.td.get_text()
        for linha in pagina.select("table.table tr")
        if linha.th and linha.td
    }


def extrair_livro(url: str) -> dict:
    pagina = baixar_html(url)
    tabela = ler_tabela(pagina)
    estrelas = pagina.select_one("div.product_main p.star-rating")
    links_breadcrumb = pagina.select("ul.breadcrumb a")
    return {
        "url": url,
        "titulo": texto_ou_none(pagina.select_one("div.product_main h1")),
        "preco_raw": texto_ou_none(pagina.select_one("div.product_main p.price_color")),
        "rating_raw": " ".join(estrelas["class"]) if estrelas else None,
        "estoque_raw": tabela.get("Availability"),
        "upc": tabela.get("UPC"),
        "n_reviews_raw": tabela.get("Number of reviews"),
        "categoria_raw": links_breadcrumb[2].get_text() if len(links_breadcrumb) > 2 else None,
        "descricao": texto_ou_none(pagina.select_one("#product_description ~ p")),
    }


def raspar(paginas: int) -> list[dict]:
    with ThreadPoolExecutor(max_workers=MAX_PARALELO) as executor:
        urls = [u for lista in executor.map(links_da_pagina, range(1, paginas + 1)) for u in lista]
        return list(executor.map(extrair_livro, urls))


def gravar_bronze(livros: list[dict], execucao_id: str) -> None:
    with conectar() as conn:
        conn.execute(SQL_BRONZE.read_text(encoding="utf-8"))
        with conn.cursor() as cur:
            cur.executemany(
                "insert into bronze.livros (fonte_url, payload, _execucao_id) values (%s, %s, %s)",
                [(livro["url"], Jsonb(livro), execucao_id) for livro in livros],
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Raspa books.toscrape.com e grava na bronze.")
    parser.add_argument("--paginas", type=int, default=50, help="páginas da listagem (20 livros cada)")
    args = parser.parse_args()

    execucao_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    livros = raspar(args.paginas)
    gravar_bronze(livros, execucao_id)
    print(f"Execução {execucao_id}: {len(livros)} livros gravados em bronze.livros")


if __name__ == "__main__":
    main()
