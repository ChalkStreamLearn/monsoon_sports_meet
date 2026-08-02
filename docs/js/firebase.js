// ChalkStream — Firebase initialization
//
// 1. Go to https://console.firebase.google.com -> your project ->
//    Project settings -> General -> "Your apps" -> Web app.
// 2. Copy the config object shown there and paste the values below.
// 3. This file is safe to commit publicly - a Firebase web API key is not
//    a secret; access is controlled by firestore.rules / storage.rules,
//    not by hiding this config.
import { initializeApp } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-app.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-firestore.js";
import { getStorage } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-storage.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyAKOajhx7vxLXUMFE3Vu6w9XZS74tLoq1s",
  authDomain: "chalkstream-sports.firebaseapp.com",
  projectId: "chalkstream-sports",
  storageBucket: "chalkstream-sports.firebasestorage.app",
  messagingSenderId: "700889174885",
  appId: "1:700889174885:web:dcc39ab8b069b80758478c",
  measurementId: "G-2XTG0N1K2P"
};

const app = initializeApp(firebaseConfig);

export const db = getFirestore(app);
export const storage = getStorage(app);
export const auth = getAuth(app);
