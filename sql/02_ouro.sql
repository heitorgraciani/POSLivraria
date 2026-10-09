create schema if not exists ouro;

create or replace view ouro.livros
with (security_invoker = true)
as
select
    p.*,
    p.preco_gbp * p.estoque_qtd  as valor_estoque_gbp,  -- M1
    case
        when p.preco_gbp < 20 then 'até £20'            -- M3
        when p.preco_gbp < 40 then '£20–40'             -- M3
        else 'acima de £40'                             -- M3
    end                          as faixa_preco,
    p.rating >= 4                as bem_avaliado        -- M2
from prata.livros p;

create or replace view ouro.categorias
with (security_invoker = true)
as
select
    categoria,
    count(*)                                                     as qtd_titulos,
    round(avg(preco_gbp), 2)                                     as preco_medio_gbp,
    round(avg(rating), 2)                                        as rating_medio,
    sum(estoque_qtd)                                             as estoque_unidades,
    sum(valor_estoque_gbp)                                       as valor_estoque_gbp,  -- M1
    round(100.0 * count(*) filter (where bem_avaliado) / count(*), 2) as pct_bem_avaliados  -- M2
from ouro.livros
group by categoria;
