# ChalkStream Sports — Rainy Season Sports Meet

Live scores, schedule, standings & gallery for the Rainy Season Sports Meet —
bilingual (Burmese/Chinese), hosted on **GitHub Pages**, with real-time data
in **Cloud Firestore** and gallery photos/videos on **Cloudinary**.

Once set up: updating a score in the admin panel makes it appear on the
live website within a second or two, for every visitor, with no redeploy.

**Live site:** https://chalkstreamlearn.github.io/monsoon_sports_meet/

```
monsoon_sports_meet/
├── docs/                     ← deployed directly by GitHub Pages
│   ├── index.html              site markup, CSS, and render functions
│   ├── manifest.json           "Add to Home Screen" icon/name config
│   ├── assets/                  favicon, apple-touch-icon, PWA icons
│   └── js/
│       ├── firebase.js          Firebase project config (real values filled in)
│       └── app.js               real-time Firestore listeners
├── admin/
│   ├── admin.py                 Streamlit admin panel — deployed on
│   │                            Streamlit Community Cloud, reachable from
│   │                            any phone, no server needs to stay on
│   ├── requirements.txt
│   └── serviceAccountKey.json   you add this yourself, never committed
│                                (on Streamlit Cloud this lives in Secrets
│                                 as a [firebase_service_account] table instead)
├── scripts/
│   ├── data.json                 source content for a one-time / reset seed
│   ├── seed_firestore.py         loads data.json into empty collections
│   └── reset_and_reseed.py       clears scores/schedule/standings and
│                                 reloads them from data.json (safe to
│                                 re-run — never touches gallery)
├── firestore.rules
├── firebase.json                 Firestore-only config (no Hosting section —
│                                 GitHub Pages replaced Firebase Hosting)
└── .firebaserc
```

## 1. Firebase project

1. [Firebase Console](https://console.firebase.google.com) → **Add project** → name it (e.g. `chalkstream-sports`).
2. Enable **Firestore Database** (Build → Firestore Database → Create database → production mode, region `asia-southeast1`).
3. Firebase **Storage** is *not* used — Storage requires the paid Blaze
   plan, so gallery media goes to Cloudinary's free tier instead (below).

## 2. Web app config

Project Settings (gear icon) → **Your apps** → Add app → Web (`</>`).
Copy the `firebaseConfig` object into **`docs/js/firebase.js`**. This is
safe to commit publicly — a Firebase web API key isn't a secret; access is
controlled by `firestore.rules`, not by hiding this file.

## 3. Service account key (for the admin panel)

Project Settings → **Service Accounts** → **Generate new private key**.
- **Local use:** save as `admin/serviceAccountKey.json` (already in `.gitignore`).
- **Streamlit Community Cloud:** paste its contents into the app's
  **Settings → Secrets** as a `[firebase_service_account]` TOML table instead
  (see `admin/admin.py` for the exact field names expected).

## 4. Cloudinary (gallery photos/videos)

1. Sign up free at [cloudinary.com](https://cloudinary.com) — no card required.
2. Settings → Upload → **Add upload preset** → Signing Mode: **Unsigned**.
3. Set these two values (as env vars locally, or Streamlit Secrets on Cloud):
   ```
   CLOUDINARY_CLOUD_NAME=<your cloud name>
   CLOUDINARY_UPLOAD_PRESET=<your preset name>
   ```
   Optional — only needed so the admin panel's delete button can also
   remove the file from Cloudinary itself:
   ```
   CLOUDINARY_API_KEY=...
   CLOUDINARY_API_SECRET=...
   ```

## 5. Load the initial data

```
cd scripts
pip install firebase-admin
python seed_firestore.py
```

This reads `scripts/data.json` and creates the matching documents in
Firestore. Check Firebase Console → Firestore Database afterward to
confirm the `scores`, `schedule`, `standings`, and `gallery` collections
were created.

To reset scores/schedule/standings back to `data.json` later (e.g. after
editing team names or the schedule) without duplicating documents, use:
```
python reset_and_reseed.py
```
This clears those three collections first, then reloads them — `gallery`
is never touched, so uploaded photos/videos are always safe.

## 6. Run the admin panel

**Locally:**
```
cd admin
pip install -r requirements.txt
ADMIN_PASSWORD=yourpassword streamlit run admin.py
```

**On Streamlit Community Cloud (recommended — works from your phone,
no computer needs to stay on):**
1. [share.streamlit.io](https://share.streamlit.io) → sign in with GitHub
2. New app → repository `ChalkStreamLearn/monsoon_sports_meet`, branch `main`,
   main file path `admin/admin.py`
3. Add the secrets from steps 3–4 above under **Settings → Secrets**

Log in, edit scores, add gallery photos — changes save straight to
Firestore/Cloudinary and appear on the live site within seconds.

## 7. Deploy the website

The site is plain static HTML/CSS/JS — no build step. Push to `main` and
GitHub Pages (Settings → Pages → Deploy from a branch → `main` / `/docs`)
publishes it automatically within about a minute. Content changes (scores,
schedule, gallery) never need this — they go live instantly through
Firestore on their own.

## How data flows

```
Admin panel (admin.py)  →  Firestore / Cloudinary  →  Website (onSnapshot listeners)
        ↑
   Firebase Admin SDK (serviceAccountKey.json — full trust, bypasses rules)
```

The website never writes anything — `firestore.rules` allows public
**read** access but denies all client writes. Only `admin.py`, running
with the service account key, can change data. That means the Firebase
web config being visible in the page source (which it always is, for any
Firebase site) doesn't let anyone else edit the scores.

## Firestore collections

| Collection  | Shape                                                                                                                                                    |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scores`    | one doc per match: `sport_emoji`, `sport_mm`, `sport_zh`, `status`, `status_mm`, `status_zh`, `team_a`, `team_b`, `score`, `note_mm`, `note_zh`, `order` |
| `schedule`  | one doc per event: `date`, `title_mm`, `title_zh`, `sub_mm`, `sub_zh`, `tag_mm`, `tag_zh`, `is_emoji_tag`, `order`                                       |
| `standings` | one doc per sport: `sport_key`, `sport_emoji`, `sport_mm`, `sport_zh`, `qualify_count`, `total_rounds`, `note_mm`, `note_zh`, `teams` (array), `order`   |
| `gallery`   | one doc per photo/video: `type`, `src` (Cloudinary URL), `public_id`, `tag_emoji`, `tag_mm`, `tag_zh`, `cap_mm`, `cap_zh`, `uploadedAt`                  |

## Costs

Firestore's free tier comfortably covers a small school sports site
(real-time listeners count as reads, not writes-per-second). Cloudinary's
free tier (25GB storage/bandwidth) covers gallery media. GitHub Pages and
Streamlit Community Cloud are both free. No billing account is required
anywhere in this stack.
