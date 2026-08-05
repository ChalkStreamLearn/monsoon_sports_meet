import { initializeApp } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-app.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/12.0.0/firebase-firestore.js";

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
const db = getFirestore(app);

export { app, db };
