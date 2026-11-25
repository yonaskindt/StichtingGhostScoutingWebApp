import hmac
import importlib
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(BASE_DIR))

import data_manager as dm
import field_renderer as fr

importlib.reload(dm)
importlib.reload(fr)

st.set_page_config(page_title="FTC Scouting Hub", layout="wide", initial_sidebar_state="collapsed")


def _get_user_role(username: str) -> str:
    clean_user = (username or "").strip()
    try:
        roles = st.secrets.get("auth_roles", {})
        role = str(roles.get(clean_user, "admin")).strip().lower()
    except Exception:
        role = "admin"
    return role if role in {"admin", "strategist"} else "strategist"


def _check_credentials(username: str, password: str) -> tuple[bool, str]:
    try:
        users = st.secrets["auth_users"]
    except Exception:
        return False, "strategist"

    clean_user = (username or "").strip()
    if not clean_user or clean_user not in users:
        return False, "strategist"

    expected_pw = str(users[clean_user])
    entered_pw = str(password or "")
    if hmac.compare_digest(entered_pw.encode("utf-8"), expected_pw.encode("utf-8")):
        return True, _get_user_role(clean_user)
    return False, "strategist"


def _logout():
    for k in [
        "authenticated",
        "auth_user",
        "auth_role",
        "selected_team",
        "scan_feedback",
        "focus_cell_0",
        "plan_highlighted_team",
    ]:
        st.session_state.pop(k, None)
    st.rerun()


def _require_login():
    if st.session_state.get("authenticated"):
        return

    st.markdown("### 🔐 FTC Scouting Hub — Sign In")
    st.caption("Enter your team credentials to continue.")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log In", type="primary")

    if submitted:
        ok, role = _check_credentials(username, password)
        if ok:
            st.session_state.authenticated = True
            st.session_state.auth_user = username.strip()
            st.session_state.auth_role = role
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.stop()


def _num_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def _safe_pct(scored: pd.Series, attempts: pd.Series) -> pd.Series:
    valid = attempts > 0
    out = pd.Series(float("nan"), index=scored.index, dtype="float64")
    out.loc[valid] = (scored.loc[valid] / attempts.loc[valid]) * 100.0
    return out.round(1)


def _build_enriched_scouting_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return raw_df.copy()

    df = raw_df.copy()
    df["team_num"] = pd.to_numeric(df["team_num"], errors="coerce")
    df["match_num"] = pd.to_numeric(df["match_num"], errors="coerce")
    df = df.dropna(subset=["team_num", "match_num"]).copy()
    df["team_num"] = df["team_num"].astype(int)
    df["match_num"] = df["match_num"].astype(int)

    df["auto_total"] = _num_series(df, "auto_total")
    df["tele_total"] = _num_series(df, "tele_total")
    df["end_total"] = _num_series(df, "end_total")
    df["total_points"] = df["auto_total"] + df["tele_total"] + df["end_total"]

    hive_pollen_scored = _num_series(df, "hive_scored_pollen")
    hive_pollen_total = _num_series(df, "hive_total_pollen")
    hive_nectar_scored = _num_series(df, "hive_scored_nectar")
    hive_nectar_total = _num_series(df, "hive_total_nectar")

    flower_pollen_scored = _num_series(df, "flower_scored_pollen")
    flower_nectar_scored = _num_series(df, "flower_scored_nectar")
    flower_missed = _num_series(df, "flower_missed")

    df["hive_points"] = hive_pollen_scored + hive_nectar_scored
    df["flower_points"] = flower_pollen_scored + flower_nectar_scored

    auto_scored = _num_series(df, "auto_total_scored")
    auto_shots = _num_series(df, "auto_total_shot")

    flower_scored = flower_pollen_scored + flower_nectar_scored
    flower_attempts = flower_scored + flower_missed

    df["auto_accuracy_pct"] = _safe_pct(auto_scored, auto_shots)
    df["pollen_accuracy_pct"] = _safe_pct(hive_pollen_scored, hive_pollen_total)
    df["nectar_accuracy_pct"] = _safe_pct(hive_nectar_scored, hive_nectar_total)
    df["flower_accuracy_pct"] = _safe_pct(flower_scored, flower_attempts)

    df = df.sort_values(["team_num", "match_num"]).reset_index(drop=True)
    df["team_match_num"] = df.groupby("team_num").cumcount() + 1
    return df


