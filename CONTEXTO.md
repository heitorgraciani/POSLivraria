# CONTEXTO.md · Memória viva do projeto

> **Leia este arquivo antes de qualquer tarefa.** Ele vence o SPEC e o PRD em caso de conflito. **Atualize ao final de cada etapa** (§1 e §5). O agente SQL também lê este arquivo inteiro.

## 1\. Estado do projeto

| etapa | status | observação |
| :---- | :---- | :---- |
| 1 · Scraping → bronze | ✅ aprovado | 3 execuções (2× `--paginas 2` no aceite + 1× `--paginas 50`): 1.080 linhas, 1.000 UPCs distintos; payload cru (`Â£`, `star-rating Three`, `In stock (N available)`) |
| 2 · Prata | ✅ aprovado | view `prata.livros`: 1.000 linhas = 1.000 UPCs; 0 nulos em preço/rating/estoque; 0 `Default`/`Add a comment` (219 → `Sem categoria`) |
| 3 · Ouro | ✅ aprovado | views `ouro.livros` e `ouro.categorias` (49 categorias): `sum(qtd_titulos)` = 1.000 = linhas da prata; `faixa_preco` só com os 3 valores de M3; M1 e M2 conferidos linha a linha |
| 4 · Agente SQL | ✅ aprovado | `claude-opus-5-5`: com contexto acerta as 4 perguntas do PRD na 1ª tentativa, só em `ouro`; nunca consultou `bronze` (nem quando pedido). Sem contexto erra a P1 (câmbio inventado e `Sem categoria` no ranking) |
| extra · Interface Streamlit | ✅ aprovado | `05_app_streamlit.py`: pergunta → mostra resposta, SQL executado e tabela do banco; toggle com/sem contexto; testado com `AppTest` (P1, P2 e sem contexto) e servidor no ar |

&nbsp;

**Próximo passo:** nenhum. Projeto concluído\. Para abrir: `python -m streamlit run 05_app_streamlit.py`\.

## 2\. Fonte de dados: books.toscrape.com

- Site público feito para treinar scraping. 50 páginas × 20 livros \= 1.000 livros.  
- Listagem: `https://books.toscrape.com/catalogue/page-{n}.html` → links em `article.product_pod h3 a`.  
- Detalhe do livro: título em `div.product_main h1`; preço em `div.product_main p.price_color`; avaliação na classe de `p.star-rating` (ex.: `star-rating Three`); tabela `table.table` com `UPC`, `Availability`, `Number of reviews`; categoria no 3º link de `ul.breadcrumb`.  
- **Encoding:** o site não declara charset. Com `requests`, o `£` costuma chegar como `Â£`. Na bronze isso fica como veio; R2 resolve na prata.  
- Campos do `payload` na bronze: `url`, `titulo`, `preco_raw`, `rating_raw`, `estoque_raw`, `upc`, `n_reviews_raw`, `categoria_raw`, `descricao`.

## 3\. Regras de negócio

**Bronze → prata**

- **R1 · Chave e duplicidade:** chave \= `upc`. Manter só a linha com o `_ingestao_em` mais recente.  
- **R2 · Preço:** extrair só o número de `preco_raw` → `preco_gbp numeric(10,2)`. Moeda \= libra (GBP).  
- **R3 · Avaliação:** `star-rating One..Five` → `rating` 1..5.  
- **R4 · Estoque:** de `In stock (22 available)` extrair `22` → `estoque_qtd int`. Sem número \= 0\.  
- **R5 · Reviews:** `n_reviews_raw` → `n_reviews int`.  
- **R6 · Categoria:** `Default` e `Add a comment` não são categorias → `Sem categoria`.  
- **R7 · Texto:** remover espaços nas pontas.

**Métricas (ouro)**

- **M1 · Valor em estoque** \= `preco_gbp × estoque_qtd`.  
- **M2 · Bem avaliado** \= `rating >= 4`.  
- **M3 · Faixa de preço:** `até £20` (\< 20\) · `£20–40` (20 a \< 40\) · `acima de £40` (≥ 40).  
- **M4 · Moeda das respostas:** GBP. Se pedirem reais, usar o câmbio de §5. Rankings de categoria **excluem** `Sem categoria`, salvo pedido explícito.

