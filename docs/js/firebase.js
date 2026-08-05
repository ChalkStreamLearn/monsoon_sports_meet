// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyAKOajhx7vxLXUMFE3Vu6w9XZS74tLoq1s",
  authDomain: "chalkstream-sports.firebaseapp.com",
  projectId: "chalkstream-sports",
  storageBucket: "chalkstream-sports.firebasestorage.app",
  messagingSenderId: "700889174885",
  appId: "1:700889174885:web:dcc39ab8b069b80758478c",
  measurementId: "G-2XTG0N1K2P"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);