if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "auth_role" not in st.session_state:
    st.session_state.auth_role = "strategist"

_require_login()

active_user = st.session_state.get("auth_user", "user")
active_role = st.session_state.get("auth_role", "strategist")
is_admin = active_role == "admin"

if not hasattr(fr, "render_draggable_field"):
    st.error(
        f"Loaded field_renderer from: {getattr(fr, '__file__', 'unknown')} — missing render_draggable_field. "
        f"Make sure you saved field_renderer.py in {BASE_DIR}."
    )
    st.stop()

if getattr(fr, "FIELD_IMG_PATH", None):
    fr.FIELD_IMG_PATH = str(BASE_DIR / fr.FIELD_IMG_PATH)

dm.init_storage()

NUM_CELLS = len(dm.QR_COLUMNS)  # 23 cells matching the 23 QR fields

# --- 1. VIEWPORT & DATA ENTRY SCROLL-LOCK CSS ---
scroll_lock_css = """
        /* Lock vertical scrolling when Tab 1 (Data Entry & QR Scan) is selected */
        div[data-testid="stTabs"]:has(button[aria-selected="true"]:first-of-type) {
            max-height: calc(100vh - 64px) !important;
            overflow: hidden !important;
        }
        div[data-testid="stTabs"]:has(button[aria-selected="true"]:first-of-type) div[data-testid="stTabPanel"]:first-of-type {
            max-height: calc(100vh - 108px) !important;
            overflow: hidden !important;
        }
""" if is_admin else ""

st.markdown(f"""
    <style>
        header[data-testid="stHeader"], footer {{ display: none !important; }}
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        section.main,
        .block-container {{
            max-width: 100% !important;
        }}
        .block-container {{
            padding: 0.35rem 1rem 0.5rem 1rem !important;
        }}
        {scroll_lock_css}
        div[data-testid="stButton"] button {{
            height: 2.35rem;
            font-size: 0.94rem;
            font-weight: 700;
        }}
        /* Hide all 23 scan cells cleanly while keeping them in the DOM */
        div[data-testid="stTextInput"]:has(input[aria-label^="qr_cell_"]) {{
            position: fixed !important;
            left: -9999px !important;
            top: -9999px !important;
            width: 1px !important;
            height: 1px !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }}
    </style>
""", unsafe_allow_html=True)

# --- TOP SESSION BAR (ROLE BADGE + LOG OUT) ---
role_badge = "🛡️ Admin" if is_admin else "🧭 Strategist"
bar_left, bar_right = st.columns([6, 1.2])
with bar_left:
    st.caption(f"Signed in as **{active_user}** · Role: **{role_badge}**")
with bar_right:
    if st.button("Log Out", key="btn_logout", use_container_width=True):
        _logout()

# --- 2. SESSION STATE ---
if "selected_team" not in st.session_state:
    st.session_state.selected_team = None
if "start_positions" not in st.session_state:
    st.session_state.start_positions = {}
if "scan_feedback" not in st.session_state:
    st.session_state.scan_feedback = ""
if "focus_cell_0" not in st.session_state:
    st.session_state.focus_cell_0 = False
if "plan_highlighted_team" not in st.session_state:
    st.session_state.plan_highlighted_team = None

for i in range(NUM_CELLS):
    if f"qr_c_{i}" not in st.session_state:
        st.session_state[f"qr_c_{i}"] = ""

schedule_df = dm.load_schedule()
scouting_df = dm.load_scouting_data()
start_pos_df = dm.load_start_positions()
enriched_df = _build_enriched_scouting_df(scouting_df)

if is_admin:
    tab_entry, tab_plan, tab_pick, tab_deep = st.tabs([
        "📥 Data Entry & QR Scan",
        "🗺️ Match Planning",
        "🏆 Alliance Selection",
        "📈 Team Deep Dive",
    ])
else:
    tab_entry = None
    tab_plan, tab_pick, tab_deep = st.tabs([
        "🗺️ Match Planning",
        "🏆 Alliance Selection",
        "📈 Team Deep Dive",
    ])

