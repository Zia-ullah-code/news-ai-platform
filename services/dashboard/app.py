"""Streamlit dashboard — the read-only face of the platform.

Standing rule 1: this app NEVER writes DuckDB. Every query opens a short-lived
read_only connection with a lock-retry, because the scheduler (the single
writer) may briefly hold the file during a cycle. Data is cached for 30s —
honest "near-real-time" for a 5-minute pipeline.

Run: streamlit run services/dashboard/app.py
"""

import time

import duckdb
import pandas as pd
import streamlit as st

from shared.config import get_settings

st.set_page_config(page_title="News Intelligence", page_icon="📰", layout="wide")

SETTINGS = get_settings()
LOCK_RETRIES = 5


@st.cache_data(ttl=30, show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    last_error = None
    for _ in range(LOCK_RETRIES):
        try:
            conn = duckdb.connect(SETTINGS.duckdb_path, read_only=True)
            try:
                return conn.execute(sql, params).fetchdf()
            finally:
                conn.close()
        except duckdb.Error as exc:  # writer briefly holds the file
            last_error = exc
            time.sleep(0.5)
    raise last_error


def table_exists(name: str) -> bool:
    try:
        return not query(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", (name,)
        ).empty
    except duckdb.Error:
        return False


SENTIMENT_ICON = {"positive": "🟢", "neutral": "⚪", "negative": "🔴"}


def render_alerts() -> None:
    st.subheader("🚨 Alerts")
    threshold = st.slider("Importance threshold", 1, 10, 7,
                          help="Articles the AI scored at or above this level")
    df = query(
        """
        SELECT g.importance, g.category, g.sentiment, g.summary, g.reason,
               g.keywords, g.processed_at, s.title, s.url, s.source, s.published
        FROM gold_ai_news g JOIN silver_news s USING (article_id)
        WHERE g.importance >= ?
        ORDER BY g.processed_at DESC, g.importance DESC
        LIMIT 50
        """,
        (threshold,),
    )
    if df.empty:
        st.info("No alerts at this threshold yet — the pipeline adds articles every cycle.")
        return
    for row in df.itertuples():
        icon = SENTIMENT_ICON.get(row.sentiment, "⚪")
        with st.container(border=True):
            st.markdown(
                f"**[{row.title}]({row.url})**  \n"
                f"`importance {row.importance}/10` · {row.category} · {icon} {row.sentiment} · {row.source}"
            )
            st.write(row.summary)
            st.caption(f"Why it matters: {row.reason}")
            st.caption("Keywords: " + ", ".join(row.keywords))


def render_latest() -> None:
    st.subheader("📰 Latest news")
    df = query(
        """
        SELECT published, title, source_domain AS source, reading_time_min AS "min read", url
        FROM gold_news ORDER BY published DESC NULLS LAST LIMIT 100
        """
    )
    st.dataframe(
        df, width='stretch', hide_index=True,
        column_config={"url": st.column_config.LinkColumn("link", display_text="open")},
    )


def render_search() -> None:
    st.subheader("🔎 Search")
    term = st.text_input("Search title and content")
    if not term:
        return
    df = query(
        """
        SELECT s.published, s.title, s.source, s.url,
               g.importance, g.category
        FROM silver_news s LEFT JOIN gold_ai_news g USING (article_id)
        WHERE s.title ILIKE '%' || ? || '%' OR s.content_clean ILIKE '%' || ? || '%'
        ORDER BY s.published DESC NULLS LAST LIMIT 100
        """,
        (term, term),
    )
    st.caption(f"{len(df)} matches")
    st.dataframe(
        df, width='stretch', hide_index=True,
        column_config={"url": st.column_config.LinkColumn("link", display_text="open")},
    )


def render_stats() -> None:
    st.subheader("📊 Statistics")
    total = query("SELECT count(*) AS n FROM silver_news").n[0]
    enriched = query("SELECT count(*) AS n FROM gold_ai_news").n[0] if table_exists("gold_ai_news") else 0
    alerts = query("SELECT count(*) AS n FROM gold_ai_news WHERE importance >= 7").n[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Articles", f"{total}")
    c2.metric("AI-enriched", f"{enriched}")
    c3.metric("Alerts (≥7)", f"{alerts}")

    left, right = st.columns(2)
    with left:
        st.caption("Articles by source")
        st.bar_chart(
            query("SELECT source, count(*) AS articles FROM silver_news GROUP BY 1"),
            x="source", y="articles",
        )
        st.caption("Publish hour (UTC)")
        st.bar_chart(
            query("SELECT publish_hour AS hour, count(*) AS articles FROM gold_news "
                  "WHERE publish_hour IS NOT NULL GROUP BY 1 ORDER BY 1"),
            x="hour", y="articles",
        )
    with right:
        st.caption("AI category spread")
        st.bar_chart(
            query("SELECT category, count(*) AS articles FROM gold_ai_news GROUP BY 1"),
            x="category", y="articles",
        )
        st.caption("Importance distribution")
        st.bar_chart(
            query("SELECT importance, count(*) AS articles FROM gold_ai_news GROUP BY 1 ORDER BY 1"),
            x="importance", y="articles",
        )


PAGES = {
    "Alerts": render_alerts,
    "Latest News": render_latest,
    "Search": render_search,
    "Statistics": render_stats,
}


def main() -> None:
    st.title("📰 News Intelligence Platform")
    if not table_exists("silver_news"):
        st.warning("No data yet — run the scheduler at least once.")
        return
    page = st.sidebar.radio("Page", list(PAGES.keys()))
    st.sidebar.caption("Data refreshes every 30s; the pipeline runs every 5 min.")
    last = query("SELECT max(run_at) AS t FROM pipeline_runs").t[0]
    st.sidebar.caption(f"Last pipeline run: {last:%Y-%m-%d %H:%M UTC}" if pd.notna(last) else "Pipeline never ran")
    PAGES[page]()


main()
