// ChalkStream — live data layer
//
// Replaces the old fetch('data.json') call with real-time Firestore
// listeners. Whenever a document changes in Firestore (e.g. the admin
// panel updates a score), onSnapshot fires again and the page re-renders
// instantly — no refresh needed.
//
// This file assumes index.html defines renderScores(), renderStandings(),
// renderSchedule() and renderGallery() as globals (it attaches them to
// `window` right after defining them) and window.__reSyncLang() to keep
// the bilingual toggle working after new nodes are injected.

import { db } from "./firebase.js";
import {
  collection,
  onSnapshot,
  query,
  orderBy,
  doc,
} from "https://www.gstatic.com/firebasejs/12.0.0/firebase-firestore.js";

function afterRender() {
  if (typeof window.__reSyncLang === "function") window.__reSyncLang();
}

// ---------- Branding (logo + hero banner) ----------
const brandingRef = doc(db, "branding", "main");
onSnapshot(
  brandingRef,
  (snap) => {
    if (snap.exists()) {
      window.renderBranding(snap.data());
    }
  },
  (err) => console.error("branding listener failed:", err)
);

// ---------- Live Scores ----------
// Each doc in "scores" is one match card. Sort by an "order" number field
// so the admin panel controls card order (falls back gracefully if some
// older docs don't have it).
const scoresQuery = query(collection(db, "scores"), orderBy("order"));
onSnapshot(
  scoresQuery,
  (snapshot) => {
    const scores = snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    window.renderScores(scores);
    afterRender();
  },
  (err) => console.error("scores listener failed:", err)
);

// ---------- Schedule ----------
const scheduleQuery = query(collection(db, "schedule"), orderBy("order"));
onSnapshot(
  scheduleQuery,
  (snapshot) => {
    const schedule = snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    window.renderSchedule(schedule);
    afterRender();
  },
  (err) => console.error("schedule listener failed:", err)
);

// ---------- Standings ----------
// Each doc in "standings" is one sport's whole group (with a nested
// "teams" array), matching the original data.json shape exactly so
// renderStandings() doesn't need to change at all.
const standingsQuery = query(collection(db, "standings"), orderBy("order"));
onSnapshot(
  standingsQuery,
  (snapshot) => {
    const standings = snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    window.renderStandings(standings);
    afterRender();
  },
  (err) => console.error("standings listener failed:", err)
);

// ---------- Gallery ----------
const galleryQuery = query(collection(db, "gallery"), orderBy("uploadedAt", "desc"));
onSnapshot(
  galleryQuery,
  (snapshot) => {
    const gallery = snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    window.renderGallery(gallery);
    afterRender();
  },
  (err) => console.error("gallery listener failed:", err)
);
