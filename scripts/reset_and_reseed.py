"""
One-time update: clears the OLD scores/schedule/standings documents (the
original demo placeholder data) and reloads them from the updated
scripts/data.json — the real team counts (10 football / 8 basketball /
6 volleyball, teams labeled A, B, C...) and the Aug 14 lottery-draw
announcement.

The `gallery` collection is left completely untouched — real uploaded
photos/videos are never deleted by this script.

Usage:
    cd scripts
    pip install firebase-admin
    python reset_and_reseed.py

Requires admin/serviceAccountKey.json to already exist.
Safe to run more than once — it clears before it re-adds, so it never
creates duplicates.
"""

import json
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

SCRIPT_DIR = Path(__file__).parent
SERVICE_ACCOUNT_PATH = SCRIPT_DIR.parent / "admin" / "serviceAccountKey.json"
DATA_FILE = SCRIPT_DIR / "data.json"

COLLECTIONS_TO_RESET = ["scores", "schedule", "standings"]


def clear_collection(db, name):
    docs = list(db.collection(name).stream())
    for doc in docs:
        doc.reference.delete()
    print(f"Cleared {len(docs)} old document(s) from '{name}'.")


def main():
    if not SERVICE_ACCOUNT_PATH.exists():
        raise SystemExit(
            f"Missing {SERVICE_ACCOUNT_PATH}. Download it from Firebase Console "
            "→ Project Settings → Service Accounts, and place it there first."
        )
    if not DATA_FILE.exists():
        raise SystemExit(f"Missing {DATA_FILE}.")

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    for name in COLLECTIONS_TO_RESET:
        clear_collection(db, name)

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

    print("\nDone. gallery collection was left untouched.")
    print("Check the Firebase Console → Firestore Database to confirm, or refresh the live site.")


if __name__ == "__main__":
    main()
