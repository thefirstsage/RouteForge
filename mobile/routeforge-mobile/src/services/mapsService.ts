import { Linking, Alert } from "react-native";
import type { BusinessStop, RouteSession } from "../models";

const GOOGLE_ROUTE_LIMIT = 10;

export type GoogleRoutePart = {
  index: number;
  label: string;
  origin: string;
  destination: string;
  waypoints: string[];
  stops: BusinessStop[];
};

function encode(value: string): string {
  return encodeURIComponent(value.trim());
}

function stopLocation(stop: BusinessStop): string {
  if (typeof stop.latitude === "number" && typeof stop.longitude === "number") {
    return `${stop.latitude},${stop.longitude}`;
  }
  return stop.address || stop.name;
}

export async function openStopInGoogleMaps(stop: BusinessStop): Promise<void> {
  const query = stop.address || stop.name;
  if (!query) {
    Alert.alert("No address", "This stop does not have an address to open.");
    return;
  }
  await Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${encode(query)}`);
}

export function getGoogleMapsRouteParts(session: RouteSession): GoogleRoutePart[] {
  const stops = session.stops.filter((stop) => stopLocation(stop).trim());
  if (!stops.length) {
    return [];
  }
  const hasStartingLocation = Boolean(session.startingLocation.trim());

  if (stops.length <= GOOGLE_ROUTE_LIMIT) {
    const origin = hasStartingLocation ? session.startingLocation : stopLocation(stops[0]);
    const destination = hasStartingLocation ? session.startingLocation : stopLocation(stops[stops.length - 1]);
    const waypoints = hasStartingLocation
      ? stops.map(stopLocation)
      : stops.slice(1, -1).map(stopLocation);
    return [
      {
        index: 0,
        label: hasStartingLocation ? `Stops 1-${stops.length} + return` : `Stops 1-${stops.length}`,
        origin,
        destination,
        waypoints,
        stops
      }
    ];
  }

  const parts: GoogleRoutePart[] = [];
  for (let start = 0; start < stops.length; start += GOOGLE_ROUTE_LIMIT) {
    const chunkStops = stops.slice(start, start + GOOGLE_ROUTE_LIMIT);
    const previousStop = start > 0 ? stops[start - 1] : null;
    const origin = previousStop ? stopLocation(previousStop) : (hasStartingLocation ? session.startingLocation : stopLocation(chunkStops[0]));
    const isFinalPart = start + GOOGLE_ROUTE_LIMIT >= stops.length;
    const destination = isFinalPart && hasStartingLocation
      ? session.startingLocation
      : stopLocation(chunkStops[chunkStops.length - 1]);
    const waypoints = isFinalPart && hasStartingLocation
      ? chunkStops.map(stopLocation)
      : chunkStops
        .slice(previousStop || hasStartingLocation ? 0 : 1, -1)
        .map(stopLocation);
    const firstStopNumber = start + 1;
    const lastStopNumber = start + chunkStops.length;
    parts.push({
      index: parts.length,
      label: isFinalPart && hasStartingLocation
        ? `Stops ${firstStopNumber}-${lastStopNumber} + return`
        : `Stops ${firstStopNumber}-${lastStopNumber}`,
      origin,
      destination,
      waypoints,
      stops: chunkStops
    });
  }
  return parts;
}

async function openGoogleMapsDirections(origin: string, destination: string, waypoints: string[]): Promise<void> {
  const routePlaces = [origin, ...waypoints, destination].filter((place) => place.trim());
  const routePath = routePlaces.map(encode).join("/");
  const url = `https://www.google.com/maps/dir/${routePath}?travelmode=driving`;

  await Linking.openURL(url);
}

export async function openRoutePartInGoogleMaps(session: RouteSession, partIndex: number): Promise<void> {
  const parts = getGoogleMapsRouteParts(session);
  const part = parts[partIndex];
  if (!part) {
    Alert.alert("No route part", "This route part could not be opened.");
    return;
  }

  await openGoogleMapsDirections(part.origin, part.destination, part.waypoints);
}

export async function openRouteInGoogleMaps(session: RouteSession): Promise<void> {
  const parts = getGoogleMapsRouteParts(session);
  if (!parts.length) {
    Alert.alert("No stops", "Add stops before opening the route.");
    return;
  }

  if (parts.length > 1) {
    Alert.alert(
      "Route split into parts",
      `Google Maps is most reliable with ${GOOGLE_ROUTE_LIMIT} stops at a time. Opening Part 1 now. Use the route part buttons to open the rest.`
    );
  }

  await openRoutePartInGoogleMaps(session, 0);
}
