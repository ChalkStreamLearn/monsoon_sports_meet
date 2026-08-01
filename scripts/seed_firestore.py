"""
One-time migration: loads scripts/data.json (your original ChalkStream data)
into Cloud Firestore, so you don't have to re-type everything by hand in
the admin panel.

Usage:
    cd scripts
    pip install firebase-admin
    python seed_firestore.py

Requires admin/serviceAccountKey.json to already exist (see admin/admin.py
docstring for how to get it).

Safe to run once. Running it again will ADD duplicate documents — it does
not check for existing data first. If you need to re-seed, clear the
collections in the Firebase Console first (Firestore → select each
collection → delete documents), or delete the whole collection.
"""

import json
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

SCRIPT_DIR = Path(__file__).parent
SERVICE_ACCOUNT_PATH = SCRIPT_DIR.parent / "admin" / "serviceAccountKey.json"
DATA_FILE = SCRIPT_DIR / "data.json"


def main():
    if not SERVICE_ACCOUNT_PATH.exists():
        raise SystemExit(
            f"Missing {SERVICE_ACCOUNT_PATH}. Download it from Firebase Console "
            "→ Project Settings → Service Accounts, and place it there first."
        )
    if not DATA_FILE.exists():
        raise SystemExit(f"Missing {DATA_FILE}.")

    cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    scores = data.get("scores", [])
    for i, m in enumerate(scores):
        db.collection("scores").add({**m, "order": i})
    print(f"Seeded {len(scores)} score card(s).")

    schedule = data.get("schedule", [])
    for i, ev in enumerate(schedule):
        db.collection("schedule").add({**ev, "order": i})
    print(f"Seeded {len(schedule)} schedule row(s).")

    standings = data.get("standings", [])
    for i, group in enumerate(standings):
        db.collection("standings").add({**group, "order": i})
    print(f"Seeded {len(standings)} standings group(s).")

    gallery = data.get("gallery", [])
    for i, g in enumerate(gallery):
        # Note: this only carries over metadata. Local media/ files referenced
        # by old relative paths (e.g. "media/xyz.jpg") are NOT uploaded to
        # Firebase Storage by this script — re-upload those through the
        # admin panel's Gallery tab so they get real Storage URLs.
        db.collection("gallery").add({**g, "order": i, "uploadedAt": firestore.SERVER_TIMESTAMP})
    print(f"Seeded {len(gallery)} gallery item(s) (metadata only — re-upload files via admin panel).")

    print("\nDone. Check the Firebase Console → Firestore Database to confirm.")


if __name__ == "__main__":
    main()
