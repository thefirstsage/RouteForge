# RouteForge Mobile Field UX Review - May 8, 2026

This file summarizes the latest RouteForge mobile MVP updates for review in ChatGPT or another code reviewer.

Project path:

`C:\Users\User\Documents\Codex\LeadGen\mobile\routeforge-mobile`

Main files to review:

- `App.tsx`
- `src/constants.ts`
- `src/models.ts`
- `src/services/routeService.ts`
- `src/services/mapsService.ts`
- `src/services/mockBusinessProvider.ts`

Desktop note:

These changes are for the mobile Expo app. The desktop PySide6 app should remain untouched.

---

## Current Product Goal

RouteForge mobile should feel like:

**Google Maps + canvassing memory + quick stop tracking**

The app should help a field worker:

1. Find businesses.
2. Pick stops.
3. Build a route.
4. Open Google Maps.
5. Track what happened at each stop.
6. Resume later without losing progress.

It should not feel like a CRM, dashboard, spreadsheet, or admin tool.

---

## Latest UX Changes

### 1. Today’s Route Is Now The Primary Work Screen

The Today’s Route screen was simplified and made more field-friendly.

Changes:

- Larger route stop cards.
- Business name and address are visually prioritized.
- Phone/details are lower emphasis.
- Common field actions are immediately visible.
- Less common statuses are hidden under `More`.
- Completed stops compress so the user can keep moving down the route.

Primary quick actions:

- Visited
- Interested
- Follow-Up
- Not Interested
- Done

Secondary actions under `More`:

- Manager Not In
- No Answer
- Turned Away
- Called
- Skipped

Review question:

Are these the right default quick actions for canvassing / door knocking?

---

### 2. Added `Visited` Status

`Visited` was added as a first-class stop status.

Files:

- `src/models.ts`
- `src/constants.ts`

Relevant model update:

```ts
export type StopStatus =
  | "New"
  | "Visited"
  | "Stopped In"
  | "Turned Away"
  | "Manager Not In"
  | "Called"
  | "No Answer"
  | "Interested"
  | "Need Follow-Up"
  | "Not Interested"
  | "Done"
  | "Skipped";
```

Review question:

Should `Stopped In` remain as a secondary status, or should it be removed now that `Visited` exists?

---

### 3. Completed Stops Now Compress

Problem:

After a stop is handled, it still took up too much screen space.

Fix:

Stops with completed statuses render as smaller compressed cards unless expanded.

Completed statuses currently include:

```ts
export const COMPLETED_ROUTE_STATUSES: StopStatus[] = [
  "Visited",
  "Stopped In",
  "Interested",
  "Need Follow-Up",
  "Not Interested",
  "Done",
  "Skipped"
];
```

Review question:

Should `Interested` and `Need Follow-Up` count as completed for route progress, or should only `Done`, `Visited`, `Not Interested`, and `Skipped` count?

---

### 4. Progress Bar Added

Today’s Route now shows:

- Completion percentage
- Completed count
- Follow-up count
- Interested count

Relevant helper in `App.tsx`:

```ts
function renderRouteProgress(session: RouteSession, followUps: number, interested: number) {
  const completed = completedCount(session.stops);
  const percent = session.stops.length ? Math.round((completed / session.stops.length) * 100) : 0;
  return (
    <View style={styles.progressCard}>
      <View style={styles.progressHeader}>
        <Text style={styles.progressTitle}>{percent}% complete</Text>
        <Text style={styles.progressMeta}>{completed}/{session.stops.length} stops</Text>
      </View>
      <View style={styles.progressTrack}>
        <View style={[styles.progressFill, { width: `${percent}%` }]} />
      </View>
      <View style={styles.progressStats}>
        <Text style={styles.progressStat}>{followUps} follow-ups</Text>
        <Text style={styles.progressStat}>{interested} interested</Text>
      </View>
    </View>
  );
}
```

Review question:

Is this enough route progress context, or should it also show “next incomplete stop”?

---

### 5. Resume Last Route Added

Problem:

A user reopening the app should not have to hunt for an unfinished route.

Fix:

On the Start screen, if an unfinished saved route exists, RouteForge shows:

- Resume Last Route
- Start New Route

Relevant logic:

```ts
const lastUnfinishedRoute = useMemo(() => {
  return savedRoutes.find((route) => completedCount(route.stops) < route.stops.length) ?? null;
}, [savedRoutes]);
```

Review question:

Should “last unfinished route” be based on most recently updated route instead of saved route order?

---

### 6. Business Result Filters Added

Problem:

Generated results can feel overwhelming on mobile.

Fix:

Added simple filter chips:

- All
- Best Stops
- Most Walkable
- Multi-store Plazas
- High Density

Relevant type:

```ts
type BusinessFilter = "all" | "best" | "walkable" | "plazas" | "dense";
```

Relevant helper ideas:

```ts
function isWalkableStop(stop: BusinessStop): boolean {
  const category = stop.category.toLowerCase();
  return (
    stop.bestStop ||
    category.includes("plaza") ||
    category.includes("storefront") ||
    category.includes("retail") ||
    category.includes("restaurant") ||
    category.includes("cafe")
  );
}
```

Review question:

Are these filters useful enough for field testing, or should there be fewer choices?

---

## Existing Route / Google Maps Behavior

Recent routing behavior still applies:

- RouteForge orders selected stops to reduce driving distance.
- Google Maps opens externally.
- Long routes are split into parts because Google Maps links have practical waypoint limits.
- First route part starts from the user’s starting location.
- Later parts start from the previous part’s last stop.
- Final part returns to starting location when possible.

Known limitation:

Google Maps public links do not provide true unlimited automatic route optimization. RouteForge does the simple local ordering first, then sends that order to Google Maps.

Review question:

Should RouteForge eventually add a backend optimizer / mapping API, or is this enough for the MVP test?

---

## Acceptance Check Run

TypeScript check passed:

```powershell
& 'C:\Program Files\nodejs\node.exe' '.\node_modules\typescript\bin\tsc' --noEmit
```

Run from:

`C:\Users\User\Documents\Codex\LeadGen\mobile\routeforge-mobile`

---

## What ChatGPT Should Review

Please review:

1. Today’s Route action hierarchy.
2. Whether completed stops should compress exactly as implemented.
3. Whether `Visited` and `Stopped In` both need to exist.
4. Whether progress calculation should count follow-ups/interested as completed.
5. Whether the Start screen resume logic is enough.
6. Whether business filters reduce friction or add clutter.
7. Any obvious bugs or TypeScript/React Native issues in the current approach.

