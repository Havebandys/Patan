from __future__ import annotations

import base64
from pathlib import Path


def image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def global_css() -> str:
    return """
    <style>
    :root { --patan-blue:#1d91ff; --patan-cyan:#50d4ff; --panel:rgba(8,22,40,.78); --line:rgba(80,212,255,.23); }
    [data-testid="stAppViewContainer"] { background: radial-gradient(circle at 10% 0%, #102942 0%, #07111f 36%, #040912 100%); color:#eaf4ff; }
    [data-testid="stHeader"] { background: transparent; }
    /* V1 · ocultar controles administrativos de Streamlit (Deploy + menú superior). */
    [data-testid="stDeployButton"], .stDeployButton,
    button[data-testid="stDeployButton"],
    [data-testid="stAppDeployButton"], .stAppDeployButton,
    #MainMenu,
    header[data-testid="stHeader"] [data-testid="stMainMenu"],
    header[data-testid="stHeader"] button[aria-label="Main menu"],
    header[data-testid="stHeader"] button[aria-label="Deploy"] {
        display:none !important;
        visibility:hidden !important;
    }
    /* V2.1 · conservar siempre accesible el control nativo para abrir/cerrar el panel lateral. */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stExpandSidebarButton"],
    button[data-testid="stSidebarCollapseButton"],
    button[data-testid="stExpandSidebarButton"],
    button[aria-label="Collapse sidebar"],
    button[aria-label="Expand sidebar"] {
        display:flex !important;
        visibility:visible !important;
        opacity:1 !important;
        pointer-events:auto !important;
    }
    [data-testid="stSidebar"] { background: linear-gradient(180deg,#07111f 0%,#091a2d 100%); border-right:1px solid var(--line); }
    .block-container { max-width: 1500px; padding-top: 1.1rem; padding-bottom: 2rem; }
    .patan-title { letter-spacing:.34rem; font-weight:800; font-size:2.05rem; margin:0; }
    .patan-sub { letter-spacing:.14rem; color:#83c8ff; font-size:.78rem; text-transform:uppercase; }
    .glass { background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:16px 18px; box-shadow:0 18px 50px rgba(0,0,0,.25); }
    .metric-card { background:linear-gradient(180deg,rgba(15,42,68,.95),rgba(7,20,36,.95)); border:1px solid var(--line); border-radius:16px; padding:15px 17px; min-height:104px; }
    .metric-value { font-size:2rem; font-weight:800; }
    .metric-label { color:#a9c8df; font-size:.76rem; text-transform:uppercase; letter-spacing:.09rem; }
    .status-green { border-left:5px solid #36d17c; }
    .status-yellow { border-left:5px solid #ffd84d; }
    .status-red { border-left:5px solid #ff5353; }
    .status-blue { border-left:5px solid #4aa8ff; }
    div[data-testid="stButton"] button { border-radius:12px; border:1px solid rgba(80,212,255,.35); }
    /* V13.4 · lenguaje visual armónico */
    div[data-testid="stButton"] button[kind="primary"] {
        background:linear-gradient(90deg,#0d78b5 0%,#18a7c8 100%) !important;
        border:1px solid rgba(86,218,255,.62) !important;
        color:#f6fbff !important;
        box-shadow:0 8px 22px rgba(0,104,160,.20) !important;
        font-weight:750 !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background:linear-gradient(90deg,#1188c8 0%,#20b6d4 100%) !important;
        border-color:#74e4ff !important;
        transform:translateY(-1px);
    }

    /* V19 desde V18 · botones compactos y celestes, sin rojo en el área principal. */
    [data-testid="stMain"] div[data-testid="stButton"],
    [data-testid="stMain"] [data-testid="stFormSubmitButton"],
    [data-testid="stMain"] [data-testid="stDownloadButton"] {
        width:auto !important; display:flex !important; justify-content:flex-start !important;
    }
    [data-testid="stMain"] div[data-testid="stButton"] button,
    [data-testid="stMain"] [data-testid="stFormSubmitButton"] button,
    [data-testid="stMain"] [data-testid="stDownloadButton"] button,
    [data-testid="stMain"] button[data-testid="stBaseButton-primary"],
    [data-testid="stMain"] button[data-testid="stBaseButton-secondary"] {
        width:auto !important; min-width:118px !important; min-height:36px !important; height:36px !important;
        padding:.34rem .95rem !important; border-radius:10px !important;
        background:linear-gradient(90deg,#0d86bd 0%,#18a9c5 100%) !important;
        border:1px solid rgba(102,226,255,.72) !important;
        color:#ffffff !important; font-weight:750 !important; letter-spacing:.025rem !important;
        box-shadow:0 7px 18px rgba(0,120,175,.18) !important;
    }
    [data-testid="stMain"] div[data-testid="stButton"] button:hover,
    [data-testid="stMain"] [data-testid="stFormSubmitButton"] button:hover,
    [data-testid="stMain"] [data-testid="stDownloadButton"] button:hover,
    [data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover,
    [data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover {
        background:linear-gradient(90deg,#1297ce 0%,#20b9d1 100%) !important;
        border-color:#83ecff !important; color:#ffffff !important;
        transform:translateY(-1px); box-shadow:0 8px 20px rgba(0,120,175,.22) !important;
    }

    .patan-sidebar-version {
        display:flex; align-items:center; justify-content:center; gap:.46rem; width:max-content;
        margin:-.10rem 0 .52rem 0; padding:.26rem .60rem; border-radius:999px;
        background:rgba(13,134,189,.11); border:1px solid rgba(80,212,255,.30);
        box-shadow:0 0 16px rgba(24,169,197,.07); color:#7fcde9; font-weight:800;
    }
    .patan-sidebar-version span { font-size:.52rem; opacity:.72; letter-spacing:.08rem; }
    .patan-sidebar-version b { font-size:.68rem; color:#50d4ff; letter-spacing:.10rem; }
    .patan-pct-strip { display:grid; grid-template-columns:repeat(3,1fr); gap:.42rem; max-width:340px; margin:.15rem auto .25rem auto; }
    .patan-pct-strip span { display:grid; grid-template-columns:auto 1fr; grid-template-rows:auto auto; column-gap:.42rem; align-items:center; padding:.38rem .5rem; border-radius:12px; background:rgba(10,34,55,.76); border:1px solid rgba(80,212,255,.18); }
    .patan-pct-strip .patan-dot { width:9px; height:9px; border-radius:50%; grid-row:1/3; display:inline-block; }
    .patan-pct-strip .green { background:#35d07f; } .patan-pct-strip .yellow { background:#f2c94c; } .patan-pct-strip .red { background:#ff5b5b; }
    .patan-pct-strip b { font-size:1.08rem; line-height:1; color:#f2f8ff; }
    .patan-pct-strip small { font-size:.53rem; color:#8fb5cf; letter-spacing:.05rem; margin-top:.08rem; }
    .patan-class-strip {
        display:flex; justify-content:center; gap:.55rem; flex-wrap:wrap;
        margin:.15rem 0 .1rem 0;
    }
    .patan-class-strip span {
        display:inline-flex; align-items:center; justify-content:center; gap:.35rem;
        padding:.34rem .62rem; border-radius:999px;
        background:rgba(10,34,55,.88); border:1px solid rgba(80,212,255,.22);
        color:#dcecff; font-size:.72rem; letter-spacing:.02rem;
    }
    .patan-class-strip b { color:#64d8ff; }
    .patan-export-label {
        margin-top:.45rem; margin-bottom:.15rem; text-align:left;
        color:#7fdcff; font-size:.72rem; font-weight:800; letter-spacing:.10rem;
    }
    div[data-testid="stForm"] { background:rgba(5,17,30,.55); border:1px solid var(--line); border-radius:16px; padding:1rem; }
    [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
    .patan-version { display:none !important; }
    .patan-brand-paw { display:flex; align-items:center; justify-content:center; width:100%; margin:.2rem 0 .15rem 0; }
    .patan-brand-paw img { width:145px; height:145px; object-fit:contain; filter:drop-shadow(0 0 10px rgba(80,212,255,.22)); }
    .patan-sol { display:flex; align-items:center; justify-content:center; width:100%; margin:-.30rem 0 .28rem 0; cursor:help; overflow:visible; }
    .patan-sol img { width:166px; height:166px; object-fit:contain; object-position:center; border-radius:0; filter:drop-shadow(0 0 11px rgba(246,200,75,.24)); display:block; }
    @keyframes patanPulse { 0%,100%{opacity:1;box-shadow:0 0 0 rgba(80,212,255,0)} 50%{opacity:.42;box-shadow:0 0 18px rgba(80,212,255,.28)} }
    .patan-blink { animation:patanPulse 1.05s infinite; border-radius:10px; padding:8px 10px; margin:7px 0 9px 0; font-weight:800; letter-spacing:.04rem; font-size:.78rem; }
    .patan-alert-blue { color:#dff7ff; border:1px solid rgba(80,212,255,.68); background:rgba(29,145,255,.18); }
    .patan-alert-yellow { color:#fff1a9; border:1px solid rgba(255,216,77,.7); background:rgba(116,88,8,.24); }
    div[data-baseweb="tooltip"] > div, [role="tooltip"] { background:#0b2037 !important; color:#f3f9ff !important; border:1px solid #50d4ff !important; border-radius:10px !important; box-shadow:0 12px 34px rgba(0,0,0,.42) !important; font-size:.82rem !important; line-height:1.35 !important; }
    [data-testid="stTooltipIcon"] svg { color:#50d4ff !important; }
    /* V22 · ajuste exclusivo del lateral: todo entra sin scroll a 100% de navegador. */
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] { overflow-y:hidden !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] { gap:.05rem !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] label { min-height:24px !important; padding-top:0 !important; padding-bottom:0 !important; }
    [data-testid="stSidebar"] hr { margin:.38rem 0 .48rem 0 !important; }
    [data-testid="stSidebar"] [data-testid="stButton"] { margin-top:0 !important; }
    /* V13: preview ejecutivo realmente apaisado: usa casi todo el viewport. */
    [data-testid="stDialog"] [role="dialog"] { width:94vw !important; max-width:1600px !important; }
    [data-testid="stDialog"] [role="dialog"] > div { max-width:none !important; }
    /* PATÁN V12: escritura operativa siempre en MAYÚSCULAS. Las claves no se transforman. */
    input:not([type="password"]), textarea { text-transform:uppercase !important; }
    input:not([type="password"])::placeholder, textarea::placeholder { text-transform:uppercase !important; }
    </style>
    """