# ==============================================================================
# TAB 1: DATA ENTRY & QR SCANNING (ADMIN ONLY)
# ==============================================================================
if is_admin and tab_entry is not None:
    with tab_entry:
        top_col1, top_col2 = st.columns([1, 3])
        with top_col1:
            sel_match = st.selectbox("Select Match", schedule_df["match_num"].tolist(), key="entry_match")

        match_row = schedule_df[schedule_df["match_num"] == sel_match].iloc[0]
        red_teams = [int(match_row["red_1"]), int(match_row["red_2"])]
        blue_teams = [int(match_row["blue_1"]), int(match_row["blue_2"])]
        team_alliance_map = {
            red_teams[0]: "Red",
            red_teams[1]: "Red",
            blue_teams[0]: "Blue",
            blue_teams[1]: "Blue",
        }

        default_pos_map = {
            red_teams[0]: (70.0, 145.0),
            red_teams[1]: (70.0, 295.0),
            blue_teams[0]: (370.0, 145.0),
            blue_teams[1]: (370.0, 295.0),
        }

        if sel_match not in st.session_state.start_positions:
            st.session_state.start_positions[sel_match] = dict(default_pos_map)
            saved_match_pos = start_pos_df[start_pos_df["match_num"] == sel_match]
            for _, r in saved_match_pos.iterrows():
                try:
                    t_id = int(r["team_num"])
                    if not pd.isna(r["start_x"]) and not pd.isna(r["start_y"]):
                        st.session_state.start_positions[sel_match][t_id] = (
                            float(r["start_x"]),
                            float(r["start_y"]),
                        )
                except (TypeError, ValueError):
                    continue
        else:
            for t_id, xy in default_pos_map.items():
                st.session_state.start_positions[sel_match].setdefault(t_id, xy)

        completed_teams = set(
            scouting_df[scouting_df["match_num"] == sel_match]["team_num"].dropna().astype(int).tolist()
        )
        saved_pos_teams = set(
            start_pos_df[start_pos_df["match_num"] == sel_match]["team_num"].dropna().astype(int).tolist()
        )

        def clear_23_cells():
            for idx in range(NUM_CELLS):
                st.session_state[f"qr_c_{idx}"] = ""

        def save_prematch_positions():
            global start_pos_df
            payload = {}
            for t_id, alliance in team_alliance_map.items():
                xy = st.session_state.start_positions[sel_match].get(t_id, default_pos_map[t_id])
                payload[t_id] = {"x": float(xy[0]), "y": float(xy[1]), "alliance": alliance}
            ok, msg = dm.save_match_start_positions(sel_match, payload)
            start_pos_df = dm.load_start_positions()
            summary = ", ".join(f"{k}:({int(v['x'])},{int(v['y'])})" for k, v in payload.items())
            st.session_state.scan_feedback = f"{msg} [{summary}]" if ok else f"⚠️ {msg}"

        def save_from_23_cells():
            values = [str(st.session_state.get(f"qr_c_{idx}", "")).strip() for idx in range(NUM_CELLS)]
            while values and values[-1] == "":
                values.pop()

            if not values:
                return

            if not st.session_state.selected_team:
                st.session_state.scan_feedback = "⚠️ Click a team button before scanning!"
                clear_23_cells()
                return

            raw_tabbed = "\t".join(values)
            ok, msg = dm.parse_and_save_qr(raw_tabbed, sel_match, st.session_state.selected_team)
            st.session_state.scan_feedback = msg
            clear_23_cells()
            if ok:
                st.session_state.selected_team = None
                st.session_state.focus_cell_0 = False

        with top_col2:
            if st.session_state.scan_feedback:
                st.success(st.session_state.scan_feedback)
            elif st.session_state.selected_team:
                st.info(
                    f"Active: **Team {st.session_state.selected_team}** — "
                    f"Armed across {NUM_CELLS} background cells. Pull scanner trigger to scan."
                )
            else:
                st.warning("Pre-match: drag robots on the field and click 'Save Start Positions'. Post-match: click a team button and scan QR.")

        col_red, col_field, col_blue = st.columns([1, 2, 1])

        with col_red:
            st.markdown("#### 🔴 Red Alliance")
            for team in red_teams:
                done_icon = "✅" if team in completed_teams else ("📍" if team in saved_pos_teams else "⬜")
                btn_type = "primary" if st.session_state.selected_team == team else "secondary"
                if st.button(f"{done_icon} Team {team}", key=f"btn_red_{sel_match}_{team}", type=btn_type, use_container_width=True):
                    st.session_state.selected_team = team
                    st.session_state.scan_feedback = ""
                    st.session_state.focus_cell_0 = True
                    clear_23_cells()
                    st.rerun()

        with col_field:
            dragged_bots = fr.render_draggable_field(
                red_teams,
                blue_teams,
                st.session_state.start_positions[sel_match],
                key=f"field_drag_{sel_match}",
            )
            if isinstance(dragged_bots, dict):
                for t_str, b_info in dragged_bots.items():
                    try:
                        t_int = int(t_str)
                        if isinstance(b_info, dict) and "x" in b_info and "y" in b_info:
                            st.session_state.start_positions[sel_match][t_int] = (
                                float(b_info["x"]),
                                float(b_info["y"]),
                            )
                    except (TypeError, ValueError):
                        continue

            st_col1, st_col2, st_col3 = st.columns([2, 1.4, 1.1])
            with st_col1:
                active_label = (
                    f"🎯 Armed: Team {st.session_state.selected_team}"
                    if st.session_state.selected_team
                    else ("📍 Start positions saved" if len(saved_pos_teams) == 4 else "Pre-match: drag robots & save")
                )
                st.caption(active_label)
            with st_col2:
                if st.button("Save Start Positions", key="btn_save_pos", use_container_width=True):
                    save_prematch_positions()
                    st.rerun()
            with st_col3:
                if st.button("Save Scan", key="btn_save_23", use_container_width=True):
                    save_from_23_cells()
                    st.rerun()

            for i in range(NUM_CELLS):
                st.text_input(f"qr_cell_{i}", key=f"qr_c_{i}")

            arm_token = (
                f"{sel_match}_{st.session_state.selected_team}"
                if (st.session_state.focus_cell_0 and st.session_state.selected_team)
                else ""
            )
            st.session_state.focus_cell_0 = False

            components.html(f"""
                <script>
                    (function() {{
                        const pWin = window.parent;
                        const pDoc = pWin.document;
                        const numCells = {NUM_CELLS};
                        const armToken = "{arm_token}";

                        function getCell(idx) {{
                            return pDoc.querySelector('input[aria-label="qr_cell_' + idx + '"]');
                        }}

                        function commitAllCells() {{
                            for (let i = 0; i < numCells; i++) {{
                                const c = getCell(i);
                                if (c) {{
                                    c.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    c.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                }}
                            }}
                            const saveBtn = Array.from(pDoc.querySelectorAll('button'))
                                .find(b => b.innerText && b.innerText.trim() === 'Save Scan');
                            if (saveBtn) {{
                                setTimeout(() => saveBtn.click(), 80);
                            }}
                        }}

                        function bindCells() {{
                            for (let i = 0; i < numCells; i++) {{
                                const cell = getCell(i);
                                if (cell && !cell.dataset.cellBound) {{
                                    cell.dataset.cellBound = "1";
                                    cell.addEventListener('keydown', (e) => {{
                                        if (e.key === 'Tab') {{
                                            e.preventDefault();
                                            const next = getCell(Math.min(numCells - 1, i + 1));
                                            if (next) next.focus();
                                        }} else if (e.key === 'Enter') {{
                                            e.preventDefault();
                                            commitAllCells();
                                        }}
                                    }});
                                }}
                            }}
                        }}

                        bindCells();

                        if (armToken && pWin._lastArmedToken !== armToken) {{
                            pWin._lastArmedToken = armToken;
                            let attempts = 0;
                            const focusTimer = setInterval(() => {{
                                attempts++;
                                bindCells();
                                const firstCell = getCell(0);
                                if (firstCell) {{
                                    firstCell.focus();
                                    if (pDoc.activeElement === firstCell || attempts >= 20) {{
                                        clearInterval(focusTimer);
                                    }}
                                }} else if (attempts >= 20) {{
                                    clearInterval(focusTimer);
                                }}
                            }}, 50);
                        }} else if (!armToken) {{
                            pWin._lastArmedToken = null;
                        }}
                    }})();
                </script>
            """, height=0)

        with col_blue:
            st.markdown("#### 🔵 Blue Alliance")
            for team in blue_teams:
                done_icon = "✅" if team in completed_teams else ("📍" if team in saved_pos_teams else "⬜")
                btn_type = "primary" if st.session_state.selected_team == team else "secondary"
                if st.button(f"{done_icon} Team {team}", key=f"btn_blue_{sel_match}_{team}", type=btn_type, use_container_width=True):
                    st.session_state.selected_team = team
                    st.session_state.scan_feedback = ""
                    st.session_state.focus_cell_0 = True
                    clear_23_cells()
                    st.rerun()


