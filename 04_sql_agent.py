import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from aplicar_sql import conectar

CAMINHO_CONTEXTO = Path(__file__).parent / "CONTEXTO.md"
SCHEMAS_DO_AGENTE = ("prata", "ouro")
SCHEMAS_DE_SISTEMA = (
    "pg_catalog", "information_schema", "pg_toast", "auth", "storage", "realtime",
    "extensions", "graphql", "graphql_public", "vault", "pgsodium", "pgsodium_masks",
    "net", "cron", "pgbouncer", "supabase_functions", "supabase_migrations",
)
MAX_TENTATIVAS = 3
LIMITE_LINHAS = 50
MODELO_PADRAO_ANTHROPIC = "claude-opus-5-5"

INSTRUCOES_AGENTE = """Você é o analista de dados da Livraria Inteligente e responde à diretoria comercial.

Regras:
- Consulte SOMENTE os schemas `prata` e `ouro`. Nunca use `bronze` nem outro schema.
- Prefira `ouro` quando a métrica já existir lá.
- Gere UM único comando SQL por vez, só SELECT (ou WITH ... SELECT), dentro de um bloco ```sql```.
- Use apenas tabelas e colunas que aparecem no schema abaixo. Não invente.
- Aplique as regras de negócio e métricas do CONTEXTO.md (moeda, câmbio, faixas, exclusão de `Sem categoria` em rankings).
- Se a pergunta for ambígua, NÃO gere SQL: faça uma pergunta curta de esclarecimento."""

INSTRUCOES_MINIMAS = "Você gera SQL PostgreSQL. Responda com UM comando SELECT dentro de um bloco ```sql```."

INSTRUCOES_RESPOSTA = """Você recebeu a pergunta, o SQL executado e o resultado.
Responda em português do Brasil, de forma curta e direta, com os números do resultado.
Indique a moeda (GBP por padrão; R$ quando pedido). Não invente valores que não estejam no resultado."""


def ler_schema(schemas: tuple[str, ...] | None) -> str:
    if schemas:
        filtro, params = "table_schema = any(%s)", [list(schemas)]
    else:
        filtro, params = "not (table_schema = any(%s)) and table_schema not like 'pg_temp%%'", [list(SCHEMAS_DE_SISTEMA)]
    sql = f"""
        select table_schema, table_name, column_name, data_type
        from information_schema.columns
        where {filtro}
        order by table_schema, table_name, ordinal_position
    """
    with conectar() as conn:
        linhas = conn.execute(sql, params).fetchall()

    tabelas: dict[str, list[str]] = {}
    for schema, tabela, coluna, tipo in linhas:
        tabelas.setdefault(f"{schema}.{tabela}", []).append(f"{coluna} {tipo}")
    return "\n".join(f"- {nome}({', '.join(colunas)})" for nome, colunas in tabelas.items())


def montar_system_prompt(com_contexto: bool) -> str:
    if not com_contexto:
        return f"{INSTRUCOES_MINIMAS}\n\n## Schema do banco\n{ler_schema(None)}"
    contexto = CAMINHO_CONTEXTO.read_text(encoding="utf-8")
    return (
        f"{INSTRUCOES_AGENTE}\n\n"
        f"## CONTEXTO.md\n{contexto}\n\n"
        f"## Schema real (prata e ouro)\n{ler_schema(SCHEMAS_DO_AGENTE)}"
    )


def chamar_llm(system: str, mensagens: list[dict]) -> str:
    provedor = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    modelo = os.getenv("LLM_MODEL", "").strip()
    if provedor == "anthropic":
        return chamar_anthropic(system, mensagens, modelo or MODELO_PADRAO_ANTHROPIC)
    if provedor == "openai":
        if not modelo:
            sys.exit("Defina LLM_MODEL no .env para usar o provedor openai.")
        return chamar_openai(system, mensagens, modelo)
    sys.exit(f"LLM_PROVIDER inválido: {provedor!r} (use openai ou anthropic)")


def chamar_anthropic(system: str, mensagens: list[dict], modelo: str) -> str:
    import anthropic

    resposta = anthropic.Anthropic().messages.create(
        model=modelo,
        max_tokens=16000,
        system=system,
        messages=mensagens,
    )
    if resposta.stop_reason == "refusal":
        return "O modelo recusou esta pergunta."
    return "".join(bloco.text for bloco in resposta.content if bloco.type == "text")


def chamar_openai(system: str, mensagens: list[dict], modelo: str) -> str:
    from openai import OpenAI

    resposta = OpenAI().chat.completions.create(
        model=modelo,
        messages=[{"role": "system", "content": system}, *mensagens],
    )
    return resposta.choices[0].message.content or ""


