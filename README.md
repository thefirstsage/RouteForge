# Route2Revenue

Route2Revenue is a simple field sales route builder and follow-up tracker for local service businesses.

Tagline: Plan your route. Knock more doors. Close more deals.

## What It Does

- Find local businesses by city, state, radius, and business type.
- Build a practical driving route with **Build My Day**.
- Print a **Door-Knocking Sheet** or **Call List**.
- Track calls, door knocks, interested businesses, and follow-up dates.
- Reopen saved progress later and keep working from the Follow-Ups tab.

## Daily Workflow

1. Open Route2Revenue.
2. Enter the city where you are working today.
3. Click **Find Today's Businesses**.
4. Click **Build My Day**.
5. Start the driving route, print the door-knocking sheet, or print the call list.
6. Mark outcomes and set follow-up dates.
7. Save progress so you can continue later.

Missing emails are normal. Phone numbers, addresses, route order, notes, and follow-up dates matter most for field sales.

## Running The App

After building, open:

```text
dist\Route2Revenue\Route2Revenue.exe
```

The helper command file is:

```text
Open Route2Revenue.cmd
```

## Rebuilding

Run:

```text
Codex Rebuild Existing Env.ps1
```

The build keeps one backup version and removes older backup versions to avoid piling up storage.

## Saved Data

Saved progress, routes, presets, and config are stored under:

```text
%LOCALAPPDATA%\Route2Revenue
```

If an older app data folder exists under the previous product name, Route2Revenue copies saved leads, routes, presets, and config into the new folder without deleting the old data.

## Legal

- Privacy Policy: [docs/privacy-policy.md](docs/privacy-policy.md)
