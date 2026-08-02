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


def swap_order(name, item_a, item_b):
    """Swap the 'order' field of two documents and commit immediately —
    used for the up/down reorder buttons so moves take effect at once,
    without needing the separate 'Save changes' button."""
    batch = db.batch()
    order_a = item_a.get("order", 0)
    order_b = item_b.get("order", 0)
    batch.update(db.collection(name).document(item_a["_id"]), {"order": order_b})
    batch.update(db.collection(name).document(item_b["_id"]), {"order": order_a})
    batch.commit()


def save_upload_to_storage(uploaded_file):
    """Upload a file to Cloudinary (unsigned preset), return (public_url, public_id, kind)."""
    ext = Path(uploaded_file.name).suffix.lower()
    kind = "video" if ext in VIDEO_EXTS else "photo" if ext in IMAGE_EXTS else None
    if kind is None:
        return None, None, None

    safe_name = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    content_type, _ = mimetypes.guess_type(uploaded_file.name)
    resource_type = "video" if kind == "video" else "image"

    resp = requests.post(
        f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload",
        data={
            "upload_preset": CLOUDINARY_UPLOAD_PRESET,
            "public_id": f"gallery/{safe_name}",
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
    resource_type = "video" if kind == "video" else "image"
    resp = requests.delete(
        f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/resources/{resource_type}/upload",
        auth=(CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET),
        params={"public_ids[]": public_id},
        timeout=30,
    )
    return resp.ok


st.title("🏐 ChalkStream Admin")
st.caption("Edits Firestore directly — changes appear on the live site within seconds.")

tab_scores, tab_standings, tab_schedule, tab_gallery = st.tabs(
    ["Live Scores", "Standings", "Schedule", "Gallery"]
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
                c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1, 1, 1, 0.6])
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
                if c6.button("🗑", key=f"t{gi}_{ti}_del"):
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
        row = st.columns([0.07, 0.07, 0.86])
        with row[0]:
            if st.button("▲", key=f"up{i}", disabled=(i == 0), help="Move up"):
                swap_order("schedule", schedule[i], schedule[i - 1])
                st.rerun()
        with row[1]:
            if st.button("▼", key=f"down{i}", disabled=(i == len(schedule) - 1), help="Move down"):
                swap_order("schedule", schedule[i], schedule[i + 1])
                st.rerun()
        with row[2]:
            with st.expander(f"{ev.get('date','')} — {ev.get('title_mm','')}", expanded=False):
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

                if st.button("🗑 Delete this row", key=f"delev{i}"):
                    delete_doc("schedule", ev["_id"])
                    st.rerun()

    st.divider()
    if st.button("➕ Add new schedule row"):
        add_doc("schedule", {
            "date": "", "title_mm": "", "title_zh": "",
            "sub_mm": "", "sub_zh": "", "tag_mm": "", "tag_zh": "",
            "is_emoji_tag": False
        })
        st.rerun()

    if schedule and st.button("💾 Save schedule changes", type="primary", key="save_schedule"):
        save_collection_order("schedule", schedule)
        st.success("Saved — live site will update within a couple seconds.")

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

with st.expander("Raw data (advanced, read-only preview)"):
    st.json({
        "scores": load_collection("scores"),
        "standings": load_collection("standings"),
        "schedule": load_collection("schedule"),
        "gallery": load_collection("gallery"),
    })