def splash_css(bg_path: Path) -> str:
    b64 = image_b64(bg_path)
    return f"""
    <style>
    html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"] {{
      width:100%; height:100%; overflow:hidden;
    }}
    [data-testid="stAppViewContainer"] {{
      background-image:url('data:image/png;base64,{b64}');
      background-size:cover;
      background-position:center center;
      background-repeat:no-repeat;
      background-color:#031426;
    }}
    [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"],
    [data-testid="stDecoration"], footer {{ display:none !important; }}
    input:not([type="password"]) {{ text-transform:uppercase !important; }}
    input:not([type="password"])::placeholder {{ text-transform:uppercase !important; }}
    .block-container {{
      position:relative !important; width:100vw !important; max-width:none !important;
      height:100vh !important; padding:0 !important; margin:0 !important; z-index:20 !important;
    }}
    .patan-splash-mask {{ display:none !important; }}

    /* V3 FIX: controles REALES sobre el acceso dibujado del lienzo. */
    [data-testid="stTextInput"] {{
      position:fixed !important;
      left:calc(50% - 37px) !important;
      bottom:18.0vh !important;
      transform:translateX(-50%) !important;
      width:244px !important;
      max-width:244px !important;
      margin:0 !important;
      z-index:50 !important;
    }}
    [data-testid="stTextInput"] > div > div,
    [data-testid="stTextInput"] [data-baseweb="input"] {{
      background:rgba(2,20,36,.18) !important;
      border:1px solid rgba(112,207,238,.34) !important;
      border-radius:9px !important;
      min-height:38px !important; height:38px !important;
      backdrop-filter:blur(2px) !important; -webkit-backdrop-filter:blur(2px) !important;
      box-shadow:none !important;
    }}
    [data-testid="stTextInput"] > div > div:focus-within,
    [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{
      border-color:rgba(118,224,255,.78) !important;
      box-shadow:0 0 0 1px rgba(94,210,245,.10) !important;
    }}
    [data-testid="stTextInput"] input {{
      color:#e9f7ff !important; background:transparent !important;
      font-size:11px !important; letter-spacing:.035rem !important;
      padding:0 11px !important; height:36px !important;
    }}
    [data-testid="stTextInput"] input::placeholder {{
      color:rgba(210,232,245,.58) !important; opacity:1 !important;
    }}

    [data-testid="stButton"] {{
      position:fixed !important;
      left:calc(50% + 126px) !important;
      bottom:18.0vh !important;
      width:42px !important;
      height:38px !important;
      margin:0 !important;
      z-index:51 !important;
    }}
    [data-testid="stButton"] button {{
      width:38px !important; min-width:38px !important;
      height:38px !important; min-height:38px !important;
      padding:0 !important; margin:0 !important;
      border-radius:50% !important;
      border:1px solid rgba(112,207,238,.45) !important;
      background:rgba(4,35,55,.24) !important;
      color:#dff7ff !important;
      font-size:18px !important; font-weight:400 !important;
      box-shadow:none !important;
      backdrop-filter:blur(2px) !important; -webkit-backdrop-filter:blur(2px) !important;
    }}
    [data-testid="stButton"] button:hover {{
      background:rgba(15,91,119,.40) !important;
      border-color:#72dfff !important;
    }}

    .splash-error {{
      position:fixed !important; left:50% !important; bottom:6.0vh !important; transform:translateX(-50%) !important;
      width:auto !important; min-width:190px !important; z-index:60 !important; text-align:center !important;
      color:#ffdfe3 !important; background:rgba(75,14,27,.50) !important;
      border:1px solid rgba(255,113,127,.36) !important; border-radius:8px !important;
      padding:5px 10px !important; font-size:.68rem !important; backdrop-filter:blur(4px) !important;
    }}
    @media (max-width:760px) {{
      [data-testid="stTextInput"] {{ left:calc(50% - 24px) !important; bottom:9vh !important; width:62vw !important; max-width:244px !important; }}
      [data-testid="stButton"] {{ left:calc(50% + 118px) !important; bottom:9vh !important; }}
      .splash-error {{ bottom:2.2vh !important; }}
    }}
    </style>
    """