def extrair_sql(texto: str) -> str | None:
    bloco = re.search(r"```sql\s*(.*?)```", texto, flags=re.S | re.I)
    return bloco.group(1).strip().rstrip(";").strip() if bloco else None


def remover_comentarios(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)


def validar_sql(sql: str, com_contexto: bool) -> None:
    limpo = remover_comentarios(sql).strip()
    if not re.match(r"(?is)^(select|with)\b", limpo):
        raise ValueError("Só são permitidos comandos SELECT ou WITH.")
    if ";" in limpo:
        raise ValueError("Envie um único comando, sem ';'.")
    if com_contexto and re.search(r"(?i)\bbronze\b", limpo):
        raise ValueError("O schema bronze não pode ser consultado. Use prata ou ouro.")


def executar_sql(sql: str) -> tuple[list[str], list[tuple]]:
    with conectar() as conn:
        conn.read_only = True
        with conn.transaction():
            conn.execute("set local statement_timeout = '10s'")
            cur = conn.execute(f"select * from ({sql}) as _consulta limit {LIMITE_LINHAS}")
            return [c.name for c in cur.description], cur.fetchall()


def formatar_tabela(colunas: list[str], linhas: list[tuple]) -> str:
    cabecalho = " | ".join(colunas)
    corpo = "\n".join(" | ".join("" if v is None else str(v) for v in linha) for linha in linhas)
    return f"{cabecalho}\n{corpo}" if linhas else f"{cabecalho}\n(sem linhas)"


def gerar_e_executar(pergunta: str, system: str, com_contexto: bool, tentativas: list[dict]):
    mensagens = [{"role": "user", "content": pergunta}]
    for _ in range(MAX_TENTATIVAS):
        texto = chamar_llm(system, mensagens)
        sql = extrair_sql(texto)
        if sql is None:
            return None, texto
        tentativa = {"sql": sql, "erro": None}
        tentativas.append(tentativa)
        try:
            validar_sql(sql, com_contexto)
            return sql, executar_sql(sql)
        except Exception as erro:
            tentativa["erro"] = str(erro)
            mensagens += [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": f"O SQL falhou com o erro abaixo. Corrija e envie um novo bloco ```sql```.\n{erro}"},
            ]
    return None, f"Não consegui gerar um SQL válido em {MAX_TENTATIVAS} tentativas."


def perguntar(pergunta: str, com_contexto: bool = True) -> dict:
    system = montar_system_prompt(com_contexto)
    tentativas: list[dict] = []
    sql, resultado = gerar_e_executar(pergunta, system, com_contexto, tentativas)
    if sql is None:
        return {"tentativas": tentativas, "sql": None, "colunas": [], "linhas": [], "resposta": resultado}
    colunas, linhas = resultado
    tabela = formatar_tabela(colunas, linhas)
    resposta = chamar_llm(
        f"{system}\n\n{INSTRUCOES_RESPOSTA}",
        [{"role": "user", "content": f"Pergunta: {pergunta}\n\nSQL:\n{sql}\n\nResultado:\n{tabela}"}],
    )
    return {"tentativas": tentativas, "sql": sql, "colunas": colunas, "linhas": linhas, "resposta": resposta}


def responder(pergunta: str, com_contexto: bool) -> None:
    saida = perguntar(pergunta, com_contexto)
    for numero, tentativa in enumerate(saida["tentativas"], start=1):
        print(f"\n[SQL · tentativa {numero}]\n{tentativa['sql']}")
        if tentativa["erro"]:
            print(f"[erro] {tentativa['erro']}")
    if saida["sql"]:
        print(f"\n[resultado]\n{formatar_tabela(saida['colunas'], saida['linhas'])}")
    print(f"\n[resposta]\n{saida['resposta']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente SQL da Livraria Inteligente.")
    parser.add_argument("--sem-contexto", action="store_true", help="só instrução mínima + schema de todas as tabelas")
    parser.add_argument("--pergunta", help="responde uma pergunta e sai (sem o loop interativo)")
    args = parser.parse_args()
    load_dotenv()

    com_contexto = not args.sem_contexto
    if args.pergunta:
        responder(args.pergunta, com_contexto)
        return

    print(f"Agente SQL ({'com' if com_contexto else 'SEM'} contexto). Linha vazia ou 'sair' encerra.")
    while True:
        pergunta = input("\nPergunta: ").strip()
        if pergunta.lower() in ("", "sair"):
            break
        responder(pergunta, com_contexto)


if __name__ == "__main__":
    main()
