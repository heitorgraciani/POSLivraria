import importlib
from decimal import Decimal

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
agente = importlib.import_module("04_sql_agent")

PERGUNTAS_EXEMPLO = [
    "Qual categoria tem o maior valor em estoque, em reais?",
    "Quantos livros bem avaliados custam menos de £20?",
    "Quantos livros únicos temos na base?",
    "Qual o preço médio por faixa de preço?",
]


def linhas_para_tabela(colunas: list[str], linhas: list[tuple]) -> list[dict]:
    return [
        {coluna: float(valor) if isinstance(valor, Decimal) else valor for coluna, valor in zip(colunas, linha)}
        for linha in linhas
    ]


def mostrar_saida(saida: dict) -> None:
    st.markdown(saida["resposta"])
    if saida["sql"]:
        st.caption("SQL executado")
        st.code(saida["sql"], language="sql")
        st.caption(f"Resultado do banco ({len(saida['linhas'])} linha(s), máx. {agente.LIMITE_LINHAS})")
        st.dataframe(linhas_para_tabela(saida["colunas"], saida["linhas"]), hide_index=True)
    falhas = [t for t in saida["tentativas"] if t["erro"]]
    if falhas:
        with st.expander(f"Tentativas com erro ({len(falhas)})"):
            for tentativa in falhas:
                st.code(tentativa["sql"], language="sql")
                st.error(tentativa["erro"])


st.set_page_config(page_title="Livraria Inteligente · Agente SQL", page_icon="📚")
st.title("📚 Livraria Inteligente")
st.caption("Pergunte em português. O agente gera o SQL, consulta as camadas prata/ouro e responde.")

with st.sidebar:
    com_contexto = st.toggle("Usar CONTEXTO.md", value=True, help="Desligado = modo --sem-contexto (para comparar)")
    st.markdown("**Perguntas do PRD**")
    clicados = [p for p in PERGUNTAS_EXEMPLO if st.button(p, use_container_width=True)]
    exemplo = clicados[0] if clicados else None
    if st.button("Limpar conversa", type="secondary"):
        st.session_state.historico = []

st.session_state.setdefault("historico", [])

for item in st.session_state.historico:
    with st.chat_message("user"):
        st.markdown(item["pergunta"])
        if not item["com_contexto"]:
            st.caption("sem contexto")
    with st.chat_message("assistant"):
        mostrar_saida(item["saida"])

pergunta = st.chat_input("Faça sua pergunta sobre o catálogo") or exemplo
if pergunta:
    with st.chat_message("user"):
        st.markdown(pergunta)
    with st.chat_message("assistant"):
        with st.spinner("Gerando SQL e consultando o banco..."):
            try:
                saida = agente.perguntar(pergunta, com_contexto)
            except Exception as erro:
                st.error(f"Falha ao responder: {erro}")
                st.stop()
        mostrar_saida(saida)
    st.session_state.historico.append({"pergunta": pergunta, "com_contexto": com_contexto, "saida": saida})
