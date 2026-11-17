# Google login for the TapInX hostel portal

Google login is available on the web sign-in screen for pre-registered hostel students and staff. Firebase proves ownership of the Google account; TapInX remains the authority for the institution, role, student record, staff record, department, and assigned navbar pages.

## Firebase Console

1. Open the `tapinx-e6718` Firebase project.
2. In **Authentication → Sign-in method**, enable **Google** and select the support email.
3. In **Authentication → Settings → Authorized domains**, add:
   - `tapinx.in`
   - `www.tapinx.in`
   - the development hostname when testing locally
4. A service-account private key is not required for Google login token
   verification. Generate one only when the deployment also needs privileged
   Firebase Admin operations such as FCM v1, and never commit it.

## Backend server

Add the Firebase project ID to `backend/.env`:

```dotenv
FIREBASE_PROJECT_ID=tapinx-e6718
```

Restart `openvision-backend` after changing the environment. Google login uses
Google's cached public signing certificates and does not need a private key.
For FCM v1, additionally set `GOOGLE_APPLICATION_CREDENTIALS` to a protected
service-account JSON file, or provide `FIREBASE_CREDENTIALS_JSON` through the
deployment secret manager.

## Account matching rules

- The vendor must have web login enabled and use the `hostel` vertical.
- The Google email must exactly match a registered TapInX email.
- Students are matched through email fields in their resident profile, such as `email`, `student_email`, or `employee_email`.
- Staff are matched through the email saved in **Leave Management Configuration → Staff**.
- Unknown emails are rejected and never create a tenant or profile.
- Staff receive only the navbar pages assigned by SuperAdmin. Their signed staff session is revalidated against the current database record.
- Existing password login remains available.
- The Android attendance application is unaffected.

## Deployment check

After deployment, use a registered hostel student and a registered staff email to test **Continue with Google**. Also test an unregistered Google account and confirm that TapInX rejects it with the institution-registration message.
