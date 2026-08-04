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

// ---------- Match fixtures ----------
// Cached so the "Teams" listener below can re-render fixtures with fresh
// colors without needing its own copy of the match data.
let __latestMatches = [];
const matchesQuery = query(collection(db, "matches"), orderBy("order"));
onSnapshot(
  matchesQuery,
  (snapshot) => {
    __latestMatches = snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    window.renderMatches(__latestMatches);
    afterRender();
  },
  (err) => console.error("matches listener failed:", err)
);

// ---------- Teams (colors) ----------
// Each doc in "teams" is one team: { name, color }. Set once per team in
// the admin panel's "Teams" tab — every fixture/score chip for that team
// picks it up automatically, everywhere on the site.
const teamsQuery = query(collection(db, "teams"));
onSnapshot(
  teamsQuery,
  (snapshot) => {
    const colorMap = {};
    snapshot.docs.forEach((doc) => {
      const d = doc.data();
      if (d.name) colorMap[d.name] = d.color;
    });
    window.setTeamColors(colorMap);
    // Re-render fixtures now that colors are (or just changed) available.
    window.renderMatches(__latestMatches);
    afterRender();
  },
  (err) => console.error("teams listener failed:", err)
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

// ---------- Audio (live commentary clips) ----------
// Each doc in "audio" is one uploaded clip: { src, who_mm/who_zh,
// what_mm/what_zh, public_id, uploadedAt }. Newest clip first, same as
// Gallery, so a freshly-uploaded commentary clip shows up at the top.
const audioQuery = query(collection(db, "audio"), orderBy("uploadedAt", "desc"));
onSnapshot(
  audioQuery,
  (snapshot) => {
    const audio = snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }));
    window.renderAudio(audio);
    afterRender();
  },
  (err) => console.error("audio listener failed:", err)
);
