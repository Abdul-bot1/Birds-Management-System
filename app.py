"""
Aviary Manager
==============
A single-file Streamlit application implementing the Aviary / Parrot
Management System PRD. Uses a local, persistent SQLite database
(created automatically next to this script) for birds, species
categories, photos (stored as blobs), and season-based egg records.

Run locally:
    streamlit run app.py

No external API keys are required. If you deploy this behind a
Cloudflare Tunnel, just point the tunnel at the local Streamlit port
(default 8501) - no code changes needed here.
"""

import io
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from PIL import Image

# ----------------------------------------------------------------------
# CONFIG / CONSTANTS
# ----------------------------------------------------------------------

# The database used to be opened with a bare relative filename ("aviary.db").
# That resolves against whatever the *current working directory* happens to
# be when Streamlit is launched - which changes between sessions/restarts on
# many hosts, making it look like "the data disappears". Anchoring the path
# to the folder this script lives in (and allowing an override via an
# environment variable for platforms that provide a persistent disk/volume)
# makes storage reliable and consistent every time the portal is opened.
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("AVIARY_DB_PATH", str(BASE_DIR / "aviary.db"))

GENDERS = ["Unknown", "Male", "Female"]
STATUSES = ["Active", "Sold", "Deceased", "Transferred"]
THUMB_SIZE = (300, 300)

st.set_page_config(page_title="Aviary Manager", page_icon="🦜", layout="wide")

# ----------------------------------------------------------------------
# ACCESS CONTROL
# ----------------------------------------------------------------------
# A single shared password gate. Everyone who logs in reaches the exact
# same portal and the exact same database - there is no per-user data
# separation, so "your data" is simply the only data that exists here.
# Set your own password via Streamlit secrets (recommended) with a key
# named APP_PASSWORD in .streamlit/secrets.toml, e.g.:
#     APP_PASSWORD = "your-secret-here"
# If no secret is configured, the app falls back to the DEFAULT_PASSWORD
# below purely so the app is usable out of the box - change it before
# sharing the link with anyone.
DEFAULT_PASSWORD = "parrot123"


def get_app_password():
    try:
        return st.secrets["APP_PASSWORD"]
    except Exception:
        return DEFAULT_PASSWORD


# ----------------------------------------------------------------------
# THEME / STYLING
# ----------------------------------------------------------------------
# A warm jungle-aviary palette (emerald canopy, teal sky, mango + coral
# feather accents) plus a soft layered gradient "scenery" backdrop. Built
# entirely from CSS gradients/SVG so it renders instantly with no external
# image downloads or licensing concerns.

CUSTOM_CSS = """
<style>
:root{
    --canopy-deep:#0b3d2e;
    --canopy:#146356;
    --canopy-light:#1f8a70;
    --sky:#2a9d8f;
    --sky-soft:#8ecae6;
    --mango:#f4a261;
    --coral:#e76f51;
    --gold:#ffd166;
    --cream:#fdf6ec;
    --ink:#0f2e26;
}

/* App background: layered dusk-jungle gradient with a soft canopy glow */
[data-testid="stAppViewContainer"]{
    background:
        radial-gradient(circle at 15% 15%, rgba(255,209,102,0.18), transparent 40%),
        radial-gradient(circle at 85% 10%, rgba(231,111,81,0.16), transparent 45%),
        radial-gradient(circle at 50% 100%, rgba(142,202,230,0.20), transparent 55%),
        linear-gradient(160deg, #0b3d2e 0%, #146356 35%, #1f8a70 65%, #2a9d8f 100%);
    background-attachment: fixed;
}

/* Subtle "leaf canopy" texture overlay using layered SVG dots/leaves */
[data-testid="stAppViewContainer"]::before{
    content:"";
    position:fixed;
    inset:0;
    pointer-events:none;
    opacity:0.08;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='%23ffffff'%3E%3Cpath d='M20 10c15 0 25 10 25 25S35 60 20 60 -5 50 -5 35 5 10 20 10z' opacity='0.5'/%3E%3Ccircle cx='90' cy='30' r='10'/%3E%3Ccircle cx='60' cy='90' r='14'/%3E%3Ccircle cx='100' cy='100' r='7'/%3E%3C/g%3E%3C/svg%3E");
    background-size: 260px 260px;
}

[data-testid="stHeader"]{
    background: rgba(0,0,0,0);
}

/* Sidebar: deeper canopy tone with a gold accent edge */
[data-testid="stSidebar"]{
    background: linear-gradient(190deg, #0b3d2e 0%, #0f4a3a 60%, #146356 100%);
    border-right: 3px solid var(--gold);
}
[data-testid="stSidebar"] *{
    color: var(--cream) !important;
}
[data-testid="stSidebar"] button{
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,209,102,0.35) !important;
    border-radius: 10px !important;
    transition: all 0.15s ease-in-out;
}
[data-testid="stSidebar"] button:hover{
    background: linear-gradient(90deg, var(--mango), var(--coral)) !important;
    border-color: var(--coral) !important;
    color: var(--ink) !important;
    transform: translateY(-1px);
}

/* Headings pop with a warm gradient glow */
h1, h2, h3{
    color: var(--cream) !important;
    text-shadow: 0 2px 10px rgba(0,0,0,0.25);
}
h1{
    background: linear-gradient(90deg, var(--gold), var(--mango), var(--coral));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    display: inline-block;
    font-weight: 800 !important;
}

/* General body text a touch brighter for contrast against the dark canopy */
p, span, label, .stMarkdown, .stCaption, [data-testid="stMetricLabel"]{
    color: var(--cream) !important;
}
[data-testid="stMetricValue"]{
    color: var(--gold) !important;
    font-weight: 800 !important;
}

/* Card containers (bird tiles, category tiles, season records) get a
   frosted-glass panel so photos and colours underneath still show through */
[data-testid="stContainer"] > div[data-testid="stVerticalBlockBorderWrapper"]{
    background: rgba(253,246,236,0.10);
    border: 1px solid rgba(255,209,102,0.30) !important;
    border-radius: 16px !important;
    backdrop-filter: blur(6px);
    box-shadow: 0 6px 20px rgba(0,0,0,0.18);
}

/* Buttons: mango-to-coral gradient, gold on hover */
.stButton > button{
    background: linear-gradient(90deg, var(--sky), var(--canopy-light));
    color: var(--cream);
    border: 1px solid rgba(255,255,255,0.25);
    border-radius: 10px;
    font-weight: 600;
    transition: all 0.15s ease-in-out;
}
.stButton > button:hover{
    background: linear-gradient(90deg, var(--mango), var(--coral));
    color: var(--ink);
    border-color: var(--gold);
    transform: translateY(-1px);
    box-shadow: 0 4px 14px rgba(231,111,81,0.35);
}

/* Primary form-submit buttons stand out in gold */
[data-testid="stFormSubmitButton"] button{
    background: linear-gradient(90deg, var(--gold), var(--mango)) !important;
    color: var(--ink) !important;
    font-weight: 700 !important;
    border: none !important;
}

/* Inputs: cream frosted fields for readability on a dark backdrop */
input, textarea, [data-baseweb="select"] > div{
    background: rgba(253,246,236,0.92) !important;
    color: var(--ink) !important;
    border-radius: 8px !important;
}

/* Expanders and dividers */
[data-testid="stExpander"]{
    background: rgba(253,246,236,0.08);
    border: 1px solid rgba(255,209,102,0.25) !important;
    border-radius: 12px !important;
}
hr{
    border-color: rgba(255,209,102,0.35) !important;
}

/* Metrics row container */
[data-testid="stMetric"]{
    background: rgba(253,246,236,0.10);
    border: 1px solid rgba(255,209,102,0.25);
    border-radius: 14px;
    padding: 10px 14px;
}
</style>
"""


