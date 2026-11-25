import os
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = str(BASE_DIR / "data")
SCHEDULE_PATH = os.path.join(DATA_DIR, "schedule.csv")
SCOUTING_PATH = os.path.join(DATA_DIR, "scouting_data.csv")
START_POS_PATH = os.path.join(DATA_DIR, "start_positions.csv")

START_POS_COLUMNS = [
    "match_num",
    "team_num",
    "alliance",
    "start_x",
    "start_y",
]

# Exact order of columns coming from your QR code (with Starting Position removed)
QR_COLUMNS = [
    # Pre-match
    "scouter_initials",
    "match_num",
    "team_num",
    "alliance",
    "no_show",
    # Auto
    "auto_moved",
    "auto_park",
    "auto_total_shot",
    "auto_total_scored",
    # Teleop
    "tele_pick_up",
    # Hive
    "hive_total_pollen",
    "hive_scored_pollen",
    "hive_total_nectar",
    "hive_scored_nectar",
    # Flower
    "flower_scored_pollen",
    "flower_scored_nectar",
    "flower_missed",
    # Post match
    "comments",
    "post_park",
    "driver_skill",
    "died",
    "tipped_fell",
    "defence",
]

# Derived phase totals calculated by the web app (start positions live in start_positions.csv)
META_COLUMNS = [
    "auto_total",
    "tele_total",
    "end_total",
]


def init_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SCHEDULE_PATH):
        sample_sched = pd.DataFrame([
            {"match_num": 1, "red_1": 11105, "red_2": 12345, "blue_1": 6789, "blue_2": 54321},
            {"match_num": 2, "red_1": 9999, "red_2": 11105, "blue_1": 12345, "blue_2": 8888},
        ])
        sample_sched.to_csv(SCHEDULE_PATH, index=False)

    if not os.path.exists(SCOUTING_PATH):
        df = pd.DataFrame(columns=QR_COLUMNS + META_COLUMNS)
        df.to_csv(SCOUTING_PATH, index=False)

    if not os.path.exists(START_POS_PATH):
        pos_df = pd.DataFrame(columns=START_POS_COLUMNS)
        pos_df.to_csv(START_POS_PATH, index=False)


def load_schedule() -> pd.DataFrame:
    return pd.read_csv(SCHEDULE_PATH)


def _to_num(val) -> float:
    num = pd.to_numeric(val, errors="coerce")
    return 0.0 if pd.isna(num) else float(num)


def _park_score(val) -> float:
    """Returns 1.0 when `post_park` is true, otherwise 0.0."""
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return 1.0 if float(val) != 0 else 0.0
    return 1.0 if str(val).strip().lower() == "true" else 0.0


def _recompute_phase_totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "post_park" in out.columns:
        out["end_total"] = out["post_park"].apply(_park_score)
    return out


def load_scouting_data() -> pd.DataFrame:
    if os.path.exists(SCOUTING_PATH):
        df = pd.read_csv(SCOUTING_PATH)
        return _recompute_phase_totals(df)
    return pd.DataFrame(columns=QR_COLUMNS + META_COLUMNS)


def load_start_positions() -> pd.DataFrame:
    if os.path.exists(START_POS_PATH):
        return pd.read_csv(START_POS_PATH)
    return pd.DataFrame(columns=START_POS_COLUMNS)


def save_match_start_positions(match_num: int, positions_by_team: dict) -> tuple[bool, str]:
    """
    Saves starting coordinates for a match to START_POS_PATH.
    `positions_by_team` maps int(team_num) -> {"x": ..., "y": ..., "alliance": ...} or (x, y).
    """
    init_storage()
    rows = []
    for team_num, info in positions_by_team.items():
        try:
            t_int = int(team_num)
        except (TypeError, ValueError):
            continue

        if isinstance(info, dict):
            if "x" not in info or "y" not in info:
                continue
            sx = float(info["x"])
            sy = float(info["y"])
            alliance = str(info.get("alliance", "")).strip()
        elif isinstance(info, (tuple, list)) and len(info) >= 2:
            sx = float(info[0])
            sy = float(info[1])
            alliance = ""
        else:
            continue

        rows.append({
            "match_num": int(match_num),
            "team_num": t_int,
            "alliance": alliance,
            "start_x": sx,
            "start_y": sy,
        })

    if not rows:
        return False, "No robot coordinates to save."

    df = load_start_positions()
    df = df[df["match_num"] != int(match_num)]
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    df.to_csv(START_POS_PATH, index=False)
    return True, f"Saved start positions for Match {int(match_num)} ({len(rows)} robots)"


def get_saved_start_pos(match_num: int, team_num: int) -> tuple[float, float] | None:
    pos_df = load_start_positions()
    if pos_df.empty:
        return None
    matched = pos_df[
        (pos_df["match_num"] == int(match_num)) & (pos_df["team_num"] == int(team_num))
    ]
    if matched.empty:
        return None
    row = matched.iloc[-1]
    if pd.isna(row["start_x"]) or pd.isna(row["start_y"]):
        return None
    return (float(row["start_x"]), float(row["start_y"]))


def parse_and_save_qr(raw_qr: str, selected_match: int, selected_team: int, start_pos: tuple = None) -> tuple[bool, str]:
    """Parses tab-delimited QR string and saves scouting metrics to SCOUTING_PATH."""
    cleaned = raw_qr.strip("\r\n")
    parts = cleaned.split("\t")

    if len(parts) < 3:
        return False, f"Scan failed: Expected tab-separated values, got {len(parts)} fields."

    row_data = {}
    for i, col in enumerate(QR_COLUMNS):
        val = parts[i].strip() if i < len(parts) else ""
        if val.lower() == "true":
            val = True
        elif val.lower() == "false":
            val = False
        elif val.isdigit():
            val = int(val)
        row_data[col] = val

    # Normalize Alliance ('R' -> 'Red', 'B' -> 'Blue') so field filtering matches cleanly
    raw_alliance = str(row_data.get("alliance", "")).strip().upper()
    if raw_alliance.startswith("R"):
        row_data["alliance"] = "Red"
    elif raw_alliance.startswith("B"):
        row_data["alliance"] = "Blue"

    # Enforce the UI-selected match and team
    row_data["match_num"] = int(selected_match)
    row_data["team_num"] = int(selected_team)

    # Phase totals for Tab 2, Tab 3 & Tab 4 trendlines
    row_data["auto_total"] = _to_num(row_data.get("auto_total_scored"))

    row_data["tele_total"] = (
        _to_num(row_data.get("hive_scored_pollen")) +
        _to_num(row_data.get("hive_scored_nectar")) +
        _to_num(row_data.get("flower_scored_pollen")) +
        _to_num(row_data.get("flower_scored_nectar"))
    )

    row_data["end_total"] = _park_score(row_data.get("post_park"))

    df = load_scouting_data()
    # Overwrite if this match + team was already scanned
    df = df[~((df["match_num"] == selected_match) & (df["team_num"] == selected_team))]
    df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
    df = _recompute_phase_totals(df)
    df.to_csv(SCOUTING_PATH, index=False)

    return True, f"Saved Match {selected_match} - Team {selected_team} ({len(parts)} fields parsed)"