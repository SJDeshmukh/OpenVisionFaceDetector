# Google login for the TapInX hostel portal

Google login is available on the web sign-in screen for pre-registered hostel students and staff. Firebase proves ownership of the Google account; TapInX remains the authority for the institution, role, student record, staff record, department, and assigned navbar pages.

## Firebase Console

1. Open the `tapinx-e6718` Firebase project.
2. In **Authentication → Sign-in method**, enable **Google** and select the support email.
3. In **Authentication → Settings → Authorized domains**, add:
   - `tapinx.in`
   - `www.tapinx.in`
   - the development hostname when testing locally
4. In **Project settings → Service accounts**, generate a private key for the backend. Never commit this JSON file.

## Backend server

Place the service-account JSON in a directory readable only by the backend service user. Add these values to `backend/.env`:

```dotenv
FIREBASE_PROJECT_ID=tapinx-e6718
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/firebase-service-account.json
```

`FIREBASE_CREDENTIALS_JSON` may be used instead of a file path when the deployment platform stores multiline JSON secrets. Restart `openvision-backend` after changing the environment. The same Firebase Admin configuration can be reused by FCM notifications.

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