def inject_theme():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ----------------------------------------------------------------------
# DATABASE LAYER
# ----------------------------------------------------------------------


@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    with closing(conn.cursor()) as cur:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS id_seq (
                name TEXT PRIMARY KEY,
                next_val INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                category_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                icon BLOB,
                sort_order INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS birds (
                bird_id TEXT PRIMARY KEY,
                ring_number TEXT UNIQUE NOT NULL,
                category_id INTEGER,
                gender TEXT DEFAULT 'Unknown',
                father_id TEXT,
                mother_id TEXT,
                partner_id TEXT,
                cage_location TEXT,
                status TEXT DEFAULT 'Active',
                date_of_birth TEXT,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(category_id) REFERENCES categories(category_id) ON DELETE SET NULL,
                FOREIGN KEY(father_id) REFERENCES birds(bird_id),
                FOREIGN KEY(mother_id) REFERENCES birds(bird_id),
                FOREIGN KEY(partner_id) REFERENCES birds(bird_id)
            );

            CREATE TABLE IF NOT EXISTS photos (
                photo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                bird_id TEXT NOT NULL,
                image BLOB NOT NULL,
                is_primary INTEGER DEFAULT 0,
                uploaded_at TEXT,
                FOREIGN KEY(bird_id) REFERENCES birds(bird_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS egg_seasons (
                season_id INTEGER PRIMARY KEY AUTOINCREMENT,
                bird_id TEXT NOT NULL,
                season_label TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                notes TEXT,
                FOREIGN KEY(bird_id) REFERENCES birds(bird_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS egg_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER NOT NULL,
                lay_date TEXT,
                egg_count INTEGER DEFAULT 1,
                notes TEXT,
                FOREIGN KEY(season_id) REFERENCES egg_seasons(season_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            "INSERT OR IGNORE INTO id_seq (name, next_val) VALUES ('bird', 1)"
        )
        conn.commit()


def next_bird_id():
    conn = get_connection()
    with closing(conn.cursor()) as cur:
        cur.execute("UPDATE id_seq SET next_val = next_val + 1 WHERE name='bird'")
        cur.execute("SELECT next_val FROM id_seq WHERE name='bird'")
        val = cur.fetchone()["next_val"] - 1
        conn.commit()
    return f"B-{val:05d}"


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ---- Category helpers --------------------------------------------------


def list_categories():
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM categories ORDER BY sort_order ASC, name ASC"
    ).fetchall()


def get_category(category_id):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM categories WHERE category_id=?", (category_id,)
    ).fetchone()


def add_category(name, description, icon_bytes):
    conn = get_connection()
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM categories"
    ).fetchone()["m"]
    conn.execute(
        "INSERT INTO categories (name, description, icon, sort_order) VALUES (?,?,?,?)",
        (name.strip(), description, icon_bytes, max_order + 1),
    )
    conn.commit()


def update_category(category_id, name, description, icon_bytes=None):
    conn = get_connection()
    if icon_bytes is not None:
        conn.execute(
            "UPDATE categories SET name=?, description=?, icon=? WHERE category_id=?",
            (name.strip(), description, icon_bytes, category_id),
        )
    else:
        conn.execute(
            "UPDATE categories SET name=?, description=? WHERE category_id=?",
            (name.strip(), description, category_id),
        )
    conn.commit()


def delete_category(category_id):
    conn = get_connection()
    conn.execute("DELETE FROM categories WHERE category_id=?", (category_id,))
    conn.commit()


def move_category(category_id, direction):
    """direction: -1 (up) or +1 (down)"""
    conn = get_connection()
    cats = list_categories()
    ids = [c["category_id"] for c in cats]
    idx = ids.index(category_id)
    swap_idx = idx + direction
    if 0 <= swap_idx < len(ids):
        a, b = cats[idx], cats[swap_idx]
        conn.execute(
            "UPDATE categories SET sort_order=? WHERE category_id=?",
            (b["sort_order"], a["category_id"]),
        )
        conn.execute(
            "UPDATE categories SET sort_order=? WHERE category_id=?",
            (a["sort_order"], b["category_id"]),
        )
        conn.commit()


def bird_count_for_category(category_id):
    conn = get_connection()
    return conn.execute(
        "SELECT COUNT(*) AS c FROM birds WHERE category_id=?", (category_id,)
    ).fetchone()["c"]


# ---- Bird helpers --------------------------------------------------


def ring_number_owner(ring_number, exclude_bird_id=None):
    conn = get_connection()
    if exclude_bird_id:
        row = conn.execute(
            "SELECT bird_id FROM birds WHERE ring_number=? AND bird_id<>?",
            (ring_number, exclude_bird_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT bird_id FROM birds WHERE ring_number=?", (ring_number,)
        ).fetchone()
    return row["bird_id"] if row else None


def get_bird(bird_id):
    conn = get_connection()
    return conn.execute("SELECT * FROM birds WHERE bird_id=?", (bird_id,)).fetchone()


def list_birds(category_id=None, search=None, gender=None, location=None,
                partnered=None, status=None):
    conn = get_connection()
    q = "SELECT * FROM birds WHERE 1=1"
    params = []
    if category_id is not None:
        q += " AND category_id=?"
        params.append(category_id)
    if search:
        q += " AND (bird_id LIKE ? OR ring_number LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if gender and gender != "Any":
        q += " AND gender=?"
        params.append(gender)
    if location:
        q += " AND cage_location LIKE ?"
        params.append(f"%{location}%")
    if partnered == "Partnered":
        q += " AND partner_id IS NOT NULL"
    elif partnered == "Unpartnered":
        q += " AND partner_id IS NULL"
    if status and status != "Any":
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY ring_number ASC"
    return conn.execute(q, params).fetchall()


def set_partner_link(bird_id, new_partner_id):
    """Handles bidirectional partner assignment, clearing old links as needed."""
    conn = get_connection()
    current = get_bird(bird_id)
    old_partner_id = current["partner_id"] if current else None

    # Clear old partner's link back to this bird
    if old_partner_id and old_partner_id != new_partner_id:
        conn.execute(
            "UPDATE birds SET partner_id=NULL, updated_at=? WHERE bird_id=? AND partner_id=?",
            (now_iso(), old_partner_id, bird_id),
        )

    if new_partner_id:
        # If the new partner already had a different partner, break that link too
        other = get_bird(new_partner_id)
        if other and other["partner_id"] and other["partner_id"] != bird_id:
            conn.execute(
                "UPDATE birds SET partner_id=NULL, updated_at=? WHERE bird_id=?",
                (now_iso(), other["partner_id"]),
            )
        conn.execute(
            "UPDATE birds SET partner_id=?, updated_at=? WHERE bird_id=?",
            (bird_id, now_iso(), new_partner_id),
        )
    conn.commit()


def add_bird(ring_number, category_id, gender, father_id, mother_id, partner_id,
             cage_location, status, dob, notes):
    conn = get_connection()
    bird_id = next_bird_id()
    ts = now_iso()
    conn.execute(
        """INSERT INTO birds
           (bird_id, ring_number, category_id, gender, father_id, mother_id,
            partner_id, cage_location, status, date_of_birth, notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (bird_id, ring_number.strip(), category_id, gender, father_id or None,
         mother_id or None, None, cage_location, status,
         dob.isoformat() if isinstance(dob, date) else dob, notes, ts, ts),
    )
    conn.commit()
    if partner_id:
        set_partner_link(bird_id, partner_id)
    return bird_id


def update_bird(bird_id, ring_number, category_id, gender, father_id, mother_id,
                 partner_id, cage_location, status, dob, notes):
    conn = get_connection()
    conn.execute(
        """UPDATE birds SET ring_number=?, category_id=?, gender=?, father_id=?,
           mother_id=?, cage_location=?, status=?, date_of_birth=?, notes=?, updated_at=?
           WHERE bird_id=?""",
        (ring_number.strip(), category_id, gender, father_id or None, mother_id or None,
         cage_location, status, dob.isoformat() if isinstance(dob, date) else dob,
         notes, now_iso(), bird_id),
    )
    conn.commit()
    current = get_bird(bird_id)
    if current["partner_id"] != partner_id:
        set_partner_link(bird_id, partner_id)


def delete_bird(bird_id):
    conn = get_connection()
    ts = now_iso()
    # Clear dangling references first so linked profiles show "record removed"
    conn.execute("UPDATE birds SET father_id=NULL, updated_at=? WHERE father_id=?", (ts, bird_id))
    conn.execute("UPDATE birds SET mother_id=NULL, updated_at=? WHERE mother_id=?", (ts, bird_id))
    conn.execute("UPDATE birds SET partner_id=NULL, updated_at=? WHERE partner_id=?", (ts, bird_id))
    conn.execute("DELETE FROM birds WHERE bird_id=?", (bird_id,))
    conn.commit()


# ---- Photo helpers --------------------------------------------------


def add_photo(bird_id, image_bytes, make_primary=False):
    conn = get_connection()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail(THUMB_SIZE)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    data = buf.getvalue()

    if make_primary:
        conn.execute("UPDATE photos SET is_primary=0 WHERE bird_id=?", (bird_id,))
    has_any = conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE bird_id=?", (bird_id,)
    ).fetchone()["c"]
    is_primary = 1 if (make_primary or has_any == 0) else 0
    conn.execute(
        "INSERT INTO photos (bird_id, image, is_primary, uploaded_at) VALUES (?,?,?,?)",
        (bird_id, data, is_primary, now_iso()),
    )
    conn.commit()


def list_photos(bird_id):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM photos WHERE bird_id=? ORDER BY is_primary DESC, uploaded_at ASC",
        (bird_id,),
    ).fetchall()


def get_primary_photo(bird_id):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM photos WHERE bird_id=? ORDER BY is_primary DESC, uploaded_at ASC LIMIT 1",
        (bird_id,),
    ).fetchone()


def delete_photo(photo_id):
    conn = get_connection()
    conn.execute("DELETE FROM photos WHERE photo_id=?", (photo_id,))
    conn.commit()


def set_primary_photo(bird_id, photo_id):
    conn = get_connection()
    conn.execute("UPDATE photos SET is_primary=0 WHERE bird_id=?", (bird_id,))
    conn.execute("UPDATE photos SET is_primary=1 WHERE photo_id=?", (photo_id,))
    conn.commit()


# ---- Egg record helpers --------------------------------------------------


def list_seasons(bird_id):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM egg_seasons WHERE bird_id=? ORDER BY start_date DESC, season_id DESC",
        (bird_id,),
    ).fetchall()


def add_season(bird_id, label, start, end, notes):
    conn = get_connection()
    conn.execute(
        "INSERT INTO egg_seasons (bird_id, season_label, start_date, end_date, notes) VALUES (?,?,?,?,?)",
        (bird_id, label.strip(), start.isoformat() if isinstance(start, date) else start,
         end.isoformat() if isinstance(end, date) else end, notes),
    )
    conn.commit()


def delete_season(season_id):
    conn = get_connection()
    conn.execute("DELETE FROM egg_seasons WHERE season_id=?", (season_id,))
    conn.commit()


def list_entries(season_id):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM egg_entries WHERE season_id=? ORDER BY lay_date ASC", (season_id,)
    ).fetchall()


def add_entry(season_id, lay_date, egg_count, notes):
    conn = get_connection()
    conn.execute(
        "INSERT INTO egg_entries (season_id, lay_date, egg_count, notes) VALUES (?,?,?,?)",
        (season_id, lay_date.isoformat() if isinstance(lay_date, date) else lay_date,
         egg_count, notes),
    )
    conn.commit()


def delete_entry(entry_id):
    conn = get_connection()
    conn.execute("DELETE FROM egg_entries WHERE entry_id=?", (entry_id,))
    conn.commit()


# ---- Stats helpers --------------------------------------------------


def stat_total_birds():
    conn = get_connection()
    return conn.execute("SELECT COUNT(*) c FROM birds").fetchone()["c"]


def stat_by_category():
    conn = get_connection()
    return conn.execute(
        """SELECT c.name AS name, COUNT(b.bird_id) AS cnt
           FROM categories c LEFT JOIN birds b ON b.category_id = c.category_id
           GROUP BY c.category_id ORDER BY cnt DESC"""
    ).fetchall()


def stat_by_location():
    conn = get_connection()
    return conn.execute(
        """SELECT COALESCE(NULLIF(TRIM(cage_location),''),'(unassigned)') AS loc, COUNT(*) AS cnt
           FROM birds GROUP BY loc ORDER BY cnt DESC"""
    ).fetchall()


def stat_breeding_pairs():
    conn = get_connection()
    return conn.execute(
        "SELECT COUNT(*) c FROM birds WHERE partner_id IS NOT NULL"
    ).fetchone()["c"] // 2


def stat_egg_by_season():
    conn = get_connection()
    return conn.execute(
        """SELECT es.season_label AS label, COALESCE(SUM(ee.egg_count),0) AS total
           FROM egg_seasons es LEFT JOIN egg_entries ee ON ee.season_id = es.season_id
           GROUP BY es.season_label ORDER BY label ASC"""
    ).fetchall()


# ----------------------------------------------------------------------
# NAVIGATION HELPERS
# ----------------------------------------------------------------------


def goto(page, **kwargs):
    st.session_state["page"] = page
    for k, v in kwargs.items():
        st.session_state[k] = v
    st.rerun()


def init_state():
    st.session_state.setdefault("page", "dashboard")
    st.session_state.setdefault("selected_category", None)
    st.session_state.setdefault("selected_bird", None)
    st.session_state.setdefault("edit_bird_mode", False)


def bird_display_name(bird_id):
    if not bird_id:
        return None
    b = get_bird(bird_id)
    if not b:
        return f"{bird_id} (record removed)"
    return f"{b['ring_number']} ({b['bird_id']})"


def bird_picker(label, key, exclude_bird_id=None, allow_none=True):
    conn = get_connection()
    rows = conn.execute("SELECT bird_id, ring_number FROM birds ORDER BY ring_number").fetchall()
    options = [""] if allow_none else []
    id_map = {}
    for r in rows:
        if exclude_bird_id and r["bird_id"] == exclude_bird_id:
            continue
        disp = f"{r['ring_number']} ({r['bird_id']})"
        options.append(disp)
        id_map[disp] = r["bird_id"]
    current_display = ""
    default_val = st.session_state.get(key + "_default")
    if default_val:
        current_display = bird_display_name(default_val) or ""
    idx = options.index(current_display) if current_display in options else 0
    chosen = st.selectbox(label, options, index=idx, key=key)
    return id_map.get(chosen)


# ----------------------------------------------------------------------
# UI: LOGIN GATE
# ----------------------------------------------------------------------


def render_login():
    st.markdown(
        """
        <div style="text-align:center; margin-top:40px; margin-bottom:10px;">
            <h1 style="font-size:3rem;">🦜 Aviary Manager</h1>
            <p style="font-size:1.1rem; opacity:0.9;">Your private aviary, exactly as you left it.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.container(border=True):
            st.markdown("### 🔐 Enter Password")
            with st.form("login_form"):
                pwd = st.text_input("Password", type="password", label_visibility="collapsed",
                                     placeholder="Password")
                submitted = st.form_submit_button("Enter Aviary", use_container_width=True)
                if submitted:
                    if pwd == get_app_password():
                        st.session_state["authenticated"] = True
                        st.rerun()
                    else:
                        st.error("Incorrect password. Please try again.")


def require_login():
    st.session_state.setdefault("authenticated", False)
    if not st.session_state["authenticated"]:
        render_login()
        st.stop()


# ----------------------------------------------------------------------
# UI: SIDEBAR
# ----------------------------------------------------------------------


def render_sidebar():
    with st.sidebar:
        st.markdown("## 🦜 Aviary Manager")
        if st.button("🏠 Dashboard", use_container_width=True):
            goto("dashboard")
        if st.button("🗂️ All Parrots", use_container_width=True):
            goto("categories")
        if st.button("🥚 Breeding / Egg Records", use_container_width=True):
            goto("breeding")
        if st.button("📊 Statistics", use_container_width=True):
            goto("stats")
        if st.button("⚙️ Settings", use_container_width=True):
            goto("settings")

        st.markdown("---")
        if st.button("🚪 Log Out", use_container_width=True):
            st.session_state["authenticated"] = False
            st.rerun()

        st.markdown("---")
        st.markdown("**Global Search**")
        q = st.text_input("Ring number or Bird ID", key="global_search_box", label_visibility="collapsed",
                           placeholder="Search ring # or bird ID...")
        if q:
            results = list_birds(search=q)
            if results:
                for b in results[:8]:
                    if st.button(f"{b['ring_number']} — {b['bird_id']}", key=f"gs_{b['bird_id']}",
                                 use_container_width=True):
                        goto("bird", selected_bird=b["bird_id"], edit_bird_mode=False)
            else:
                st.caption("No matching birds.")


# ----------------------------------------------------------------------
# UI: DASHBOARD
# ----------------------------------------------------------------------


def render_dashboard():
    st.title("Dashboard")
    cats = list_categories()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Birds", stat_total_birds())
    c2.metric("Species Categories", len(cats))
    c3.metric("Breeding Pairs", stat_breeding_pairs())
    egg_total = sum(r["total"] for r in stat_egg_by_season())
    c4.metric("Eggs Logged (all-time)", egg_total)

    st.markdown("### All Parrots")
    if not cats:
        st.info("No species categories yet. Add one below to get started.")
    else:
        cols = st.columns(4)
        for i, cat in enumerate(cats):
            with cols[i % 4]:
                with st.container(border=True):
                    if cat["icon"]:
                        st.image(cat["icon"], use_container_width=True)
                    st.markdown(f"**{cat['name']}**")
                    st.caption(f"{bird_count_for_category(cat['category_id'])} birds")
                    if st.button("Open", key=f"open_cat_{cat['category_id']}", use_container_width=True):
                        goto("category", selected_category=cat["category_id"])

    with st.expander("➕ Add Category"):
        with st.form("add_cat_form", clear_on_submit=True):
            name = st.text_input("Species / Breed Name")
            desc = st.text_area("Description (optional)")
            icon = st.file_uploader("Icon / Photo (optional)", type=["png", "jpg", "jpeg"])
            submitted = st.form_submit_button("Create Category")
            if submitted:
                if not name.strip():
                    st.error("Name is required.")
                elif any(c["name"].lower() == name.strip().lower() for c in cats):
                    st.error("A category with this name already exists.")
                else:
                    icon_bytes = icon.read() if icon else None
                    add_category(name, desc, icon_bytes)
                    st.success(f"Category '{name}' created.")
                    st.rerun()

    st.markdown("### Flock Snapshot")
    colA, colB = st.columns(2)
    with colA:
        st.markdown("**Birds by Species**")
        by_cat = stat_by_category()
        if by_cat:
            st.bar_chart({r["name"]: r["cnt"] for r in by_cat})
    with colB:
        st.markdown("**Birds by Location**")
        by_loc = stat_by_location()
        if by_loc:
            st.bar_chart({r["loc"]: r["cnt"] for r in by_loc})


# ----------------------------------------------------------------------
# UI: CATEGORIES (list / manage)
# ----------------------------------------------------------------------


def render_categories():
    st.title("All Parrots — Species Categories")
    if st.button("← Back to Dashboard"):
        goto("dashboard")

    cats = list_categories()
    if not cats:
        st.info("No categories yet.")

    for i, cat in enumerate(cats):
        with st.container(border=True):
            cols = st.columns([1, 3, 1, 1, 1, 1])
            if cat["icon"]:
                cols[0].image(cat["icon"], width=80)
            with cols[1]:
                st.markdown(f"**{cat['name']}**")
                st.caption(cat["description"] or "")
                st.caption(f"{bird_count_for_category(cat['category_id'])} birds")
            if cols[2].button("Open", key=f"catlist_open_{cat['category_id']}"):
                goto("category", selected_category=cat["category_id"])
            if cols[3].button("↑", key=f"catlist_up_{cat['category_id']}"):
                move_category(cat["category_id"], -1)
                st.rerun()
            if cols[4].button("↓", key=f"catlist_down_{cat['category_id']}"):
                move_category(cat["category_id"], 1)
                st.rerun()
            if cols[5].button("🗑️", key=f"catlist_del_{cat['category_id']}"):
                st.session_state[f"confirm_del_cat_{cat['category_id']}"] = True

            if st.session_state.get(f"confirm_del_cat_{cat['category_id']}"):
                n_birds = bird_count_for_category(cat["category_id"])
                if n_birds > 0:
                    st.warning(
                        f"This category has {n_birds} bird(s). Reassign or delete them first, "
                        f"or confirm to delete the category (birds will become uncategorized)."
                    )
                else:
                    st.warning("Delete this category?")
                cc1, cc2 = st.columns(2)
                if cc1.button("Confirm Delete", key=f"confirm_yes_{cat['category_id']}"):
                    delete_category(cat["category_id"])
                    st.session_state.pop(f"confirm_del_cat_{cat['category_id']}", None)
                    st.rerun()
                if cc2.button("Cancel", key=f"confirm_no_{cat['category_id']}"):
                    st.session_state.pop(f"confirm_del_cat_{cat['category_id']}", None)
                    st.rerun()

            with st.expander("Edit"):
                with st.form(f"edit_cat_{cat['category_id']}"):
                    new_name = st.text_input("Name", value=cat["name"])
                    new_desc = st.text_area("Description", value=cat["description"] or "")
                    new_icon = st.file_uploader("Replace icon", type=["png", "jpg", "jpeg"],
                                                 key=f"icon_{cat['category_id']}")
                    if st.form_submit_button("Save"):
                        update_category(cat["category_id"], new_name, new_desc,
                                         new_icon.read() if new_icon else None)
                        st.success("Saved.")
                        st.rerun()


# ----------------------------------------------------------------------
# UI: CATEGORY DETAIL (birds in a species)
# ----------------------------------------------------------------------


def render_category_detail():
    cat_id = st.session_state.get("selected_category")
    cat = get_category(cat_id) if cat_id else None
    if not cat:
        st.error("Category not found.")
        if st.button("← Back"):
            goto("categories")
        return

    if st.button("← Back to All Parrots"):
        goto("categories")

    st.title(f"{cat['name']}")
    if cat["description"]:
        st.caption(cat["description"])

    c1, c2, c3, c4 = st.columns(4)
    search = c1.text_input("Search within this species (ring # or ID)")
    gender_f = c2.selectbox("Gender", ["Any"] + GENDERS)
    location_f = c3.text_input("Location contains")
    partnered_f = c4.selectbox("Partnered status", ["Any", "Partnered", "Unpartnered"])

    if st.button("➕ Add Bird to this Species"):
        goto("add_bird", selected_category=cat_id)

    birds = list_birds(category_id=cat_id, search=search or None, gender=gender_f,
                        location=location_f or None, partnered=partnered_f)

    if not birds:
        st.info("No birds match your filters.")
    cols = st.columns(4)
    for i, b in enumerate(birds):
        with cols[i % 4]:
            with st.container(border=True):
                photo = get_primary_photo(b["bird_id"])
                if photo:
                    st.image(photo["image"], use_container_width=True)
                else:
                    st.caption("No photo")
                st.markdown(f"**{b['ring_number']}**")
                st.caption(f"{b['bird_id']} · {b['gender']} · {b['status']}")
                if b["cage_location"]:
                    st.caption(f"📍 {b['cage_location']}")
                st.caption("💞 Partnered" if b["partner_id"] else "Unpartnered")
                if st.button("View Profile", key=f"view_{b['bird_id']}", use_container_width=True):
                    goto("bird", selected_bird=b["bird_id"], edit_bird_mode=False)


# ----------------------------------------------------------------------
# UI: ADD BIRD FORM
# ----------------------------------------------------------------------


def render_add_bird():
    st.title("Add New Bird")
    if st.button("← Cancel"):
        goto("categories")

    cats = list_categories()
    if not cats:
        st.warning("Create a species category first.")
        return
    cat_names = {c["name"]: c["category_id"] for c in cats}
    default_cat_id = st.session_state.get("selected_category")
    default_name = next((c["name"] for c in cats if c["category_id"] == default_cat_id), list(cat_names)[0])

    with st.form("add_bird_form"):
        ring_number = st.text_input("Ring Number *")
        species_name = st.selectbox("Species / Category *", list(cat_names.keys()),
                                     index=list(cat_names.keys()).index(default_name))
        gender = st.selectbox("Gender *", GENDERS)
        status = st.selectbox("Status", STATUSES, index=0)
        dob = st.date_input("Date of Birth / Hatch Date", value=None)
        cage_location = st.text_input("Cage / Aviary Location")
        father_id = bird_picker("Father (optional)", key="father_picker_add")
        mother_id = bird_picker("Mother (optional)", key="mother_picker_add")
        partner_id = bird_picker("Partner (optional)", key="partner_picker_add")
        notes = st.text_area("Notes")
        photos = st.file_uploader("Photos", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

        submitted = st.form_submit_button("Save Bird")
        if submitted:
            if not ring_number.strip():
                st.error("Ring Number is required.")
            elif ring_number_owner(ring_number):
                owner = ring_number_owner(ring_number)
                st.error(f"This ring number is already used by Bird {owner}.")
            else:
                bird_id = add_bird(
                    ring_number, cat_names[species_name], gender, father_id, mother_id,
                    partner_id, cage_location, status, dob, notes,
                )
                if photos:
                    for idx, p in enumerate(photos):
                        add_photo(bird_id, p.read(), make_primary=(idx == 0))
                st.success(f"Bird {bird_id} added.")
                goto("bird", selected_bird=bird_id, edit_bird_mode=False)


# ----------------------------------------------------------------------
# UI: BIRD PROFILE
# ----------------------------------------------------------------------


def render_bird_profile():
    bird_id = st.session_state.get("selected_bird")
    bird = get_bird(bird_id) if bird_id else None
    if not bird:
        st.error("Bird not found.")
        if st.button("← Back to Dashboard"):
            goto("dashboard")
        return

    top = st.columns([1, 1, 1, 5])
    if top[0].button("← Back"):
        goto("categories" if not bird["category_id"] else "category",
             selected_category=bird["category_id"])
    edit_mode = top[1].toggle("Edit", value=st.session_state.get("edit_bird_mode", False))
    st.session_state["edit_bird_mode"] = edit_mode
    if top[2].button("🗑️ Delete Bird"):
        st.session_state["confirm_delete_bird"] = True

    if st.session_state.get("confirm_delete_bird"):
        st.warning(f"Delete bird {bird['ring_number']} ({bird['bird_id']})? This cannot be undone. "
                   f"Linked parent/partner records on other birds will show as removed.")
        c1, c2 = st.columns(2)
        if c1.button("Confirm Delete", key="confirm_del_bird_yes"):
            cat_id = bird["category_id"]
            delete_bird(bird_id)
            st.session_state.pop("confirm_delete_bird", None)
            goto("category" if cat_id else "categories", selected_category=cat_id)
        if c2.button("Cancel", key="confirm_del_bird_no"):
            st.session_state.pop("confirm_delete_bird", None)
            st.rerun()

    st.title(f"{bird['ring_number']}")
    st.caption(f"Bird ID: {bird['bird_id']}")

    left, right = st.columns([1, 2])

    with left:
        st.subheader("Photos")
        photos = list_photos(bird_id)
        if photos:
            pcols = st.columns(2)
            for i, p in enumerate(photos):
                with pcols[i % 2]:
                    st.image(p["image"], use_container_width=True,
                              caption="Primary" if p["is_primary"] else None)
                    if not p["is_primary"] and st.button("Set primary", key=f"prim_{p['photo_id']}"):
                        set_primary_photo(bird_id, p["photo_id"])
                        st.rerun()
                    if st.button("Delete photo", key=f"delphoto_{p['photo_id']}"):
                        delete_photo(p["photo_id"])
                        st.rerun()
        else:
            st.caption("No photos yet.")

        new_photos = st.file_uploader("Add photo(s)", type=["png", "jpg", "jpeg"],
                                       accept_multiple_files=True, key="add_photo_uploader")
        if new_photos and st.button("Upload"):
            for p in new_photos:
                add_photo(bird_id, p.read())
            st.success("Photo(s) uploaded.")
            st.rerun()

    with right:
        if not edit_mode:
            cat = get_category(bird["category_id"]) if bird["category_id"] else None
            st.markdown(f"**Species:** {cat['name'] if cat else '—'}")
            st.markdown(f"**Gender:** {bird['gender']}")
            st.markdown(f"**Status:** {bird['status']}")
            st.markdown(f"**Date of Birth:** {bird['date_of_birth'] or '—'}")
            st.markdown(f"**Cage / Location:** {bird['cage_location'] or '—'}")

            def link_row(label, ref_id):
                col1, col2 = st.columns([1, 3])
                col1.markdown(f"**{label}:**")
                if ref_id:
                    ref = get_bird(ref_id)
                    if ref:
                        if col2.button(f"{ref['ring_number']} ({ref['bird_id']})", key=f"link_{label}_{ref_id}"):
                            goto("bird", selected_bird=ref_id, edit_bird_mode=False)
                    else:
                        col2.caption("(record removed)")
                else:
                    col2.caption("—")

            link_row("Father", bird["father_id"])
            link_row("Mother", bird["mother_id"])
            link_row("Partner", bird["partner_id"])

            st.markdown("**Notes:**")
            st.write(bird["notes"] or "—")
        else:
            cats = list_categories()
            cat_names = {c["name"]: c["category_id"] for c in cats}
            current_cat = get_category(bird["category_id"]) if bird["category_id"] else None
            with st.form("edit_bird_form"):
                ring_number = st.text_input("Ring Number", value=bird["ring_number"])
                species_name = st.selectbox(
                    "Species / Category", list(cat_names.keys()),
                    index=list(cat_names.keys()).index(current_cat["name"]) if current_cat else 0,
                )
                gender = st.selectbox("Gender", GENDERS, index=GENDERS.index(bird["gender"]) if bird["gender"] in GENDERS else 0)
                status = st.selectbox("Status", STATUSES, index=STATUSES.index(bird["status"]) if bird["status"] in STATUSES else 0)
                dob_val = None
                if bird["date_of_birth"]:
                    try:
                        dob_val = date.fromisoformat(bird["date_of_birth"])
                    except ValueError:
                        dob_val = None
                dob = st.date_input("Date of Birth", value=dob_val)
                cage_location = st.text_input("Cage / Location", value=bird["cage_location"] or "")

                st.session_state["father_picker_edit_default"] = bird["father_id"]
                st.session_state["mother_picker_edit_default"] = bird["mother_id"]
                st.session_state["partner_picker_edit_default"] = bird["partner_id"]
                father_id = bird_picker("Father", key="father_picker_edit", exclude_bird_id=bird_id)
                mother_id = bird_picker("Mother", key="mother_picker_edit", exclude_bird_id=bird_id)
                partner_id = bird_picker("Partner", key="partner_picker_edit", exclude_bird_id=bird_id)
                notes = st.text_area("Notes", value=bird["notes"] or "")

                if st.form_submit_button("Save Changes"):
                    owner = ring_number_owner(ring_number, exclude_bird_id=bird_id)
                    if not ring_number.strip():
                        st.error("Ring Number is required.")
                    elif owner:
                        st.error(f"This ring number is already used by Bird {owner}.")
                    else:
                        update_bird(bird_id, ring_number, cat_names[species_name], gender,
                                    father_id, mother_id, partner_id, cage_location, status,
                                    dob, notes)
                        st.success("Saved.")
                        st.session_state["edit_bird_mode"] = False
                        st.rerun()

    st.markdown("---")
    render_egg_records(bird_id)


def render_egg_records(bird_id):
    st.subheader("🥚 Egg / Breeding Records")
    seasons = list_seasons(bird_id)

    with st.expander("➕ Add Season"):
        with st.form(f"add_season_{bird_id}", clear_on_submit=True):
            label = st.text_input("Season label (e.g., 'Spring 2026')")
            c1, c2 = st.columns(2)
            start = c1.date_input("Start date", value=date.today())
            end = c2.date_input("End date", value=date.today())
            notes = st.text_area("Notes (fertility, hatch outcome, etc.)")
            if st.form_submit_button("Create Season"):
                if not label.strip():
                    st.error("Season label is required.")
                else:
                    add_season(bird_id, label, start, end, notes)
                    st.success("Season added.")
                    st.rerun()

    if not seasons:
        st.caption("No egg records yet.")
        return

    for s in seasons:
        with st.container(border=True):
            hcols = st.columns([4, 1])
            hcols[0].markdown(f"**{s['season_label']}**  \n{s['start_date']} → {s['end_date']}")
            if s["notes"]:
                hcols[0].caption(s["notes"])
            if hcols[1].button("Delete season", key=f"del_season_{s['season_id']}"):
                delete_season(s["season_id"])
                st.rerun()

            entries = list_entries(s["season_id"])
            total = sum(e["egg_count"] for e in entries)
            st.caption(f"Total eggs this season: **{total}**")
            if entries:
                st.table(
                    [{"Date": e["lay_date"], "Eggs": e["egg_count"], "Notes": e["notes"] or ""}
                     for e in entries]
                )
                for e in entries:
                    if st.button(f"Remove entry {e['lay_date']}", key=f"del_entry_{e['entry_id']}"):
                        delete_entry(e["entry_id"])
                        st.rerun()

            with st.form(f"add_entry_{s['season_id']}", clear_on_submit=True):
                ec1, ec2, ec3 = st.columns(3)
                lay_date = ec1.date_input("Lay date", value=date.today(), key=f"ld_{s['season_id']}")
                egg_count = ec2.number_input("Egg count", min_value=1, value=1, key=f"ec_{s['season_id']}")
                entry_notes = ec3.text_input("Notes", key=f"en_{s['season_id']}")
                if st.form_submit_button("Log Entry"):
                    add_entry(s["season_id"], lay_date, egg_count, entry_notes)
                    st.rerun()


# ----------------------------------------------------------------------
# UI: BREEDING OVERVIEW
# ----------------------------------------------------------------------


def render_breeding_overview():
    st.title("Breeding / Egg Records Overview")
    if st.button("← Back to Dashboard"):
        goto("dashboard")

    conn = get_connection()
    pairs = conn.execute(
        """SELECT b1.bird_id AS id1, b1.ring_number AS r1, b2.bird_id AS id2, b2.ring_number AS r2
           FROM birds b1 JOIN birds b2 ON b1.partner_id = b2.bird_id
           WHERE b1.bird_id < b2.bird_id"""
    ).fetchall()

    st.subheader(f"Breeding Pairs ({len(pairs)})")
    if not pairs:
        st.caption("No breeding pairs recorded yet.")
    for p in pairs:
        with st.container(border=True):
            c1, c2 = st.columns(2)
            if c1.button(f"{p['r1']} ({p['id1']})", key=f"pairbtn_{p['id1']}"):
                goto("bird", selected_bird=p["id1"], edit_bird_mode=False)
            if c2.button(f"{p['r2']} ({p['id2']})", key=f"pairbtn_{p['id2']}"):
                goto("bird", selected_bird=p["id2"], edit_bird_mode=False)

    st.subheader("Egg Production by Season")
    rows = stat_egg_by_season()
    if rows:
        st.bar_chart({r["label"]: r["total"] for r in rows})
        st.table([{"Season": r["label"], "Total Eggs": r["total"]} for r in rows])
    else:
        st.caption("No egg records logged yet.")


# ----------------------------------------------------------------------
# UI: STATISTICS
# ----------------------------------------------------------------------


def render_stats():
    st.title("Statistics & Reports")
    if st.button("← Back to Dashboard"):
        goto("dashboard")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Birds", stat_total_birds())
    active = len(list_birds(status="Active"))
    c2.metric("Active Birds", active)
    c3.metric("Breeding Pairs", stat_breeding_pairs())

    st.markdown("### Birds by Species")
    by_cat = stat_by_category()
    if by_cat:
        st.bar_chart({r["name"]: r["cnt"] for r in by_cat})
        st.table([{"Species": r["name"], "Count": r["cnt"]} for r in by_cat])

    st.markdown("### Birds by Location")
    by_loc = stat_by_location()
    if by_loc:
        st.bar_chart({r["loc"]: r["cnt"] for r in by_loc})

    st.markdown("### Egg Production by Season")
    rows = stat_egg_by_season()
    if rows:
        st.bar_chart({r["label"]: r["total"] for r in rows})
    else:
        st.caption("No egg data yet.")


# ----------------------------------------------------------------------
# UI: SETTINGS / BACKUP
# ----------------------------------------------------------------------


def render_settings():
    st.title("Settings")
    if st.button("← Back to Dashboard"):
        goto("dashboard")

    st.subheader("Backup / Export")
    st.caption("Download a full copy of your aviary database. Keep it somewhere safe.")
    try:
        with open(DB_PATH, "rb") as f:
            st.download_button("⬇️ Download Database Backup", f.read(),
                                file_name=f"aviary_backup_{date.today().isoformat()}.db")
    except FileNotFoundError:
        st.caption("No database file yet — add some data first.")

    st.subheader("About")
    st.write(
        "Aviary Manager stores all data locally in a SQLite database "
        f"(`{DB_PATH}`). Photos are stored inside the database as "
        "thumbnails, so a single backup file captures everything. This "
        "path is anchored to the app's own folder (or the AVIARY_DB_PATH "
        "environment variable, if set), so the same file is opened every "
        "time the portal is loaded and nothing is lost between sessions."
    )

    st.subheader("Portal Password")
    st.write(
        "This portal is protected by a single shared password so it's "
        "always your data on the other side of the login. Set your own "
        "password by adding `APP_PASSWORD = \"your-secret\"` to "
        "`.streamlit/secrets.toml` (recommended before sharing the link "
        "with anyone) — otherwise the built-in default password is used."
    )


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------


def main():
    inject_theme()
    require_login()
    init_db()
    init_state()
    render_sidebar()

    page = st.session_state["page"]
    if page == "dashboard":
        render_dashboard()
    elif page == "categories":
        render_categories()
    elif page == "category":
        render_category_detail()
    elif page == "add_bird":
        render_add_bird()
    elif page == "bird":
        render_bird_profile()
    elif page == "breeding":
        render_breeding_overview()
    elif page == "stats":
        render_stats()
    elif page == "settings":
        render_settings()
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
