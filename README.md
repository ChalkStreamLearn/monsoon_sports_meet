# ChalkStream v2 — Firebase Edition

Live scores, schedule, standings & gallery for a school sports fest —
bilingual (Burmese/Chinese), served from GitHub + Firebase Hosting, with
data stored in Cloud Firestore instead of a static `data.json` file.

Once set up: updating a score in the admin panel makes it appear on the
live website within a second or two, for every visitor, with no redeploy.

```
chalkstream/
├── docs/                  ← deployed to GitHub Pages
│   ├── index.html           ← your site (design unchanged from v1)
│   └── js/
│       ├── firebase.js      ← Firebase project config (fill in below)
│       └── app.js           ← real-time Firestore listeners
├── admin/
│   ├── admin.py             ← Streamlit admin panel (writes to Firestore)
│   ├── requirements.txt
│   └── serviceAccountKey.json   ← you add this yourself, never committed
├── scripts/
│   ├── data.json            ← your original data, for one-time import
│   └── seed_firestore.py    ← loads data.json into Firestore, once
├── firestore.rules
├── storage.rules
├── firebase.json
├── .firebaserc
└── .github/workflows/deploy.yml
```

## 1. Create the Firebase project

1. Go to the [Firebase Console](https://console.firebase.google.com) → **Add project**.
2. Once created, enable:
   - **Firestore Database** (Build → Firestore Database → Create database → production mode)
   - **Storage** (Build → Storage → Get started)
   - **Hosting** (Build → Hosting → Get started — you can skip the CLI steps it shows you, we'll do that below)

## 2. Get your web app config

Project Settings (gear icon) → **Your apps** → Add app → Web (`</>`).
Copy the `firebaseConfig` object it gives you into **`docs/js/firebase.js`**,
replacing the placeholder values.

## 3. Get your service account key (for the admin panel)

Project Settings → **Service Accounts** → **Generate new private key**.
Save the downloaded file as **`admin/serviceAccountKey.json`**.
This file has full admin access to your Firebase project — it's already
listed in `.gitignore` so it can never accidentally get pushed to GitHub.

## 4. Install the Firebase CLI and connect this project

```bash
npm install -g firebase-tools
firebase login
```

Edit **`.firebaserc`** and replace `REPLACE_WITH_YOUR_FIREBASE_PROJECT_ID`
with your actual project ID (shown in Project Settings).

## 5. Import your existing data (one time)

```bash
cd scripts
pip install firebase-admin
python seed_firestore.py
```

This reads `scripts/data.json` and creates the matching documents in
Firestore. Check Firebase Console → Firestore Database afterward to
confirm the `scores`, `schedule`, `standings`, and `gallery` collections
were created.

> Note: any photos/videos your old gallery pointed to on local disk are
> **not** copied automatically — re-upload those through the admin panel's
> Gallery tab so they get real Firebase Storage URLs.

## 6. Run the admin panel

```bash
cd admin
pip install -r requirements.txt
ADMIN_PASSWORD=yourpassword streamlit run admin.py
```

Open the URL it prints (works on your phone too, same wifi network, or
via an ngrok/cloudflared tunnel for remote access). Log in, edit scores,
add gallery photos — changes save straight to Firestore/Storage.

## 7. Deploy the website

```bash
firebase deploy
```

This is pushed via git; GitHub Pages serves it directly from the docs/ folder.
You'll get a live URL like `https://your-project.web.app`.

Open it and confirm scores/schedule/standings load. Then open the admin
panel, change something, and watch it update on the live site without a
refresh.

## 8. (Optional) Auto-deploy from GitHub

`.github/workflows/deploy.yml` redeploys Hosting automatically whenever
you push changes to `docs/`, `firebase.json`, or the rules files —
content edits (scores etc.) don't need this, they go live instantly on
their own.

To enable it:
1. Generate a CI service account:
   ```bash
   firebase init hosting:github
   ```
   (or manually create a service account with the "Firebase Hosting Admin" role)
2. It will add a `FIREBASE_SERVICE_ACCOUNT` secret to your GitHub repo
   automatically — or add it yourself under **Settings → Secrets and
   variables → Actions**.
3. Edit `.github/workflows/deploy.yml` and replace
   `your-firebase-project-id` with your real project ID.

## How data flows

```
Admin panel (admin.py)  →  Firestore / Storage  →  Website (onSnapshot listeners)
        ↑
   Firebase Admin SDK (serviceAccountKey.json — full trust, bypasses rules)
```

The website never writes anything — `firestore.rules` and `storage.rules`
allow public **read** access but deny all client writes. Only `admin.py`,
running with your service account key, can change data. That means your
Firebase web config being visible in the page source (which it always is,
for any Firebase site) doesn't let anyone else edit your scores.

## Firestore collections

| Collection  | Shape |
|---|---|
| `scores`    | one doc per match: `sport_emoji`, `sport_mm`, `sport_zh`, `status`, `status_mm`, `status_zh`, `team_a`, `team_b`, `score`, `note_mm`, `note_zh`, `order` |
| `schedule`  | one doc per event: `date`, `title_mm`, `title_zh`, `sub_mm`, `sub_zh`, `tag_mm`, `tag_zh`, `is_emoji_tag`, `order` |
| `standings` | one doc per sport: `sport_key`, `sport_emoji`, `sport_mm`, `sport_zh`, `qualify_count`, `total_rounds`, `note_mm`, `note_zh`, `teams` (array), `order` |
| `gallery`   | one doc per photo/video: `type`, `src` (Storage public URL), `storage_path`, `tag_emoji`, `tag_mm`, `tag_zh`, `cap_mm`, `cap_zh`, `uploadedAt` |
| `branding`  | single doc (`main`): `logo_url`, `logo_public_id`, `banner_mode` (`slideshow`/`video`), `banner_images` (array of `{url, public_id}`), `banner_video_url`, `banner_video_public_id` — edited from the admin panel's Branding tab |

## Costs

Firestore, Storage, and Hosting all have generous free tiers (Spark plan)
that comfortably cover a small school sports site — real-time listeners
count as reads, so expect a small number of reads per visitor per
session, not per second.
