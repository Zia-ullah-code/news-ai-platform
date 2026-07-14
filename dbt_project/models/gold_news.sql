-- Gold: analytics-ready enrichment of silver. One row per article.

with words as (

    select
        *,
        length(content_clean)                                   as article_length,
        array_length(string_split(content_clean, ' '))          as word_count
    from {{ ref('silver_news') }}

)

select
    article_id,
    title,
    url,
    source                                                      as source_domain,
    published,
    fetched_at,
    content_clean,
    article_length,
    word_count,
    greatest(1, cast(ceil(word_count / 200.0) as integer))      as reading_time_min,
    extract(hour from published)                                as publish_hour
from words
