// ChalkStream — Firebase initialization
//
// 1. Go to https://console.firebase.google.com -> your project ->
//    Project settings -> General -> "Your apps" -> Web app.
// 2. Copy the config object shown there and paste the values below.
// 3. This file is safe to commit publicly - a Firebase web API key is not
//    a secret; access is controlled by firestore.rules / storage.rules,
//    not by hiding this config.
import { initializeApp } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-app.js";
import {
  initializeFirestore,
  persistentLocalCache,
} from "https://www.gstatic.com/firebasejs/12.0.0/firebase-firestore.js";
import { getStorage } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-storage.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "YOUR_API_KEY",
  authDomain: "YOUR_PROJECT.firebaseapp.com",
  projectId: "YOUR_PROJECT",
  storageBucket: "YOUR_PROJECT.appspot.com",
  messagingSenderId: "XXXXXXXXXXXX",
  appId: "1:XXXXXXXXXXXX:web:XXXXXXXXXXXXXXXXXXXXXX"
};

const app = initializeApp(firebaseConfig);

// persistentLocalCache turns on Firestore's built-in offline cache
// (IndexedDB under the hood). The first time a phone opens this site with
// internet on, every doc it reads gets cached locally; after that, opening
// the site with no connection at all still shows that last-synced data
// instead of a blank/error page — used by the Android WebView wrapper app
// to show scores/fixtures/results while offline.
export const db = initializeFirestore(app, {
  localCache: persistentLocalCache(),
});
export const storage = getStorage(app);
export const auth = getAuth(app);
