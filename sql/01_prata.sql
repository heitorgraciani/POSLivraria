create schema if not exists prata;

create or replace view prata.livros
with (security_invoker = true)
as
with bronze_texto as (
    select
        trim(payload->>'upc')           as upc,            -- R7
        trim(payload->>'titulo')        as titulo,         -- R7
        trim(payload->>'categoria_raw') as categoria_raw,  -- R7
        trim(payload->>'preco_raw')     as preco_raw,      -- R7
        trim(payload->>'rating_raw')    as rating_raw,     -- R7
        trim(payload->>'estoque_raw')   as estoque_raw,    -- R7
        trim(payload->>'n_reviews_raw') as n_reviews_raw,  -- R7
        trim(payload->>'url')           as url,            -- R7
        _ingestao_em,
        id
    from bronze.livros
),
mais_recente as (
    select distinct on (upc) *                              -- R1
    from bronze_texto
    order by upc, _ingestao_em desc, id desc                -- R1
)
select
    upc,
    titulo,
    case
        when categoria_raw in ('Default', 'Add a comment') then 'Sem categoria'  -- R6
        else categoria_raw
    end                                                              as categoria,
    substring(preco_raw from '[0-9]+\.?[0-9]*')::numeric(10,2)       as preco_gbp,    -- R2
    case split_part(rating_raw, ' ', 2)                                                -- R3
        when 'One'   then 1                                                            -- R3
        when 'Two'   then 2                                                            -- R3
        when 'Three' then 3                                                            -- R3
        when 'Four'  then 4                                                            -- R3
        when 'Five'  then 5                                                            -- R3
    end                                                              as rating,
    coalesce(substring(estoque_raw from '([0-9]+)')::int, 0)         as estoque_qtd,  -- R4
    nullif(n_reviews_raw, '')::int                                   as n_reviews,    -- R5
    url,
    _ingestao_em
from mais_recente;