def login_css(bg_path: Path) -> str:
    b64 = image_b64(bg_path)
    return f"""
    <style>
    html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"] {{
      width:100%; height:100%; overflow:hidden;
    }}
    [data-testid="stAppViewContainer"] {{
      background-image:url('data:image/png;base64,{b64}');
      background-size:100% 100%;
      background-position:center center;
      background-repeat:no-repeat;
      background-attachment:fixed;
      background-color:#041426;
    }}
    [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"],
    [data-testid="stDecoration"], footer {{ display:none !important; }}

    .block-container {{
      position:relative !important; width:100vw !important; max-width:none !important;
      height:100vh !important; padding:0 !important; margin:0 !important; z-index:20 !important;
    }}
    .patan-login-mask, .patan-login-heading {{ display:none !important; }}

    /* Segunda puerta simple, igual al criterio de la portada: PIN + flecha. */
    [data-testid="stForm"] {{
      position:fixed !important;
      left:50% !important;
      bottom:8.2vh !important;
      transform:translateX(-50%) !important;
      width:304px !important;
      height:40px !important;
      padding:0 !important; margin:0 !important;
      background:transparent !important; border:0 !important; box-shadow:none !important;
      overflow:visible !important; z-index:40 !important;
    }}
    [data-testid="stForm"] > div,
    [data-testid="stForm"] [data-testid="stVerticalBlock"] {{
      padding:0 !important; margin:0 !important; background:transparent !important;
      border:0 !important; box-shadow:none !important; gap:0 !important;
    }}

    [data-testid="stTextInput"] {{
      position:absolute !important;
      left:0 !important; top:0 !important;
      width:244px !important; max-width:244px !important;
      margin:0 !important; padding:0 !important;
    }}
    /* Sin contenedor duplicado: sólo el input funcional lleva borde. */
    [data-testid="stTextInput"] > div,
    [data-testid="stTextInput"] > div > div {{
      width:244px !important;
      margin:0 !important; padding:0 !important;
      background:transparent !important;
      border:0 !important; outline:0 !important;
      box-shadow:none !important;
    }}
    [data-testid="stTextInput"] [data-baseweb="input"] {{
      width:244px !important; height:38px !important; min-height:38px !important;
      background:rgba(2,20,36,.22) !important;
      border:1px solid rgba(112,207,238,.38) !important;
      border-radius:9px !important;
      box-shadow:none !important;
      backdrop-filter:blur(2px) !important; -webkit-backdrop-filter:blur(2px) !important;
    }}
    [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{
      border-color:rgba(118,224,255,.78) !important;
      box-shadow:0 0 0 1px rgba(94,210,245,.10) !important;
    }}
    [data-testid="stTextInput"] input {{
      color:#e9f7ff !important; background:transparent !important;
      font-size:12px !important; letter-spacing:.18rem !important;
      padding:0 12px !important; height:36px !important;
    }}
    [data-testid="stTextInput"] input::placeholder {{
      color:rgba(210,232,245,.58) !important; opacity:1 !important;
    }}
    [data-testid="stTextInput"] button {{ display:none !important; }}
    [data-testid="InputInstructions"], [data-testid="stTextInput"] small,
    [data-testid="stTextInput"] [aria-live="polite"],
    [data-testid="stTextInput"] div[role="status"] {{ display:none !important; }}

    [data-testid="stFormSubmitButton"] {{
      position:absolute !important;
      left:258px !important; top:0 !important;
      width:42px !important; height:38px !important;
      margin:0 !important; padding:0 !important;
    }}
    [data-testid="stFormSubmitButton"] button {{
      width:38px !important; min-width:38px !important;
      height:38px !important; min-height:38px !important;
      padding:0 !important; margin:0 !important;
      border-radius:50% !important;
      border:1px solid rgba(112,207,238,.45) !important;
      background:rgba(4,35,55,.24) !important;
      color:#dff7ff !important;
      font-size:18px !important; font-weight:400 !important;
      box-shadow:none !important;
      backdrop-filter:blur(2px) !important; -webkit-backdrop-filter:blur(2px) !important;
    }}
    [data-testid="stFormSubmitButton"] button:hover {{
      background:rgba(15,91,119,.40) !important;
      border-color:#72dfff !important;
    }}

    .login-error {{
      position:fixed !important;
      left:50% !important; bottom:2.5vh !important; transform:translateX(-50%) !important;
      width:auto !important; min-width:150px !important; z-index:50 !important;
      text-align:center !important; color:#ffe5e8 !important;
      background:rgba(84,14,27,.58) !important; border:1px solid rgba(255,105,120,.44) !important;
      border-radius:8px !important; padding:5px 10px !important; font-size:.72rem !important;
      backdrop-filter:blur(4px) !important;
    }}

    @media (max-width:900px) {{
      [data-testid="stForm"] {{ bottom:6.5vh !important; transform:translateX(-50%) scale(.90) !important; }}
      .login-error {{ bottom:1.2vh !important; }}
    }}
    </style>
    """
