import hmac
import importlib
import json
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px

import data_manager as dm
import field_renderer as fr

importlib.reload(dm)
importlib.reload(fr)

st.set_page_config(page_title="FTC Scouting Hub", layout="wide", initial_sidebar_state="collapsed")


def _check_credentials(username: str, password: str) -> bool:
    users = st.secrets.get("auth_users", {})
    clean_user = (username or "").strip()
    if clean_user not in users:
        return False
    expected_pw = str(users[clean_user])
    return hmac.compare_digest((password or "").encode("utf-8"), expected_pw.encode("utf-8"))


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
        if _check_credentials(username, password):
            st.session_state.authenticated = True
            st.session_state.auth_user = username.strip()
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.stop()


if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

_require_login()

if not hasattr(fr, "render_draggable_field"):
    st.error(
        f"Loaded field_renderer from: {getattr(fr, '__file__', 'unknown')} — missing render_draggable_field. "
        f"Make sure you saved field_renderer.py in the same directory as app.py."
    )
    st.stop()

dm.init_storage()

NUM_CELLS = len(dm.QR_COLUMNS)  # 23 cells matching the 23 QR fields

# --- 1. STRICT NO-SCROLL VIEWPORT CSS ---
st.markdown("""
    <style>
        header[data-testid="stHeader"], footer { display: none !important; }
        [data-testid="stAppViewContainer"], .main {
            height: 100vh !important;
            max-height: 100vh !important;
            overflow: hidden !important;
        }
        .block-container {
            padding: 0.4rem 1rem 0rem 1rem !important;
            max-width: 100% !important;
        }
        div[data-testid="stButton"] button {
            height: 2.6rem;
            font-size: 0.98rem;
            font-weight: 700;
        }
        /* Hide all 23 scan cells cleanly while keeping them in the DOM */
        div[data-testid="stTextInput"]:has(input[aria-label^="qr_cell_"]) {
            position: fixed !important;
            left: -9999px !important;
            top: -9999px !important;
            width: 1px !important;
            height: 1px !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }
    </style>
""", unsafe_allow_html=True)

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

tab_entry, tab_plan, tab_pick = st.tabs([
    "📥 Data Entry & QR Scan",
    "🗺️ Match Planning",
    "🏆 Alliance Selection"
])

# ==============================================================================
# TAB 1: DATA ENTRY & QR SCANNING (DRAG ROBOTS + 23 BACKGROUND CELLS)
# ==============================================================================
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
        scouting_df[scouting_df["match_num"] == sel_match]["team_num"].astype(int).tolist()
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
# TAB 2: MATCH PLANNING (HIGHLIGHT STARTING OUTLINES + COORDINATE BREAKDOWN)
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
    if scouting_df.empty:
        st.info("Scan at least one match in the Data Entry tab to populate performance graphs.")
    else:
        all_teams = sorted(scouting_df["team_num"].dropna().astype(int).unique().tolist())
        picked_teams = st.multiselect(
            "🚫 Remove Picked / Unavailable Teams from Graphs:",
            options=all_teams,
            default=[]
        )

        sequenced_df = scouting_df.copy()
        sequenced_df["team_num"] = sequenced_df["team_num"].astype(int)
        sequenced_df = sequenced_df.sort_values(["team_num", "match_num"]).reset_index(drop=True)
        sequenced_df["team_match_num"] = sequenced_df.groupby("team_num").cumcount() + 1

        filtered_df = sequenced_df[~sequenced_df["team_num"].isin(picked_teams)].copy()
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