## 4\. Dicionário de dados

**prata.livros** (1 linha \= 1 livro): `upc` · `titulo` · `categoria` · `preco_gbp` · `rating` · `estoque_qtd` · `n_reviews` · `url` · `_ingestao_em`

**ouro.livros:** prata \+ `valor_estoque_gbp` (M1) · `faixa_preco` (M3) · `bem_avaliado` (M2, bool)

**ouro.categorias** (1 linha \= 1 categoria): `categoria` · `qtd_titulos` · `preco_medio_gbp` · `rating_medio` · `estoque_unidades` · `valor_estoque_gbp` · `pct_bem_avaliados`

## 5\. Decisões

| data | decisão | motivo | quem |
| :---- | :---- | :---- | :---- |
| 08/10 | Bronze append-only; dedup só na prata | preservar o que veio de cada execução | Eng. Dados |
| 08/10 | Prata e ouro como views | base pequena, sempre atualizada | Eng. Dados |
| 08/10 | Câmbio fixo **£1 \= R\$ 7,20** | relatório da diretoria em reais (valor fictício da aula) | Financeiro |
| 08/10 | Agente SQL só lê `prata` e `ouro` | bronze tem lixo e duplicidade | Eng. Dados |
| 08/10 | `_execucao_id` = timestamp UTC + 8 hex de uuid (ex.: `20261008T234541Z-1d2e25ad`) | identificar cada execução e ordenar por data | Agente (Etapa 1) |
| 08/10 | Conexão direta `db.<ref>.supabase.co:5432` (IPv6); senha com caractere especial vai URL-encoded no `.env` (`@` → `%40`) | a rede local tem IPv6; `@` cru quebra a URL | Agente (Etapa 1) |
| 08/10 | R1 desempata `_ingestao_em` igual pelo maior `id`; R7 roda antes de R1 (UPC já sem espaços) | dedup determinística | Agente (Etapa 2) |
| 08/10 | Views com `security_invoker = true` | view no Supabase ignora RLS por padrão; assim respeita as permissões de quem consulta | Agente (Etapa 2) |
| 08/10 | `ouro.categorias` **inclui** `Sem categoria`; a exclusão do M4 é feita na consulta (`where categoria <> 'Sem categoria'`) | critério da Etapa 3 exige `sum(qtd_titulos)` = linhas da prata | Agente (Etapa 3) |
| 08/10 | `pct_bem_avaliados` em escala 0–100; médias e % arredondadas em 2 casas | leitura direta pela diretoria | Agente (Etapa 3) |
| 09/10 | Agente: `LLM_MODEL` vazio + `anthropic` → `claude-opus-5-5`; para `openai`, `LLM_MODEL` é obrigatório | SPEC pede modelo por `.env`; padrão só para o provedor configurado | Agente (Etapa 4) |
| 09/10 | Com contexto, o agente **bloqueia** SQL que cite `bronze` (além da instrução no prompt); `limit 50` aplicado envolvendo o SQL em subconsulta | garantir o critério "nunca consulta bronze" mesmo se o LLM errar | Agente (Etapa 4) |
| 09/10 | `--sem-contexto` lista tabelas de todos os schemas do usuário (exclui schemas de sistema do Postgres/Supabase) | schema de "todas as tabelas" sem poluir com `auth`, `storage` etc. | Agente (Etapa 4) |
| 09/10 | Flag extra `--pergunta "..."` responde uma pergunta e sai | permite validar os critérios de aceite sem o loop interativo | Agente (Etapa 4) |
| 09/10 | Interface web em **Streamlit** (`05_app_streamlit.py`) e lib `streamlit` adicionada | pedido explícito do usuário; amplia o escopo do PRD, que deixava interface web de fora | Usuário |
| 09/10 | A interface só exibe: lógica, guardrails e contexto continuam no `04_sql_agent.py` (`perguntar()`) | um único caminho para CLI e web; mesmas regras nos dois | Agente (extra) |
| 09/10 | `.gitignore` com `.env` (e caches do Python); `.env.exemplo` continua versionável | `.env` guarda senha do banco e chave do LLM | Usuário |

&nbsp;

## 6\. Pendências

- Guardar histórico de preço (SCD2)? → fora do escopo de hoje.