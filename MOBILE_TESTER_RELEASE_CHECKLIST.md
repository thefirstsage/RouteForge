# RouteForge Mobile Tester Release Checklist

Use this before sending an Android APK to a field tester.

## Build Prep

- [ ] Open terminal in `C:\Users\User\Documents\Codex\LeadGen\mobile\routeforge-mobile`
- [ ] Run `npm.cmd install`
- [ ] Run TypeScript check:

```powershell
& 'C:\Program Files\nodejs\node.exe' '.\node_modules\typescript\bin\tsc' --noEmit
```

- [ ] Test in Expo Go:

```powershell
npx.cmd expo start --clear --tunnel
```

## Real Data Gate

- [ ] Confirm whether this APK is a demo-data test or real-data test.
- [ ] If demo-data test, verify the app clearly displays:

```text
Demo data — phone numbers are not real.
```

- [ ] If real-data test, verify hosted backend URL is set in `src/config.ts`.
- [ ] Generate businesses on a phone using cellular data, not just home WiFi.
- [ ] Confirm results are real businesses before sending APK to testers.

## APK Build

- [ ] Make sure tester APKs do not point to `localhost`.
- [ ] If using a hosted backend, update `C:\Users\User\Documents\Codex\LeadGen\mobile\routeforge-mobile\src\config.ts`:

```ts
hosted: "https://your-hosted-routeforge-api.example.com"
```

- [ ] Install EAS CLI if needed:

```powershell
npm.cmd install -g eas-cli
```

- [ ] Log in to Expo:

```powershell
eas login
```

- [ ] Configure EAS if needed:

```powershell
eas build:configure
```

- [ ] Build Android preview APK:

```powershell
eas build --platform android --profile preview
```

- [ ] If EAS reports `git command not found`, run the APK build without Git:

```powershell
$env:EAS_NO_VCS="1"; eas.cmd build --platform android --profile preview --clear-cache
```

- [ ] Download the APK from the EAS build link.
- [ ] Install APK on an Android phone.
- [ ] If Android blocks install, enable `Install unknown apps` for the browser/files app used to open the APK.

## Field Test

- [ ] Test Start Screen.
- [ ] Test Generate Businesses.
- [ ] Test selecting stops.
- [ ] Test Save Route.
- [ ] Test Resume Route.
- [ ] Test Google Maps route handoff.
- [ ] Test route parts for more than 10 stops.
- [ ] Test stop tracking:
  - [ ] Visited
  - [ ] Interested
  - [ ] Follow-Up
  - [ ] Not Interested
  - [ ] Done
- [ ] Test `More` actions:
  - [ ] Manager Not In
  - [ ] No Answer
  - [ ] Turned Away
  - [ ] Called
  - [ ] Skipped
- [ ] Test app close/reopen persistence.
- [ ] Test that Resume Last Route opens the newest unfinished route.

## Feedback To Collect

- [ ] What confused you?
- [ ] What felt fast or useful?
- [ ] Did Google Maps open the route correctly?
- [ ] Were stop buttons easy to use in the field?
- [ ] Would you use this on a real canvassing day?
- [ ] What would make it worth paying for?
