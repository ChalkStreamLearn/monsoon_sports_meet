"""
ChalkStream Admin Panel (v2 — Firebase Firestore + Storage)
------------------------------------------------------------
Edits Cloud Firestore directly (scores / schedule / standings / gallery).
The public website (public/index.html + public/js/app.js) listens to the
same Firestore collections in real time, so any change made here appears
on the live site within a second or two — no data.json, no git push, no
redeploy needed for content changes.

Run locally (or on any server / Raspberry Pi / always-on machine):
    pip install -r requirements.txt
    ADMIN_PASSWORD=yourpass streamlit run admin.py
Then open the printed URL from your phone (same network, or via an
ngrok/cloudflared tunnel if you need it from outside).

Setup required before first run:
  1. Firebase Console → Project Settings → Service Accounts →
     "Generate new private key". Save the downloaded file as
     admin/serviceAccountKey.json (same folder as this script).
     NEVER commit this file — it's already in .gitignore.
  2. Gallery photos/videos are hosted on Cloudinary (free tier), not
     Firebase Storage. Sign up at cloudinary.com, then create an
     UNSIGNED upload preset (Settings → Upload → Add upload preset →
     Signing Mode: Unsigned). Set these before running:
       CLOUDINARY_CLOUD_NAME=cogtmcsv
       CLOUDINARY_UPLOAD_PRESET=chalkstream_media
     Optional, only needed if you want the "delete file" button in the
     Gallery tab to also remove the file from Cloudinary (otherwise it
     just removes the Firestore entry and the file stays on Cloudinary):
       CLOUDINARY_API_KEY=...
       CLOUDINARY_API_SECRET=...
     (Find these in Cloudinary → Settings → API Keys. Keep them secret —
     only set them on the server, never in public/js/.)
  3. Set ADMIN_PASSWORD before running (falls back to "chalkstream" —
     change this before real use).
  4. First time only: run `python ../scripts/seed_firestore.py` to load
     your existing data.json content into Firestore.
"""

import json
import mimetypes
import os
import time
import uuid
from pathlib import Path

import firebase_admin
import pandas as pd
import requests
import streamlit as st
from firebase_admin import credentials, firestore

ADMIN_DIR = Path(__file__).parent
SERVICE_ACCOUNT_PATH = ADMIN_DIR / "serviceAccountKey.json"

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", "chalkstream"))

CLOUDINARY_CLOUD_NAME = st.secrets.get("CLOUDINARY_CLOUD_NAME", os.environ.get("CLOUDINARY_CLOUD_NAME", "cogtmcsv"))
CLOUDINARY_UPLOAD_PRESET = st.secrets.get("CLOUDINARY_UPLOAD_PRESET", os.environ.get("CLOUDINARY_UPLOAD_PRESET", "chalkstream_media"))
CLOUDINARY_API_KEY = st.secrets.get("CLOUDINARY_API_KEY", os.environ.get("CLOUDINARY_API_KEY"))
CLOUDINARY_API_SECRET = st.secrets.get("CLOUDINARY_API_SECRET", os.environ.get("CLOUDINARY_API_SECRET"))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac"}
MAX_UPLOAD_MB = 60  # soft warning threshold — keep files light for slow wifi

STATUS_OPTIONS = ["live", "upcoming", "ended"]

st.set_page_config(page_title="ChalkStream Admin", page_icon="🏐", layout="centered")


# ---------- Firebase init ----------
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        if "firebase_service_account" in st.secrets:
            # Streamlit Community Cloud: paste the JSON key's contents into
            # Settings → Secrets as a [firebase_service_account] TOML table.
            cred = credentials.Certificate(dict(st.secrets["firebase_service_account"]))
        elif SERVICE_ACCOUNT_PATH.exists():
            cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
        else:
            st.error(
                "No Firebase credentials found. Locally: place serviceAccountKey.json "
                "in admin/. On Streamlit Cloud: add a [firebase_service_account] table "
                "in Settings → Secrets."
            )
            st.stop()
        firebase_admin.initialize_app(cred)

    return firestore.client()


db = init_firebase()


# ---------- auth ----------
def check_password():
    if st.session_state.get("authed"):
        return True
    st.title("🏐 ChalkStream Admin")
    pw = st.text_input("Password", type="password")
    if st.button("Login"):
        if pw == ADMIN_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password")
    return False


if not check_password():
    st.stop()


# ---------- Firestore helpers ----------
def load_collection(name):
    """Return list of dicts (each with '_id') ordered by the 'order' field."""
    docs = db.collection(name).stream()
    items = []
    for d in docs:
        item = d.to_dict()
        item["_id"] = d.id
        item.setdefault("order", 0)
        items.append(item)
    items.sort(key=lambda x: x.get("order", 0))
    return items


def save_collection_order(name, items):
    """Batch-write every item back to Firestore, re-numbering 'order' to
    match the current on-screen order. Strips the local-only '_id' key."""
    batch = db.batch()
    for idx, item in enumerate(items):
        doc_id = item["_id"]
        payload = {k: v for k, v in item.items() if k != "_id"}
        payload["order"] = idx
        batch.set(db.collection(name).document(doc_id), payload)
    batch.commit()


def add_doc(name, data, order_hint=None):
    if order_hint is None:
        existing = list(db.collection(name).stream())
        order_hint = len(existing)
    data = {**data, "order": order_hint}
    db.collection(name).add(data)


def delete_doc(name, doc_id):
    db.collection(name).document(doc_id).delete()


