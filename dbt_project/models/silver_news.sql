-- Silver: one clean row per article. Dedup on article_id keeping the earliest
-- ingestion; normalize types; strip HTML from content.

with parsed as (

    select
        article_id,
        trim(payload ->> 'title')                          as title,
        payload ->> 'url'                                  as url,
        payload ->> 'source'                               as source,
        try_cast(payload ->> 'published' as timestamptz)   as published,
        try_cast(payload ->> 'fetched_at' as timestamptz)  as fetched_at,
        trim(regexp_replace(coalesce(payload ->> 'content', ''), '<[^>]*>', ' ', 'g'))
                                                           as content_clean,
        ingested_at

    from {{ source('raw', 'bronze_news') }}

)

select
    article_id,
    title,
    url,
    source,
    published,
    fetched_at,
    content_clean,
    ingested_at
from parsed
qualify row_number() over (partition by article_id order by ingested_at asc) = 1
