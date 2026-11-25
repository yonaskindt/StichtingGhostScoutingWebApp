import base64
import json
import os
from pathlib import Path

import pandas as pd
import streamlit.components.v1 as components

BASE_DIR = Path(__file__).resolve().parent
FIELD_IMG_PATH = str(BASE_DIR / "assets" / "ftc_field.png")
FIELD_SIZE = 440  # Compact square size to fit without scrolling

_COMPONENT_DIR = str(BASE_DIR / "_ftc_field_comp")

_COMPONENT_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html, body {
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
    display: flex;
    justify-content: center;
    align-items: center;
  }
  canvas {
    border: 2px solid #444;
    border-radius: 8px;
    cursor: grab;
    background: #23272e;
    display: block;
  }
</style>
</head>
<body>
<canvas id="entryCanvas" width="__SIZE__" height="__SIZE__"></canvas>
<script>
(function() {
  const SIZE = __SIZE__;
  const BOT_SIZE = 38;
  const canvas = document.getElementById("entryCanvas");
  const ctx = canvas.getContext("2d");

  let bots = {};
  let draggingTeam = null;
  let lastSentJson = "";

  function sendToStreamlit(type, extra = {}) {
    window.parent.postMessage(Object.assign({
      isStreamlitMessage: true,
      type: type
    }, extra), "*");
  }

  function setFrameHeight(h) {
    sendToStreamlit("streamlit:setFrameHeight", { height: h });
  }

  function emitPositions(force = false) {
    const clean = {};
    for (const [team, b] of Object.entries(bots)) {
      clean[team] = {
        x: Math.round(b.x),
        y: Math.round(b.y),
        alliance: b.alliance
      };
    }
    const serialized = JSON.stringify(clean);
    if (force || serialized !== lastSentJson) {
      lastSentJson = serialized;
      sendToStreamlit("streamlit:setComponentValue", { value: clean });
    }
  }

  const bgImg = new Image();
  const imgSrc = "__IMG_SRC__";
  let imgLoaded = false;
  if (imgSrc) {
    bgImg.onload = () => {
      imgLoaded = true;
      draw();
    };
    bgImg.src = imgSrc;
  }

  function drawGrid() {
    ctx.fillStyle = "#23272e";
    ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.strokeStyle = "#3a404a";
    ctx.lineWidth = 1.5;
    const step = SIZE / 6;
    for (let i = 0; i <= SIZE; i += step) {
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, SIZE); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(SIZE, i); ctx.stroke();
    }
  }

  function draw() {
    ctx.clearRect(0, 0, SIZE, SIZE);
    if (imgSrc && imgLoaded) {
      ctx.drawImage(bgImg, 0, 0, SIZE, SIZE);
    } else {
      drawGrid();
    }

    for (const [team, b] of Object.entries(bots)) {
      const half = BOT_SIZE / 2;
      ctx.fillStyle = b.alliance === "Red" ? "rgba(235, 64, 52, 0.88)" : "rgba(52, 131, 235, 0.88)";
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = (draggingTeam === team) ? 3.5 : 2;

      ctx.beginPath();
      ctx.roundRect(b.x - half, b.y - half, BOT_SIZE, BOT_SIZE, 6);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 11px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(team, b.x, b.y);
    }
  }

  function getMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.max(BOT_SIZE / 2, Math.min(SIZE - BOT_SIZE / 2, e.clientX - rect.left)),
      y: Math.max(BOT_SIZE / 2, Math.min(SIZE - BOT_SIZE / 2, e.clientY - rect.top))
    };
  }

  canvas.addEventListener("mousedown", (e) => {
    const pos = getMousePos(e);
    for (const [team, b] of Object.entries(bots)) {
      if (Math.abs(pos.x - b.x) <= BOT_SIZE / 2 && Math.abs(pos.y - b.y) <= BOT_SIZE / 2) {
        draggingTeam = team;
        canvas.style.cursor = "grabbing";
        break;
      }
    }
  });

  canvas.addEventListener("mousemove", (e) => {
    if (!draggingTeam) return;
    const pos = getMousePos(e);
    bots[draggingTeam].x = Math.round(pos.x);
    bots[draggingTeam].y = Math.round(pos.y);
    draw();
  });

  function finishDrag() {
    if (draggingTeam) {
      draggingTeam = null;
      canvas.style.cursor = "grab";
      draw();
      emitPositions(true);
    }
  }

  window.addEventListener("mouseup", finishDrag);
  canvas.addEventListener("mouseleave", finishDrag);

  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.type !== "streamlit:render") return;
    const args = data.args || {};
    if (args.bots && !draggingTeam) {
      bots = JSON.parse(JSON.stringify(args.bots));
      lastSentJson = JSON.stringify(bots);
      draw();
    }
    setFrameHeight(SIZE + 8);
  });

  sendToStreamlit("streamlit:componentReady", { apiVersion: 1 });
  setFrameHeight(SIZE + 8);
  draw();
})();
</script>
</body>
</html>
"""


def _get_field_data_uri() -> str:
    resolved_path = Path(FIELD_IMG_PATH)
    if not resolved_path.is_absolute():
        resolved_path = BASE_DIR / resolved_path
    if resolved_path.exists():
        with open(resolved_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{b64}"
    return ""


def _ensure_component_files(img_uri: str) -> str:
    os.makedirs(_COMPONENT_DIR, exist_ok=True)
    index_path = os.path.join(_COMPONENT_DIR, "index.html")
    rendered = (
        _COMPONENT_HTML
        .replace("__SIZE__", str(FIELD_SIZE))
        .replace("__IMG_SRC__", img_uri)
    )
    existing = ""
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            existing = f.read()
    if existing != rendered:
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(rendered)
    return _COMPONENT_DIR


_draggable_field_comp = None


def render_draggable_field(red_teams: list[int], blue_teams: list[int], saved_positions: dict, key: str):
    """
    Renders an interactive draggable canvas via Streamlit's custom component protocol
    and returns a dict of {str(team): {"x": int, "y": int, "alliance": str}} whenever dragged.
    """
    global _draggable_field_comp
    img_uri = _get_field_data_uri()
    comp_dir = _ensure_component_files(img_uri)
    if _draggable_field_comp is None:
        _draggable_field_comp = components.declare_component("ftc_draggable_field", path=comp_dir)

    defaults = {
        str(red_teams[0]): {"x": 70, "y": 145, "alliance": "Red"},
        str(red_teams[1]): {"x": 70, "y": 295, "alliance": "Red"},
        str(blue_teams[0]): {"x": 370, "y": 145, "alliance": "Blue"},
        str(blue_teams[1]): {"x": 370, "y": 295, "alliance": "Blue"},
    }
    for team_str, info in defaults.items():
        team_int = int(team_str)
        if team_int in saved_positions and saved_positions[team_int]:
            info["x"], info["y"] = saved_positions[team_int]

    return _draggable_field_comp(bots=defaults, key=key, default=defaults)


def render_planning_field_html(
    df: pd.DataFrame,
    match_teams: dict,
    highlighted_team: int | None = None,
) -> str:
    """
    Renders the Match Planning field with starting outlines per robot (filtered by alliance).
    Highlights a team's outlines strongly when `highlighted_team` matches that team.
    """
    img_uri = _get_field_data_uri()
    history_by_team = {}

    for team, alliance in match_teams.items():
        t_df = df[(df["team_num"] == team) & (df["alliance"].astype(str).str.lower() == alliance.lower())]
        if "match_num" in t_df.columns:
            t_df = t_df.sort_values("match_num")
        if "start_x" in t_df.columns and "start_y" in t_df.columns:
            t_df = t_df.dropna(subset=["start_x", "start_y"])
            coords = [
                {
                    "x": float(r["start_x"]),
                    "y": float(r["start_y"]),
                    "match": int(r["match_num"]) if "match_num" in r and pd.notna(r["match_num"]) else None,
                }
                for _, r in t_df.iterrows()
            ]
        else:
            coords = []
        history_by_team[str(team)] = {"alliance": alliance, "coords": coords}

    data_json = json.dumps(history_by_team)
    active_team_json = json.dumps(str(highlighted_team) if highlighted_team is not None else None)

    return f"""
    <div style="display:flex; justify-content:center; align-items:center; width:100%;">
        <canvas id="planCanvas" width="{FIELD_SIZE}" height="{FIELD_SIZE}"
                style="border:2px solid #444; border-radius:8px; background:#23272e;"></canvas>
    </div>
    <script>
        const canvas = document.getElementById('planCanvas');
        const ctx = canvas.getContext('2d');
        const SIZE = {FIELD_SIZE};
        const BOT_SIZE = 38;
        const teamData = {data_json};
        const pinnedTeam = {active_team_json};

        const bgImg = new Image();
        const imgSrc = "{img_uri}";
        if (imgSrc) {{
            bgImg.onload = draw;
            bgImg.src = imgSrc;
        }}

        function drawGrid() {{
            ctx.fillStyle = "#23272e";
            ctx.fillRect(0, 0, SIZE, SIZE);
            ctx.strokeStyle = "#3a404a";
            ctx.lineWidth = 1.5;
            const step = SIZE / 6;
            for (let i = 0; i <= SIZE; i += step) {{
                ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, SIZE); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(SIZE, i); ctx.stroke();
            }}
        }}

        function draw() {{
            const active = pinnedTeam;
            ctx.clearRect(0, 0, SIZE, SIZE);
            if (imgSrc && bgImg.complete) {{
                ctx.drawImage(bgImg, 0, 0, SIZE, SIZE);
            }} else {{
                drawGrid();
            }}

            for (const [team, info] of Object.entries(teamData)) {{
                const isSelected = (active === team);
                const strokeAlpha = active ? (isSelected ? 0.98 : 0.14) : 0.42;
                const fillAlpha = active ? (isSelected ? 0.42 : 0.04) : 0.14;
                const rgb = info.alliance === "Red" ? "235, 64, 52" : "52, 131, 235";
                const half = BOT_SIZE / 2;

                info.coords.forEach((pt, idx) => {{
                    ctx.fillStyle = `rgba(${{rgb}}, ${{fillAlpha}})`;
                    ctx.strokeStyle = isSelected ? "#ffffff" : `rgba(${{rgb}}, ${{strokeAlpha}})`;
                    ctx.lineWidth = isSelected ? 3.5 : 1.75;
                    ctx.beginPath();
                    ctx.roundRect(pt.x - half, pt.y - half, BOT_SIZE, BOT_SIZE, 6);
                    ctx.fill();
                    ctx.stroke();

                    if (isSelected) {{
                        ctx.fillStyle = `rgba(${{rgb}}, 0.92)`;
                        ctx.beginPath();
                        ctx.roundRect(pt.x - half + 2, pt.y - half + 2, BOT_SIZE - 4, BOT_SIZE - 4, 4);
                        ctx.fill();

                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 10px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        const tag = pt.match ? `M${{pt.match}}` : `#${{idx + 1}}`;
                        ctx.fillText(tag, pt.x, pt.y);
                    }}
                }});
            }}
        }}

        draw();
    </script>
    """