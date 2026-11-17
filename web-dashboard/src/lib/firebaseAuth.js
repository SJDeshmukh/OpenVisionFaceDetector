import { getApps, initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';

// Firebase web identifiers are public by design. Environment overrides keep
// staging deployments separate while these production defaults make the
// checked-in TapInX bundle immediately usable for the configured project.
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || 'AIzaSyAO2YUH9aiCNibWCWD-rOEfSm1AXRpSB3w',
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || 'tapinx-e6718.firebaseapp.com',
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || 'tapinx-e6718',
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || 'tapinx-e6718.firebasestorage.app',
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '12227298938',
  appId: import.meta.env.VITE_FIREBASE_APP_ID || '1:12227298938:web:f70233fd261e9ecc28ddc3',
  measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID || 'G-Z39MVDFNEG',
};

const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);

export const firebaseAuth = getAuth(app);
export const googleAuthProvider = new GoogleAuthProvider();
googleAuthProvider.setCustomParameters({ prompt: 'select_account' });