def save_upload_to_storage(uploaded_file, folder="gallery"):
    """Upload a file to Cloudinary (unsigned preset), return (public_url, public_id, kind)."""
    ext = Path(uploaded_file.name).suffix.lower()
    kind = (
        "video" if ext in VIDEO_EXTS
        else "photo" if ext in IMAGE_EXTS
        else "audio" if ext in AUDIO_EXTS
        else None
    )
    if kind is None:
        return None, None, None

    safe_name = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    content_type, _ = mimetypes.guess_type(uploaded_file.name)
    # Cloudinary has no separate "audio" resource type — audio files upload
    # and stream fine under "video", same as clips.
    resource_type = "video" if kind in ("video", "audio") else "image"

    resp = requests.post(
        f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload",
        data={
            "upload_preset": CLOUDINARY_UPLOAD_PRESET,
            "public_id": f"{folder}/{safe_name}",
        },
        files={
            "file": (uploaded_file.name, uploaded_file.getvalue(), content_type or "application/octet-stream"),
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["secure_url"], data["public_id"], kind


def delete_from_cloudinary(public_id, kind):
    """Delete a file from Cloudinary. Requires CLOUDINARY_API_KEY/SECRET (admin API); no-ops otherwise."""
    if not public_id or not (CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET):
        return False
    resource_type = "video" if kind in ("video", "audio") else "image"
    resp = requests.delete(
        f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/resources/{resource_type}/upload",
        auth=(CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET),
        params={"public_ids[]": public_id},
        timeout=30,
    )
    return resp.ok


def load_branding():
    """Single-document collection ('branding/main') holding the site logo
    and the animated hero banner (either a photo slideshow or a video)."""
    snap = db.collection("branding").document("main").get()
    data = snap.to_dict() if snap.exists else {}
    data.setdefault("logo_url", "")
    data.setdefault("logo_public_id", "")
    data.setdefault("banner_mode", "slideshow")
    data.setdefault("banner_images", [])
    data.setdefault("banner_video_url", "")
    data.setdefault("banner_video_public_id", "")
    return data


def save_branding(data):
    db.collection("branding").document("main").set(data, merge=True)


st.title("🏐 ChalkStream Admin")
st.caption("Edits Firestore directly — changes appear on the live site within seconds.")

tab_scores, tab_standings, tab_schedule, tab_fixtures, tab_gallery, tab_audio, tab_branding = st.tabs(
    ["Live Scores", "Standings", "Event Schedule", "Match Fixtures", "Gallery", "Audio", "Branding"]
)

# ---------- SCORES TAB ----------
with tab_scores:
    st.subheader("Score cards")
    scores = load_collection("scores")

    for i, m in enumerate(scores):
        with st.expander(
            f"{m.get('sport_emoji','')} {m.get('team_a','')} vs {m.get('team_b','')} "
            f"({m.get('status','')})",
            expanded=False,
        ):
            c1, c2 = st.columns(2)
            m["sport_emoji"] = c1.text_input("Emoji", m.get("sport_emoji", ""), key=f"emo{i}")
            m["status"] = c2.selectbox(
                "Status", STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(m.get("status", "upcoming")),
                key=f"stat{i}",
            )
            c1, c2 = st.columns(2)
            m["sport_mm"] = c1.text_input("Sport (Burmese)", m.get("sport_mm", ""), key=f"smm{i}")
            m["sport_zh"] = c2.text_input("Sport (Chinese)", m.get("sport_zh", ""), key=f"szh{i}")

            c1, c2, c3 = st.columns(3)
            m["team_a"] = c1.text_input("Team A", m.get("team_a", ""), key=f"ta{i}")
            m["score"] = c2.text_input(
                "Score (or time if upcoming)", m.get("score", ""), key=f"sc{i}"
            )
            m["team_b"] = c3.text_input("Team B", m.get("team_b", ""), key=f"tb{i}")

            if m["status"] != "live":
                c1, c2 = st.columns(2)
                m["status_mm"] = c1.text_input(
                    "Status label (Burmese)", m.get("status_mm", ""), key=f"stmm{i}"
                )
                m["status_zh"] = c2.text_input(
                    "Status label (Chinese)", m.get("status_zh", ""), key=f"stzh{i}"
                )

            c1, c2 = st.columns(2)
            m["note_mm"] = c1.text_input("Note (Burmese)", m.get("note_mm", ""), key=f"nmm{i}")
            m["note_zh"] = c2.text_input("Note (Chinese)", m.get("note_zh", ""), key=f"nzh{i}")

            if st.button("🗑 Delete this match", key=f"del{i}"):
                delete_doc("scores", m["_id"])
                st.rerun()

    st.divider()
    if st.button("➕ Add new match"):
        add_doc("scores", {
            "sport_emoji": "🏐", "sport_mm": "", "sport_zh": "",
            "status": "upcoming", "status_mm": "ကျန်", "status_zh": "未开始",
            "team_a": "", "team_b": "", "score": "",
            "note_mm": "", "note_zh": ""
        })
        st.rerun()

    if scores and st.button("💾 Save score changes", type="primary", key="save_scores"):
        save_collection_order("scores", scores)
        st.success("Saved — live site will update within a couple seconds.")

# ---------- STANDINGS TAB ----------
with tab_standings:
    st.subheader("Points table & semi-final race")
    st.caption(
        "Points are calculated automatically (Win = 3, Draw = 1, Loss = 0). "
        "'Total group rounds' is how many group-stage matches each team plays in "
        "total — it's used to work out whether a team can still mathematically "
        "catch the last qualifying spot."
    )
    standings = load_collection("standings")

    for gi, group in enumerate(standings):
        with st.expander(
            f"{group.get('sport_emoji','')} {group.get('sport_mm','')} — "
            f"{len(group.get('teams', []))} teams",
            expanded=False,
        ):
            c1, c2 = st.columns(2)
            group["sport_emoji"] = c1.text_input(
                "Emoji", group.get("sport_emoji", ""), key=f"gemo{gi}"
            )
            group["sport_key"] = c2.text_input(
                "Internal key (no spaces)", group.get("sport_key", ""), key=f"gkey{gi}"
            )
            c1, c2 = st.columns(2)
            group["sport_mm"] = c1.text_input(
                "Sport name (Burmese)", group.get("sport_mm", ""), key=f"gsmm{gi}"
            )
            group["sport_zh"] = c2.text_input(
                "Sport name (Chinese)", group.get("sport_zh", ""), key=f"gszh{gi}"
            )

            c1, c2 = st.columns(2)
            group["qualify_count"] = c1.number_input(
                "Teams that advance to semi-finals",
                min_value=1, max_value=20,
                value=int(group.get("qualify_count", 2)),
                key=f"gqc{gi}",
            )
            group["total_rounds"] = c2.number_input(
                "Total group-stage rounds per team",
                min_value=1, max_value=20,
                value=int(group.get("total_rounds", 5)),
                key=f"gtr{gi}",
            )

            c1, c2 = st.columns(2)
            group["note_mm"] = c1.text_input(
                "Note (Burmese)", group.get("note_mm", ""), key=f"gnmm{gi}"
            )
            group["note_zh"] = c2.text_input(
                "Note (Chinese)", group.get("note_zh", ""), key=f"gnzh{gi}"
            )

            st.markdown("**Teams**")
            teams = group.setdefault("teams", [])
            for ti, t in enumerate(teams):
                c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(
                    [1.8, 0.9, 0.9, 0.9, 0.9, 0.5, 0.5, 0.5]
                )
                t["team"] = c1.text_input("Team", t.get("team", ""), key=f"t{gi}_{ti}_name")
                t["played"] = c2.number_input(
                    "P", min_value=0, value=int(t.get("played", 0)), key=f"t{gi}_{ti}_p"
                )
                t["won"] = c3.number_input(
                    "W", min_value=0, value=int(t.get("won", 0)), key=f"t{gi}_{ti}_w"
                )
                t["draw"] = c4.number_input(
                    "D", min_value=0, value=int(t.get("draw", 0)), key=f"t{gi}_{ti}_d"
                )
                t["lost"] = c5.number_input(
                    "L", min_value=0, value=int(t.get("lost", 0)), key=f"t{gi}_{ti}_l"
                )
                if c6.button("⬆️", key=f"t{gi}_{ti}_up", disabled=(ti == 0)):
                    teams[ti - 1], teams[ti] = teams[ti], teams[ti - 1]
                    save_collection_order("standings", standings)
                    st.rerun()
                if c7.button("⬇️", key=f"t{gi}_{ti}_down", disabled=(ti == len(teams) - 1)):
                    teams[ti + 1], teams[ti] = teams[ti], teams[ti + 1]
                    save_collection_order("standings", standings)
                    st.rerun()
                if c8.button("🗑", key=f"t{gi}_{ti}_del"):
                    teams.pop(ti)
                    save_collection_order("standings", standings)
                    st.rerun()

            if st.button("➕ Add team", key=f"addteam{gi}"):
                teams.append({"team": "", "played": 0, "won": 0, "draw": 0, "lost": 0})
                save_collection_order("standings", standings)
                st.rerun()

            if st.button("🗑 Delete this sport's standings", key=f"delgroup{gi}"):
                delete_doc("standings", group["_id"])
                st.rerun()

    st.divider()
    if st.button("➕ Add new sport standings"):
        add_doc("standings", {
            "sport_key": "", "sport_emoji": "🏐", "sport_mm": "", "sport_zh": "",
            "qualify_count": 2, "total_rounds": 5,
            "note_mm": "", "note_zh": "",
            "teams": []
        })
        st.rerun()

    if standings and st.button("💾 Save standings changes", type="primary", key="save_standings"):
        save_collection_order("standings", standings)
        st.success("Saved — live site will update within a couple seconds.")

# ---------- SCHEDULE TAB ----------
with tab_schedule:
    st.subheader("Schedule rows")
    schedule = load_collection("schedule")

    for i, ev in enumerate(schedule):
        with st.expander(f"{ev.get('date','')} — {ev.get('title_mm','')}", expanded=False):
            c1, c2, c3 = st.columns(3)
            if c1.button("⬆️ Move up", key=f"up{i}", disabled=(i == 0)):
                schedule[i - 1], schedule[i] = schedule[i], schedule[i - 1]
                save_collection_order("schedule", schedule)
                st.rerun()
            if c2.button("⬇️ Move down", key=f"down{i}", disabled=(i == len(schedule) - 1)):
                schedule[i + 1], schedule[i] = schedule[i], schedule[i + 1]
                save_collection_order("schedule", schedule)
                st.rerun()
            if c3.button("🗑 Delete this row", key=f"delev{i}"):
                delete_doc("schedule", ev["_id"])
                st.rerun()

            c1, c2 = st.columns(2)
            ev["date"] = c1.text_input("Date label", ev.get("date", ""), key=f"d{i}")
            ev["is_emoji_tag"] = c2.checkbox(
                "Tag is emoji (vs text)", ev.get("is_emoji_tag", False), key=f"emj{i}"
            )

            c1, c2 = st.columns(2)
            ev["title_mm"] = c1.text_input("Title (Burmese)", ev.get("title_mm", ""), key=f"tmm{i}")
            ev["title_zh"] = c2.text_input("Title (Chinese)", ev.get("title_zh", ""), key=f"tzh{i}")

            c1, c2 = st.columns(2)
            ev["sub_mm"] = c1.text_input("Subtitle (Burmese)", ev.get("sub_mm", ""), key=f"submm{i}")
            ev["sub_zh"] = c2.text_input("Subtitle (Chinese)", ev.get("sub_zh", ""), key=f"subzh{i}")

            c1, c2 = st.columns(2)
            ev["tag_mm"] = c1.text_input("Tag (Burmese/emoji)", ev.get("tag_mm", ""), key=f"tagmm{i}")
            ev["tag_zh"] = c2.text_input("Tag (Chinese/emoji)", ev.get("tag_zh", ""), key=f"tagzh{i}")

            ev["postponed"] = st.checkbox(
                "🌧️ Postponed / rain delay (shows a red badge on the site)",
                ev.get("postponed", False), key=f"postponed_ev{i}"
            )

    st.divider()
    if st.button("➕ Add new schedule row"):
        add_doc("schedule", {
            "date": "", "title_mm": "", "title_zh": "",
            "sub_mm": "", "sub_zh": "", "tag_mm": "", "tag_zh": "",
            "is_emoji_tag": False, "postponed": False
        })
        st.rerun()

    if schedule and st.button("💾 Save schedule changes", type="primary", key="save_schedule"):
        save_collection_order("schedule", schedule)
        st.success("Saved — live site will update within a couple seconds.")

# ---------- MATCH FIXTURES TAB ----------
with tab_fixtures:
    st.subheader("Match fixtures (ပွဲစဉ်ဇယား)")
    st.caption(
        "Which teams play which sport, on what date and time. Separate from "
        "the Event Schedule tab (which is for ceremony-level events like the "
        "lottery draw, opening, semis, finals)."
    )
    SPORT_OPTIONS = {
        "football": ("⚽", "ဘောလုံး", "足球"),
        "volleyball": ("🏐", "ဘောလီဘော", "排球"),
        "basketball": ("🏀", "ဘတ်စကက်ဘော", "篮球"),
    }

    # Preset team colors, keyed by township. Used both here (manual dropdown
    # picker) and in the bulk-import section below (auto-match by name) — so
    # the same township always gets the same color everywhere.
    TEAM_COLORS = {
        "မုံးကိုးမြို့နယ်(A)": "#1E88E5",
        "မုံးကိုးမြို့နယ်(B)": "#64B5F6",
        "မုံးစီးမြို့နယ်": "#43A047",
        "နမ့်ကျွမ်းမြို့နယ်": "#FB8C00",
        "မုံးပေါ်မြို့နယ်(A)": "#8E24AA",
        "မုံးပေါ်မြို့နယ်(B)": "#CE93D8",
        "မုံးပေါ်(ပန်ဆိုင်း)": "#87CEEB",
        "မုံးဟွမ်မြို့နယ်": "#E53935",
        "မုံးကိုး(ဖောင်းဆိုင်)": "#00897B",
        "မုံးကိုး(ရေပူ)": "#6D4C41",
        "ခရိုင်လှုပ်ရှားတပ်ဖွဲ့": "#455A64",
        "မုံးကိုးယွိချိုက်(A)": "#FDD835",
        "မုံးကိုးယွိချိုက်(B)": "#FFF176",
        "မုံးကိုးမြို့နယ်": "#1E88E5",
        "မုံးကိုးခရိုင်ရုံး": "#3949AB",
        "မုံးပေါ်မြို့နယ်": "#8E24AA",
    }
    CUSTOM_COLOR_LABEL = "🎨 Custom (pick manually)"
    COLOR_PRESET_LABELS = list(TEAM_COLORS.keys()) + [CUSTOM_COLOR_LABEL]

    def label_for_color(hex_color):
        """Reverse-lookup: given a stored hex, find which preset it matches
        (so the dropdown shows the right preset already selected)."""
        for name, hexval in TEAM_COLORS.items():
            if hexval.lower() == (hex_color or "").lower():
                return name
        return CUSTOM_COLOR_LABEL

    def resolve_team_color(name, fallback):
        """Auto-match a team name cell (bulk import) against TEAM_COLORS —
        exact match first, then 'does the cell contain this township name'."""
        name = (name or "").strip()
        if not name:
            return fallback
        if name in TEAM_COLORS:
            return TEAM_COLORS[name]
        for key, color in TEAM_COLORS.items():
            if key in name:
                return color
        return fallback

    matches = load_collection("matches")

    sport_filter = st.radio(
        "Filter by sport",
        options=["All"] + list(SPORT_OPTIONS.keys()),
        format_func=lambda k: "All" if k == "All" else f"{SPORT_OPTIONS[k][0]} {SPORT_OPTIONS[k][1]}",
        horizontal=True,
        key="fixture_sport_filter",
    )
    visible = [
        (i, m) for i, m in enumerate(matches)
        if sport_filter == "All" or m.get("sport_key") == sport_filter
    ]

    for i, m in visible:
        label = f"{SPORT_OPTIONS.get(m.get('sport_key'), ('❔',))[0]} {m.get('date','')} {m.get('time','')} — {m.get('team_a','?')} vs {m.get('team_b','?')}"
        with st.expander(label, expanded=False):
            c1, c2, c3 = st.columns(3)
            if c1.button("⬆️ Move up", key=f"mup{i}", disabled=(i == 0)):
                matches[i - 1], matches[i] = matches[i], matches[i - 1]
                save_collection_order("matches", matches)
                st.rerun()
            if c2.button("⬇️ Move down", key=f"mdown{i}", disabled=(i == len(matches) - 1)):
                matches[i + 1], matches[i] = matches[i], matches[i + 1]
                save_collection_order("matches", matches)
                st.rerun()
            if c3.button("🗑 Delete this match", key=f"mdel{i}"):
                delete_doc("matches", m["_id"])
                st.rerun()

            sport_keys = list(SPORT_OPTIONS.keys())
            current_sport = m.get("sport_key", "football")
            new_sport = st.selectbox(
                "Sport", sport_keys,
                index=sport_keys.index(current_sport) if current_sport in sport_keys else 0,
                format_func=lambda k: f"{SPORT_OPTIONS[k][0]} {SPORT_OPTIONS[k][1]} / {SPORT_OPTIONS[k][2]}",
                key=f"msport{i}",
            )
            m["sport_key"] = new_sport
            m["sport_emoji"], m["sport_mm"], m["sport_zh"] = SPORT_OPTIONS[new_sport]

            c1, c2 = st.columns(2)
            m["date"] = c1.text_input("Date (e.g. AUG 16)", m.get("date", ""), key=f"mdate{i}")
            m["time"] = c2.text_input("Time (e.g. 3:00 PM)", m.get("time", ""), key=f"mtime{i}")

            c1, c2, c3, c4 = st.columns([2.5, 1.3, 2.5, 1.3])
            m["team_a"] = c1.text_input("Team A", m.get("team_a", ""), key=f"mta{i}")
            cur_a = m.get("team_a_color") or "#7fb3c0"
            label_a = c2.selectbox(
                "Color A", COLOR_PRESET_LABELS,
                index=COLOR_PRESET_LABELS.index(label_for_color(cur_a)),
                key=f"mtacsel{i}",
            )
            if label_a == CUSTOM_COLOR_LABEL:
                m["team_a_color"] = c2.color_picker("Custom A", cur_a, key=f"mtac{i}")
            else:
                m["team_a_color"] = TEAM_COLORS[label_a]

            m["team_b"] = c3.text_input("Team B", m.get("team_b", ""), key=f"mtb{i}")
            cur_b = m.get("team_b_color") or "#c45a48"
            label_b = c4.selectbox(
                "Color B", COLOR_PRESET_LABELS,
                index=COLOR_PRESET_LABELS.index(label_for_color(cur_b)),
                key=f"mtbcsel{i}",
            )
            if label_b == CUSTOM_COLOR_LABEL:
                m["team_b_color"] = c4.color_picker("Custom B", cur_b, key=f"mtbc{i}")
            else:
                m["team_b_color"] = TEAM_COLORS[label_b]

            m["note_mm"] = st.text_input("Note (Burmese, optional)", m.get("note_mm", ""), key=f"mnotemm{i}")
            m["note_zh"] = st.text_input("Note (Chinese, optional)", m.get("note_zh", ""), key=f"mnotezh{i}")

            m["postponed"] = st.checkbox(
                "🌧️ Postponed / rain delay (shows a red badge on the site)",
                m.get("postponed", False), key=f"postponed_m{i}"
            )

    st.divider()
    add_col1, add_col2 = st.columns(2)
    add_sport = add_col1.selectbox(
        "Sport for new match", list(SPORT_OPTIONS.keys()),
        format_func=lambda k: f"{SPORT_OPTIONS[k][0]} {SPORT_OPTIONS[k][1]}",
        key="new_match_sport",
    )
    if add_col2.button("➕ Add new match", key="add_new_fixture"):
        emoji, mm, zh = SPORT_OPTIONS[add_sport]
        add_doc("matches", {
            "sport_key": add_sport, "sport_emoji": emoji, "sport_mm": mm, "sport_zh": zh,
            "date": "", "time": "", "team_a": "", "team_b": "",
            "team_a_color": "#7fb3c0", "team_b_color": "#c45a48",
            "note_mm": "", "note_zh": "", "postponed": False,
        })
        st.rerun()

    if matches and st.button("💾 Save fixture changes", type="primary", key="save_matches"):
        save_collection_order("matches", matches)
        st.success("Saved — live site will update within a couple seconds.")

    # (TEAM_COLORS and resolve_team_color are already defined above, near the
    # manual color-preset picker — reused here for bulk import auto-color.)

    # Accepts either the English column names the importer originally used,
    # or the Burmese headers from the Numbers fixtures template — so Chaw Su
    # can export straight from Numbers without renaming columns first.
    COLUMN_ALIASES = {
        "date": ["date", "ရက်စွဲ"],
        "time": ["time", "အချိန်"],
        "team_1": ["team_1", "team1", "အသင်း a", "အသင်း-a"],
        "team_2": ["team_2", "team2", "အသင်း b", "အသင်း-b"],
        "note_mm": ["note_mm", "မှတ်ချက်", "ပွဲအမျိုးအစား"],
        "note_zh": ["note_zh"],
        "sport": ["sport"],
    }

    def get_col(row, cols_lower, field):
        for alias in COLUMN_ALIASES[field]:
            if alias in cols_lower:
                return row[cols_lower[alias]]
        return None

    st.divider()
    with st.expander("📥 Bulk import from Excel", expanded=bool(st.session_state.get("fixture_import_msg"))):
        st.caption(
            "Upload a .xlsx file with columns: date, time, team_1, team_2, "
            "note_mm (optional), note_zh (optional) — Burmese headers from the "
            "Numbers template (ရက်စွဲ / အချိန် / အသင်း A / အသင်း B) also work. "
            "Team colors are filled in automatically from the township name. "
            "For two matches on the same day, add two rows with the same date "
            "but a different time (e.g. 9:00 AM and 4:00 PM)."
        )
        import_sport = st.selectbox(
            "Sport for this file (used for every row, unless the file has its "
            "own 'sport' column)",
            list(SPORT_OPTIONS.keys()),
            format_func=lambda k: f"{SPORT_OPTIONS[k][0]} {SPORT_OPTIONS[k][1]}",
            key="bulk_import_sport",
        )

        # Show the result of the last import — persisted across the rerun that
        # follows a successful import, so the message doesn't just flash and
        # disappear (which was causing people to re-click and duplicate rows).
        if st.session_state.get("fixture_import_msg"):
            st.success(st.session_state.pop("fixture_import_msg"))

        # Bump this key after every successful import so the file_uploader
        # resets to empty — prevents an accidental second click of "Import
        # from Excel" from re-importing the same file again.
        uploader_key = f"fixtures_xlsx_{st.session_state.get('fixture_uploader_gen', 0)}"
        xlsx_file = st.file_uploader(
            "Fixtures spreadsheet (.xlsx)", type=["xlsx"], key=uploader_key
        )
        if xlsx_file and st.button("Import from Excel", key="import_xlsx_matches"):
            try:
                df = pd.read_excel(xlsx_file)
            except Exception as e:
                st.error(f"Couldn't read that file: {e}")
                df = None
            if df is not None:
                cols_lower = {str(c).strip().lower(): c for c in df.columns}

                def clean(val):
                    return "" if val is None or pd.isna(val) else str(val).strip()

                imported, skipped = 0, 0
                for _, row in df.iterrows():
                    sport_raw = get_col(row, cols_lower, "sport")
                    sport = clean(sport_raw).lower() if sport_raw is not None else ""
                    if sport not in SPORT_OPTIONS:
                        sport = import_sport  # no per-row sport column — use the picker above
                    emoji, mm, zh = SPORT_OPTIONS[sport]

                    team_a_val = clean(get_col(row, cols_lower, "team_1"))
                    time_val = clean(get_col(row, cols_lower, "time"))
                    # Rest Day rows (team_1 starts with "Rest Day", or time
                    # is a placeholder "-") aren't real matches — skip them
                    # so they don't show up as a match card.
                    if team_a_val.startswith("Rest Day") or time_val == "-" or not team_a_val:
                        skipped += 1
                        continue

                    team_b_val = clean(get_col(row, cols_lower, "team_2"))
                    add_doc("matches", {
                        "sport_key": sport, "sport_emoji": emoji, "sport_mm": mm, "sport_zh": zh,
                        "date": clean(get_col(row, cols_lower, "date")),
                        "time": time_val,
                        "team_a": team_a_val,
                        "team_b": team_b_val,
                        "team_a_color": resolve_team_color(team_a_val, "#7fb3c0"),
                        "team_b_color": resolve_team_color(team_b_val, "#c45a48"),
                        "note_mm": clean(get_col(row, cols_lower, "note_mm")),
                        "note_zh": clean(get_col(row, cols_lower, "note_zh")),
                        "postponed": False,
                    })
                    imported += 1
                msg = f"Imported {imported} match(es)."
                if skipped:
                    msg += f" Skipped {skipped} row(s) (Rest Day or missing team name)."
                st.session_state["fixture_import_msg"] = msg
                # Force the uploader to reset to empty on the next run.
                st.session_state["fixture_uploader_gen"] = st.session_state.get("fixture_uploader_gen", 0) + 1
                st.rerun()

# ---------- GALLERY TAB ----------
with tab_gallery:
    st.subheader("Photos & videos")
    st.caption(
        f"Files upload straight to Cloudinary and appear on the site "
        f"immediately — no git push needed. Keep clips "
        f"short and compressed (under ~{MAX_UPLOAD_MB}MB)."
    )

    uploads = st.file_uploader(
        "Upload photo(s) or video(s)",
        type=sorted(e.strip(".") for e in IMAGE_EXTS | VIDEO_EXTS),
        accept_multiple_files=True,
        key="gallery_uploader",
    )
    if uploads:
        if st.button(f"➕ Add {len(uploads)} file(s) to gallery"):
            added = 0
            for f in uploads:
                size_mb = f.size / (1024 * 1024)
                if size_mb > MAX_UPLOAD_MB:
                    st.warning(f"Skipped {f.name} — {size_mb:.1f}MB is over the {MAX_UPLOAD_MB}MB guideline.")
                    continue
                public_url, public_id, kind = save_upload_to_storage(f)
                if kind is None:
                    st.warning(f"Skipped {f.name} — unsupported file type.")
                    continue
                add_doc("gallery", {
                    "type": kind,
                    "src": public_url,
                    "public_id": public_id,
                    "tag_emoji": "▶" if kind == "video" else "📷",
                    "tag_mm": "ဗီဒီယို" if kind == "video" else "ဓာတ်ပုံ",
                    "tag_zh": "视频" if kind == "video" else "照片",
                    "cap_mm": "",
                    "cap_zh": "",
                    "uploadedAt": firestore.SERVER_TIMESTAMP,
                }, order_hint=0)
                added += 1
            st.success(f"Added {added} file(s). Scroll down to edit captions.")
            st.rerun()

    st.divider()
    gallery = load_collection("gallery")
    st.markdown(f"**Gallery items ({len(gallery)})**")

    for gi, item in enumerate(gallery):
        with st.expander(
            f"{item.get('tag_emoji','')} {item.get('src','(missing file)')}",
            expanded=False,
        ):
            if item.get("type") == "video":
                st.video(item.get("src", ""))
            else:
                st.image(item.get("src", ""))

            c1, c2 = st.columns(2)
            item["cap_mm"] = c1.text_input("Caption (Burmese)", item.get("cap_mm", ""), key=f"gcmm{gi}")
            item["cap_zh"] = c2.text_input("Caption (Chinese)", item.get("cap_zh", ""), key=f"gczh{gi}")

            c1, c2 = st.columns(2)
            item["tag_mm"] = c1.text_input("Tag label (Burmese)", item.get("tag_mm", ""), key=f"gtmm{gi}")
            item["tag_zh"] = c2.text_input("Tag label (Chinese)", item.get("tag_zh", ""), key=f"gtzh{gi}")

            if st.button("🗑 Delete this item (and its file)", key=f"gdel{gi}"):
                public_id = item.get("public_id")
                try:
                    delete_from_cloudinary(public_id, item.get("type"))
                except Exception:
                    pass
                delete_doc("gallery", item["_id"])
                st.rerun()

    if gallery and st.button("💾 Save gallery captions"):
        for item in gallery:
            doc_id = item["_id"]
            payload = {k: v for k, v in item.items() if k != "_id"}
            db.collection("gallery").document(doc_id).set(payload, merge=True)
        st.success("Saved.")

# ---------- AUDIO TAB ----------
with tab_audio:
    st.subheader("Live audio commentary")
    st.caption(
        f"Upload MP3/M4A/WAV clips — they stream straight to Cloudinary and "
        f"appear as playable clips on the site's Audio section immediately. "
        f"Keep files under ~{MAX_UPLOAD_MB}MB."
    )

    audio_uploads = st.file_uploader(
        "Upload audio clip(s)",
        type=sorted(e.strip(".") for e in AUDIO_EXTS),
        accept_multiple_files=True,
        key="audio_uploader",
    )
    if audio_uploads:
        if st.button(f"➕ Add {len(audio_uploads)} clip(s)"):
            added = 0
            for f in audio_uploads:
                size_mb = f.size / (1024 * 1024)
                if size_mb > MAX_UPLOAD_MB:
                    st.warning(f"Skipped {f.name} — {size_mb:.1f}MB is over the {MAX_UPLOAD_MB}MB guideline.")
                    continue
                public_url, public_id, kind = save_upload_to_storage(f, folder="audio")
                if kind != "audio":
                    st.warning(f"Skipped {f.name} — unsupported file type.")
                    continue
                add_doc("audio", {
                    "src": public_url,
                    "public_id": public_id,
                    "who_mm": "",
                    "who_zh": "",
                    "what_mm": "",
                    "what_zh": "",
                    "uploadedAt": firestore.SERVER_TIMESTAMP,
                }, order_hint=0)
                added += 1
            st.success(f"Added {added} clip(s). Scroll down to fill in the labels.")
            st.rerun()

    st.divider()
    audio_clips = load_collection("audio")
    st.markdown(f"**Audio clips ({len(audio_clips)})**")

    for ai, item in enumerate(audio_clips):
        with st.expander(
            f"🎙 {item.get('what_mm') or item.get('src', '(missing file)')}",
            expanded=False,
        ):
            st.audio(item.get("src", ""))

            c1, c2 = st.columns(2)
            item["who_mm"] = c1.text_input(
                "Who / label line (Burmese)", item.get("who_mm", ""), key=f"awmm{ai}"
            )
            item["who_zh"] = c2.text_input(
                "Who / label line (Chinese)", item.get("who_zh", ""), key=f"awzh{ai}"
            )

            c1, c2 = st.columns(2)
            item["what_mm"] = c1.text_input(
                "Clip title (Burmese)", item.get("what_mm", ""), key=f"atmm{ai}"
            )
            item["what_zh"] = c2.text_input(
                "Clip title (Chinese)", item.get("what_zh", ""), key=f"atzh{ai}"
            )

            if st.button("🗑 Delete this clip (and its file)", key=f"adel{ai}"):
                public_id = item.get("public_id")
                try:
                    delete_from_cloudinary(public_id, "audio")
                except Exception:
                    pass
                delete_doc("audio", item["_id"])
                st.rerun()

    if audio_clips and st.button("💾 Save audio labels"):
        for item in audio_clips:
            doc_id = item["_id"]
            payload = {k: v for k, v in item.items() if k != "_id"}
            db.collection("audio").document(doc_id).set(payload, merge=True)
        st.success("Saved.")

# ---------- BRANDING TAB ----------
with tab_branding:
    st.subheader("Logo & animated banner")
    st.caption(
        "The logo shows top-left in the site navigation on every page (desktop "
        "and mobile). The banner plays as the background of the hero section, "
        "behind the title — pick either a rotating photo slideshow or a single "
        "looping video clip."
    )
    branding = load_branding()

    # --- Logo ---
    st.markdown("**Event logo**")
    if branding.get("logo_url"):
        st.image(branding["logo_url"], width=160)
    logo_file = st.file_uploader(
        "Upload logo (PNG/JPG — a transparent background works best)",
        type=["png", "jpg", "jpeg", "webp"],
        key="logo_uploader",
    )
    c1, c2 = st.columns(2)
    if logo_file and c1.button("⬆️ Set as logo"):
        old_public_id = branding.get("logo_public_id")
        public_url, public_id, kind = save_upload_to_storage(logo_file, folder="branding")
        if kind is None:
            st.warning("Unsupported file type.")
        else:
            if old_public_id:
                try:
                    delete_from_cloudinary(old_public_id, "photo")
                except Exception:
                    pass
            branding["logo_url"] = public_url
            branding["logo_public_id"] = public_id
            save_branding(branding)
            st.success("Logo updated — check the live site in a few seconds.")
            st.rerun()
    if branding.get("logo_url") and c2.button("🗑 Remove logo"):
        try:
            delete_from_cloudinary(branding.get("logo_public_id"), "photo")
        except Exception:
            pass
        branding["logo_url"] = ""
        branding["logo_public_id"] = ""
        save_branding(branding)
        st.rerun()

    st.divider()

    # --- Banner ---
    st.markdown("**Animated hero banner**")
    mode_labels = {"slideshow": "Slideshow (multiple photos)", "video": "Video (single clip)"}
    current_mode = branding.get("banner_mode", "slideshow")
    chosen_label = st.radio(
        "Banner type",
        options=list(mode_labels.values()),
        index=list(mode_labels.keys()).index(current_mode) if current_mode in mode_labels else 0,
        key="banner_mode_radio",
    )
    new_mode = next(k for k, v in mode_labels.items() if v == chosen_label)
    if new_mode != branding.get("banner_mode"):
        branding["banner_mode"] = new_mode
        save_branding(branding)
        st.rerun()

    if branding["banner_mode"] == "slideshow":
        st.caption("Photos rotate automatically every few seconds on the live site.")
        images = branding.setdefault("banner_images", [])
        for bi, img in enumerate(images):
            c1, c2, c3, c4 = st.columns([3, 0.6, 0.6, 0.6])
            c1.image(img.get("url", ""), width=140)
            if c2.button("⬆️", key=f"banner_up{bi}", disabled=(bi == 0)):
                images[bi - 1], images[bi] = images[bi], images[bi - 1]
                save_branding(branding)
                st.rerun()
            if c3.button("⬇️", key=f"banner_down{bi}", disabled=(bi == len(images) - 1)):
                images[bi + 1], images[bi] = images[bi], images[bi + 1]
                save_branding(branding)
                st.rerun()
            if c4.button("🗑", key=f"banner_del{bi}"):
                removed = images.pop(bi)
                try:
                    delete_from_cloudinary(removed.get("public_id"), "photo")
                except Exception:
                    pass
                save_branding(branding)
                st.rerun()

        new_banner_files = st.file_uploader(
            "Add photo(s) to slideshow",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="banner_slideshow_uploader",
        )
        if new_banner_files and st.button(f"➕ Add {len(new_banner_files)} photo(s) to banner"):
            for f in new_banner_files:
                public_url, public_id, kind = save_upload_to_storage(f, folder="branding")
                if kind:
                    images.append({"url": public_url, "public_id": public_id})
            save_branding(branding)
            st.success("Banner photos updated.")
            st.rerun()

    else:  # video mode
        st.caption("A single looping video clip plays muted behind the hero title.")
        if branding.get("banner_video_url"):
            st.video(branding["banner_video_url"])
        video_file = st.file_uploader(
            "Upload banner video (MP4/WebM — keep it short & compressed)",
            type=["mp4", "webm", "mov", "m4v"],
            key="banner_video_uploader",
        )
        c1, c2 = st.columns(2)
        if video_file and c1.button("⬆️ Set as banner video"):
            old_public_id = branding.get("banner_video_public_id")
            public_url, public_id, kind = save_upload_to_storage(video_file, folder="branding")
            if kind is None:
                st.warning("Unsupported file type.")
            else:
                if old_public_id:
                    try:
                        delete_from_cloudinary(old_public_id, "video")
                    except Exception:
                        pass
                branding["banner_video_url"] = public_url
                branding["banner_video_public_id"] = public_id
                save_branding(branding)
                st.success("Banner video updated.")
                st.rerun()
        if branding.get("banner_video_url") and c2.button("🗑 Remove banner video"):
            try:
                delete_from_cloudinary(branding.get("banner_video_public_id"), "video")
            except Exception:
                pass
            branding["banner_video_url"] = ""
            branding["banner_video_public_id"] = ""
            save_branding(branding)
            st.rerun()

with st.expander("Raw data (advanced, read-only preview)"):
    st.json({
        "scores": load_collection("scores"),
        "standings": load_collection("standings"),
        "schedule": load_collection("schedule"),
        "matches": load_collection("matches"),
        "gallery": load_collection("gallery"),
        "audio": load_collection("audio"),
        "branding": load_branding(),
    })