# ==============================================================================
# TAB 2: MATCH PLANNING (ADMIN & STRATEGIST)
# ==============================================================================
with tab_plan:
    plan_top1, plan_top2 = st.columns([1.5, 2.5])
    with plan_top1:
        plan_match = st.selectbox("Plan Match", schedule_df["match_num"].tolist(), key="plan_match")

    p_row = schedule_df[schedule_df["match_num"] == plan_match].iloc[0]
    p_red = [int(p_row["red_1"]), int(p_row["red_2"])]
    p_blue = [int(p_row["blue_1"]), int(p_row["blue_2"])]
    all_plan_teams = p_red + p_blue
    p_map = {p_red[0]: "Red", p_red[1]: "Red", p_blue[0]: "Blue", p_blue[1]: "Blue"}

    if st.session_state.plan_highlighted_team not in all_plan_teams:
        st.session_state.plan_highlighted_team = None

    with plan_top2:
        hl_label = (
            f"Highlighting **Team {st.session_state.plan_highlighted_team}** on field"
            if st.session_state.plan_highlighted_team is not None
            else "Showing all match teams — click **Highlight** on a team card to focus their starts"
        )
        st.markdown(f"<br>{hl_label}", unsafe_allow_html=True)

    pos_only_df = start_pos_df.copy()

    def render_team_card(team_num: int, alliance: str):
        t_df = scouting_df[scouting_df["team_num"] == team_num]
        t_pos_df = pos_only_df[pos_only_df["team_num"] == team_num]
        if "alliance" in t_pos_df.columns:
            alliance_pos_df = t_pos_df[
                t_pos_df["alliance"].fillna("").astype(str).str.lower().isin(["", alliance.lower()])
            ]
        else:
            alliance_pos_df = t_pos_df

        if "match_num" in alliance_pos_df.columns:
            alliance_pos_df = alliance_pos_df.sort_values("match_num")

        is_highlighted = (st.session_state.plan_highlighted_team == team_num)

        with st.container(border=True):
            hdr_col, btn_col = st.columns([2.3, 1.2])
            with hdr_col:
                st.markdown(f"**Team {team_num}** ({alliance}) — *{len(t_df)} matches*")
            with btn_col:
                btn_label = "Unhighlight" if is_highlighted else "Highlight"
                btn_kind = "primary" if is_highlighted else "secondary"
                if st.button(btn_label, key=f"hl_{plan_match}_{alliance}_{team_num}", type=btn_kind, use_container_width=True):
                    st.session_state.plan_highlighted_team = None if is_highlighted else team_num
                    st.rerun()

            coord_labels = []
            for _, pr in alliance_pos_df.iterrows():
                if pd.notna(pr.get("start_x")) and pd.notna(pr.get("start_y")):
                    m_txt = f"M{int(pr['match_num'])}:" if "match_num" in pr and pd.notna(pr["match_num"]) else ""
                    coord_labels.append(f"{m_txt}({int(pr['start_x'])},{int(pr['start_y'])})")

            if coord_labels:
                st.caption(f"Starts ({len(coord_labels)}): " + ", ".join(coord_labels))
            else:
                st.caption(f"{alliance} starts recorded: 0")

            if t_df.empty:
                st.caption("No scouting data yet.")
                return

            m1, m2, m3 = st.columns(3)
            m1.metric("Auto", f"{t_df['auto_total'].mean():.1f}")
            m2.metric("Tele", f"{t_df['tele_total'].mean():.1f}")
            m3.metric("End", f"{t_df['end_total'].mean():.1f}")

            t_df = t_df.sort_values("match_num")
            t_df["Total"] = t_df["auto_total"] + t_df["tele_total"] + t_df["end_total"]
            fig_mini = px.line(t_df, x="match_num", y="Total", markers=True, height=75)
            fig_mini.update_layout(
                margin=dict(l=0, r=0, t=2, b=0),
                xaxis_title=None, yaxis_title=None,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(
                fig_mini,
                use_container_width=True,
                config={"displayModeBar": False},
                key=f"mini_chart_{plan_match}_{alliance}_{team_num}"
            )

    p_col_red, p_col_field, p_col_blue = st.columns([1.2, 1.8, 1.2])

    with p_col_red:
        for t in p_red:
            render_team_card(t, "Red")

    with p_col_field:
        plan_html = fr.render_planning_field_html(
            pos_only_df,
            p_map,
            highlighted_team=st.session_state.plan_highlighted_team,
        )
        components.html(plan_html, height=fr.FIELD_SIZE + 10)

    with p_col_blue:
        for t in p_blue:
            render_team_card(t, "Blue")


# ==============================================================================
# TAB 3: ALLIANCE SELECTION (PERFORMANCE BY TEAM MATCH #1..N)
# ==============================================================================
with tab_pick:
    if enriched_df.empty:
        st.info("Scan at least one match in the Data Entry tab to populate performance graphs.")
    else:
        all_teams = sorted(enriched_df["team_num"].unique().tolist())
        picked_teams = st.multiselect(
            "🚫 Remove Picked / Unavailable Teams from Graphs:",
            options=all_teams,
            default=[],
            key="pick_removed_teams",
        )

        filtered_df = enriched_df[~enriched_df["team_num"].isin(picked_teams)].copy()
        filtered_df["team_label"] = filtered_df["team_num"].astype(str)

        max_matches = int(filtered_df["team_match_num"].max()) if not filtered_df.empty else 1
        tick_vals = list(range(1, max_matches + 1))

        c_auto, c_tele, c_end = st.columns(3)

        def make_trend_chart(df: pd.DataFrame, y_col: str, title: str):
            fig = px.line(
                df,
                x="team_match_num",
                y=y_col,
                color="team_label",
                markers=True,
                title=title,
                height=460,
                hover_data={"match_num": True, "team_match_num": True, y_col: True},
                labels={"team_match_num": "Team Match #", "team_label": "Team"},
            )
            fig.update_xaxes(tickmode="array", tickvals=tick_vals)
            fig.update_layout(
                margin=dict(l=10, r=10, t=35, b=10),
                xaxis_title="Team Match # (1st, 2nd, ...)",
                yaxis_title="Points",
                legend=dict(orientation="h", yanchor="bottom", y=-0.28, xanchor="center", x=0.5)
            )
            return fig

        with c_auto:
            st.plotly_chart(
                make_trend_chart(filtered_df, "auto_total", "Autonomous Over Time"),
                use_container_width=True,
                key="trend_auto"
            )

        with c_tele:
            st.plotly_chart(
                make_trend_chart(filtered_df, "tele_total", "TeleOp Over Time"),
                use_container_width=True,
                key="trend_tele"
            )

        with c_end:
            st.plotly_chart(
                make_trend_chart(filtered_df, "end_total", "Post-Match Over Time"),
                use_container_width=True,
                key="trend_end"
            )


# ==============================================================================
# TAB 4: TEAM DEEP DIVE (POLLEN, NECTAR, FLOWER & SCORING TRENDS OVER TIME)
# ==============================================================================
with tab_deep:
    if enriched_df.empty:
        st.info("Scan at least one match in the Data Entry tab to inspect per-team accuracy and trends.")
    else:
        available_teams = sorted(enriched_df["team_num"].unique().tolist())
        ctrl1, ctrl2 = st.columns([1.4, 2.6])
        with ctrl1:
            selected_deep_team = st.selectbox(
                "Select Team to Analyze",
                options=available_teams,
                key="deep_dive_team",
            )

        team_hist = enriched_df[enriched_df["team_num"] == selected_deep_team].sort_values("team_match_num").copy()
        team_ticks = list(range(1, int(team_hist["team_match_num"].max()) + 1))

        latest_row = team_hist.iloc[-1]
        avg_pts = team_hist["total_points"].mean()
        latest_pts = latest_row["total_points"]
        pts_delta = latest_pts - avg_pts

        latest_pollen_acc = latest_row["pollen_accuracy_pct"]
        latest_nectar_acc = latest_row["nectar_accuracy_pct"]
        latest_flower_acc = latest_row["flower_accuracy_pct"]

        with ctrl2:
            if len(team_hist) >= 2:
                first_pts = team_hist.iloc[0]["total_points"]
                slope_pts = latest_pts - first_pts
                if slope_pts > 0.5:
                    trend_msg = f"📈 **Trending Up** (+{slope_pts:.1f} pts from Match #1 to #{int(latest_row['team_match_num'])})"
                elif slope_pts < -0.5:
                    trend_msg = f"📉 **Trending Down** ({slope_pts:.1f} pts from Match #1 to #{int(latest_row['team_match_num'])})"
                else:
                    trend_msg = "➖ **Steady / Consistent** across logged matches"
            else:
                trend_msg = "ℹ️ Only 1 match logged so far — more matches will reveal trajectory"
            st.markdown(f"<br>{trend_msg}", unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Latest Total Score", f"{latest_pts:.1f}", delta=f"{pts_delta:+.1f} vs avg ({avg_pts:.1f})")
        k2.metric(
            "Latest Pollen Accuracy",
            f"{latest_pollen_acc:.1f}%" if pd.notna(latest_pollen_acc) else "N/A",
        )
        k3.metric(
            "Latest Nectar Accuracy",
            f"{latest_nectar_acc:.1f}%" if pd.notna(latest_nectar_acc) else "N/A",
        )
        k4.metric(
            "Latest Flower Accuracy",
            f"{latest_flower_acc:.1f}%" if pd.notna(latest_flower_acc) else "N/A",
        )

        g1, g2 = st.columns(2)

        acc_melted = team_hist.melt(
            id_vars=["team_match_num", "match_num"],
            value_vars=[
                "pollen_accuracy_pct",
                "nectar_accuracy_pct",
                "flower_accuracy_pct",
                "auto_accuracy_pct",
            ],
            var_name="Metric",
            value_name="Accuracy (%)",
        ).dropna(subset=["Accuracy (%)"])

        metric_labels = {
            "pollen_accuracy_pct": "Pollen Accuracy",
            "nectar_accuracy_pct": "Nectar Accuracy",
            "flower_accuracy_pct": "Flower Accuracy",
            "auto_accuracy_pct": "Auto Accuracy",
        }
        acc_melted["Metric"] = acc_melted["Metric"].map(metric_labels)

        with g1:
            fig_acc = px.line(
                acc_melted,
                x="team_match_num",
                y="Accuracy (%)",
                color="Metric",
                markers=True,
                title=f"Team {selected_deep_team} — Accuracy by Piece & Target (%)",
                height=360,
                hover_data={"match_num": True, "team_match_num": True, "Accuracy (%)": ":.1f"},
                labels={"team_match_num": "Team Match #"},
            )
            fig_acc.update_xaxes(tickmode="array", tickvals=team_ticks)
            fig_acc.update_yaxes(range=[0, 105])
            fig_acc.update_layout(
                margin=dict(l=10, r=10, t=35, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=-0.28, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig_acc, use_container_width=True, key=f"deep_acc_{selected_deep_team}")

        phase_melted = team_hist.melt(
            id_vars=["team_match_num", "match_num"],
            value_vars=["auto_total", "hive_points", "flower_points", "end_total", "total_points"],
            var_name="Category",
            value_name="Points",
        )
        category_labels = {
            "auto_total": "Auto",
            "hive_points": "Hive",
            "flower_points": "Flower",
            "end_total": "Post-Match",
            "total_points": "Total Points",
        }
        phase_melted["Category"] = phase_melted["Category"].map(category_labels)

        with g2:
            fig_pts = px.bar(
                phase_melted[phase_melted["Category"] != "Total Points"],
                x="team_match_num",
                y="Points",
                color="Category",
                barmode="stack",
                title=f"Team {selected_deep_team} — Scoring Breakdown Over Time",
                height=360,
                hover_data={"match_num": True, "team_match_num": True, "Points": ":.1f"},
                labels={"team_match_num": "Team Match #"},
            )
            tot_only = phase_melted[phase_melted["Category"] == "Total Points"]
            fig_pts.add_scatter(
                x=tot_only["team_match_num"],
                y=tot_only["Points"],
                mode="lines+markers",
                name="Total Points",
                hovertemplate="Team Match #%{x}<br>Total Points: %{y:.1f}<extra></extra>",
            )
            fig_pts.update_xaxes(tickmode="array", tickvals=team_ticks)
            fig_pts.update_layout(
                margin=dict(l=10, r=10, t=35, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=-0.28, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig_pts, use_container_width=True, key=f"deep_pts_{selected_deep_team}")

        display_cols = [
            col for col in [
                "team_match_num",
                "match_num",
                "total_points",
                "auto_total",
                "hive_points",
                "flower_points",
                "end_total",
                "pollen_accuracy_pct",
                "nectar_accuracy_pct",
                "flower_accuracy_pct",
                "auto_accuracy_pct",
                "comments",
            ] if col in team_hist.columns
        ]
        st.dataframe(team_hist[display_cols], use_container_width=True, hide_index=True)