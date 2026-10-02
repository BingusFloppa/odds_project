from __future__ import annotations

import pandas as pd
import streamlit as st

from odds_analytics.api import OddsApiClient
from odds_analytics.db import clear_runtime_data, get_connection, init_db
from odds_analytics.keys import add_key, order_keys, read_keys, remove_all_keys
from odds_analytics.repository import (
    bootstrap_reference_data,
    list_bookmakers,
    list_leagues,
    save_bookmaker_settings,
    save_league_settings,
    sync_leagues,
)
from odds_analytics.service import build_display_frame, fetch_selected_leagues_data, load_bets, load_data


st.set_page_config(
    page_title="Odds Analytics",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
    .app-subtitle { color: #64748b; margin-top: -0.75rem; margin-bottom: 1.25rem; }
    div[data-testid="stMetric"] {
        background: white;
        border: 1px solid #e2e8f0;
        padding: 0.75rem 1rem;
        border-radius: 0.75rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def bootstrap() -> None:
    init_db()
    bootstrap_reference_data()


bootstrap()

if "key_stats" not in st.session_state:
    st.session_state.key_stats = {}


def refresh_key_balances() -> None:
    client = OddsApiClient()
    st.session_state.key_stats = {
        key: client.check_balance(key)
        for key in read_keys()
    }


def get_ordered_api_keys() -> list[str]:
    return order_keys(read_keys(), st.session_state.key_stats)


def show_db_error(exc: Exception) -> None:
    st.error("Database connection failed. Check PostgreSQL and your .env configuration.")
    with st.expander("Technical details"):
        st.code(str(exc))


st.title("Odds Analytics")
st.markdown(
    '<div class="app-subtitle">Odds collection, fair-price modelling, value-bet tracking, and result settlement.</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Workspace")
    leagues_count = len(list_leagues())
    bookmakers_count = len(list_bookmakers())
    st.metric("Leagues in DB", leagues_count)
    st.metric("Bookmakers in DB", bookmakers_count)

    st.divider()
    st.caption("Data flow")
    st.write("The Odds API → PostgreSQL → calculations → value bets")
    st.caption(
        "Leagues and bookmakers are persistent database records. "
        "JSON files are used only for first-run seed data."
    )

tab_data, tab_bets, tab_leagues, tab_bookies, tab_settings = st.tabs(
    ["📊 Data", "💰 Bets", "🏆 Leagues", "🏢 Bookmakers", "⚙️ Settings"]
)


with tab_data:
    st.subheader("Market data")
    c1, c2 = st.columns([1, 3])
    with c1:
        fetch_clicked = st.button(
            "⬇️ Fetch & analyse",
            type="primary",
            use_container_width=True,
            help="Fetch selected leagues, save odds, settle completed matches, and recalculate value bets.",
        )
    with c2:
        st.caption(
            "Selected leagues are fetched from The Odds API. Bookmaker settings control calculations and bet discovery."
        )

    if fetch_clicked:
        leagues = list_leagues()
        selected = leagues[leagues["Select"] == True].rename(
            columns={"League Key": "league_key", "League Name": "name"}
        ).to_dict("records")
        keys = get_ordered_api_keys()

        if not selected:
            st.warning("Select at least one league in the Leagues tab.")
        elif not keys:
            st.warning("Add at least one The Odds API key in Settings.")
        else:
            progress = st.progress(0.0, text="Starting…")

            def update_progress(value, label):
                progress.progress(min(max(value, 0.0), 1.0), text=label)

            try:
                added, settled = fetch_selected_leagues_data(
                    selected,
                    keys,
                    update_progress,
                )
                progress.empty()
                st.success(
                    f"Saved {added} odds rows and updated {settled} match results."
                )
                st.rerun()
            except Exception as exc:
                progress.empty()
                show_db_error(exc)

    st.divider()

    try:
        df = load_data()
        if df.empty:
            st.info("No odds are stored yet. Select leagues and run Fetch & analyse.")
        else:
            available_bookmakers = sorted(
                df["Bookmaker"].dropna().unique().tolist()
            )
            selected_bookies = st.multiselect(
                "Filter bookmakers",
                options=available_bookmakers,
                default=available_bookmakers[:10],
            )
            filtered = (
                df[df["Bookmaker"].isin(selected_bookies)]
                if selected_bookies
                else df.iloc[0:0]
            )

            with get_connection() as conn:
                cache_df = pd.read_sql_query(
                    "SELECT hash_key, l1, l2, rho, error FROM biv_cache",
                    conn,
                )
            cache = {
                row["hash_key"]: (
                    row["l1"],
                    row["l2"],
                    row["rho"],
                    row["error"],
                )
                for _, row in cache_df.iterrows()
            }
            display_df = build_display_frame(filtered, cache)

            m1, m2, m3 = st.columns(3)
            m1.metric("Stored odds rows", f"{len(df):,}")
            m2.metric("Matches shown", f"{filtered['Match'].nunique():,}")
            m3.metric("Displayed market lines", f"{len(display_df):,}")

            if display_df.empty:
                st.info(
                    "No rows match the bookmakers currently enabled for calculation."
                )
            else:
                for col in [
                    "Odds",
                    "Margin %",
                    "Result",
                    "L1",
                    "L2",
                    "G (Rho)",
                    "Error",
                    "True Odds",
                    "Diff",
                    "Size",
                ]:
                    if col in display_df:
                        display_df[col] = pd.to_numeric(
                            display_df[col],
                            errors="coerce",
                        ).round(4 if col == "Error" else 2)

                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True,
                    height=600,
                )
    except Exception as exc:
        show_db_error(exc)


with tab_bets:
    st.subheader("Value bets")
    try:
        bets_df, total_profit = load_bets()
        if bets_df.empty:
            st.info("No value bets are stored yet.")
        else:
            settled = int(bets_df["Score"].notna().sum())
            c1, c2, c3 = st.columns(3)
            c1.metric("Value bets", f"{len(bets_df):,}")
            c2.metric("Settled", f"{settled:,}")
            c3.metric("Flat 1U profit", f"{total_profit:+.2f}")

            for col in ["Odds", "True Odds", "Edge", "Profit (U)"]:
                if col in bets_df:
                    bets_df[col] = pd.to_numeric(
                        bets_df[col],
                        errors="coerce",
                    ).round(2)

            st.dataframe(
                bets_df,
                use_container_width=True,
                hide_index=True,
                height=600,
            )
    except Exception as exc:
        show_db_error(exc)


with tab_leagues:
    st.subheader("Leagues")
    c1, c2 = st.columns([1, 2])

    with c1:
        if st.button("🔄 Sync leagues from API", use_container_width=True):
            keys = get_ordered_api_keys()
            if not keys:
                st.warning("Add an API key in Settings first.")
            else:
                with st.spinner("Loading sports from The Odds API…"):
                    response = OddsApiClient().get_sports(keys[0])

                if response.status_code == 200:
                    soccer = [
                        sport
                        for sport in response.payload
                        if "soccer" in str(sport.get("key", "")).lower()
                        or "soccer" in str(sport.get("group", "")).lower()
                    ]
                    synced = sync_leagues(soccer)
                    st.success(f"Synchronized {synced} soccer leagues.")
                    st.rerun()
                else:
                    st.error(f"API error: HTTP {response.status_code}")

    with c2:
        st.caption(
            "League selection is stored in PostgreSQL and survives app restarts."
        )

    leagues_df = list_leagues()
    if not leagues_df.empty:
        editable = leagues_df[
            ["Select", "League Name", "League Key"]
        ].copy()

        with st.form("leagues_form"):
            edited = st.data_editor(
                editable,
                column_config={
                    "Select": st.column_config.CheckboxColumn(
                        "Use",
                        default=False,
                    ),
                    "League Name": st.column_config.TextColumn(
                        disabled=True
                    ),
                    "League Key": st.column_config.TextColumn(
                        disabled=True
                    ),
                },
                use_container_width=True,
                hide_index=True,
            )

            if st.form_submit_button(
                "💾 Save league selection",
                type="primary",
                use_container_width=True,
            ):
                save_league_settings(edited.to_dict("records"))
                st.success("League settings saved.")
                st.rerun()
    else:
        st.info("No leagues in the database yet. Sync them from the API.")


with tab_bookies:
    st.subheader("Bookmakers")
    st.caption(
        "Bookmaker records and calculation settings are stored in PostgreSQL."
    )

    bookies_df = list_bookmakers()
    if bookies_df.empty:
        st.info(
            "No bookmakers are stored yet. Fetch market data once to populate this table."
        )
    else:
        editable = bookies_df[
            [
                "Bookmaker Key",
                "Bookmaker",
                "Calc Odds",
                "For Bets",
                "Build Clusters",
            ]
        ].copy()

        with st.form("bookmakers_form"):
            edited = st.data_editor(
                editable,
                column_config={
                    "Bookmaker Key": st.column_config.TextColumn(
                        disabled=True
                    ),
                    "Bookmaker": st.column_config.TextColumn(
                        disabled=True
                    ),
                    "Calc Odds": st.column_config.CheckboxColumn(
                        "Calculate odds"
                    ),
                    "For Bets": st.column_config.CheckboxColumn(
                        "Consider for bets"
                    ),
                    "Build Clusters": st.column_config.CheckboxColumn(
                        "Build clusters"
                    ),
                },
                use_container_width=True,
                hide_index=True,
            )

            if st.form_submit_button(
                "💾 Save bookmaker settings",
                type="primary",
                use_container_width=True,
            ):
                save_bookmaker_settings(edited.to_dict("records"))
                st.success("Bookmaker settings saved.")
                st.rerun()


with tab_settings:
    st.subheader("Settings & secrets")
    st.info(
        "Real API keys and database credentials are local-only and excluded by .gitignore."
    )

    keys = read_keys()
    total_tokens = sum(
        max(value, 0)
        for value in st.session_state.key_stats.values()
    )

    c1, c2 = st.columns(2)
    c1.metric("API keys configured", len(keys))
    c2.metric("Known request balance", total_tokens)

    with st.form("add_key_form", clear_on_submit=True):
        new_key = st.text_input(
            "The Odds API key",
            type="password",
        )

        if st.form_submit_button(
            "Add key",
            type="primary",
        ):
            if add_key(new_key):
                st.success("API key added locally.")
            else:
                st.warning("Key is empty or already exists.")

    if keys:
        st.write("Configured keys")
        table = []

        for key in keys:
            balance = st.session_state.key_stats.get(key)
            table.append(
                {
                    "Key": (
                        f"{key[:6]}…{key[-4:]}"
                        if len(key) > 10
                        else "••••••"
                    ),
                    "Balance": (
                        balance
                        if balance is not None and balance >= 0
                        else "Not checked"
                    ),
                }
            )

        st.dataframe(
            pd.DataFrame(table),
            use_container_width=True,
            hide_index=True,
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "🔄 Refresh balances",
                use_container_width=True,
            ):
                with st.spinner("Checking API balances…"):
                    refresh_key_balances()
                st.rerun()

        with c2:
            if st.button(
                "🗑️ Remove all local keys",
                use_container_width=True,
            ):
                remove_all_keys()
                st.session_state.key_stats = {}
                st.rerun()
    else:
        st.caption("No API keys configured locally.")

    st.divider()
    st.subheader("Database maintenance")
    st.caption(
        "This clears odds, model cache, and saved bets. "
        "Leagues and bookmakers remain intact."
    )

    if st.button(
        "🧹 Clear market data",
        type="secondary",
    ):
        clear_runtime_data()
        st.success("Market data, model cache, and bets were cleared.")
        st.rerun()
