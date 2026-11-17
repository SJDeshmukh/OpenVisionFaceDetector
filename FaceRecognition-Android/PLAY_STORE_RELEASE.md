# TapInX Play Store release

The Play Store bundle is built from the `tapinxPlaystoreRelease` variant. This
variant uses the production API, disables the in-app APK updater, removes APK
installation permissions, and blocks cleartext HTTP traffic.

## One-time setup

1. Keep the application ID `tapinx.com`. Google Play
   treats the application ID as permanent after the first app is created.
2. Store the upload key outside source control and back it up securely.
3. Copy `keystore.properties.example` to `keystore.properties` and enter the
   upload-key path and passwords. The real file and key are ignored by Git.
4. Enable **Play App Signing** when creating the app in Play Console.

## Build

Use JDK 17 and an Android SDK containing platform 36 and Build Tools 35.0.0:

```bash
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export ANDROID_HOME="$HOME/Android/Sdk"
./gradlew clean bundleTapinxPlaystoreRelease
```

The signed bundle is written to:

`app/build/outputs/bundle/tapinxPlaystoreRelease/app-tapinx-playstore-release.aab`

Every Play upload must use a greater `versionCode`. Do not recreate or replace
the upload key without following Google Play's upload-key reset process.

## Play Console checklist

- Upload the `.aab` to Internal testing first and install it from Google Play.
- Complete App access with a working reviewer account and instructions.
- Publish a public privacy-policy URL.
- Complete Data safety for camera/face templates, account data, device ID,
  notifications, location, and any analytics actually collected.
- Complete the Foreground service declaration for the attendance listener.
- Declare the app category and whether the target audience includes children.
- Add app icon, feature graphic, phone screenshots, short description, and full
  description.
- Verify login, face enrollment, online/offline attendance, sync, manual
  check-in/out, notifications, and upgrade from the customer APK.
