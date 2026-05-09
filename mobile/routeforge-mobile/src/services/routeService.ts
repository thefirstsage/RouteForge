import type { BusinessStop } from "../models";
import { COMPLETED_ROUTE_STATUSES } from "../constants";

type Point = {
  latitude: number;
  longitude: number;
};

function hasCoordinates(stop: BusinessStop): boolean {
  return typeof stop.latitude === "number" && typeof stop.longitude === "number";
}

function pointFromStop(stop: BusinessStop): Point | null {
  if (!hasCoordinates(stop)) {
    return null;
  }
  return {
    latitude: stop.latitude ?? 0,
    longitude: stop.longitude ?? 0
  };
}

function pointFromText(value?: string): Point | null {
  if (!value) {
    return null;
  }
  const match = value.trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
  if (!match) {
    return null;
  }
  return {
    latitude: Number(match[1]),
    longitude: Number(match[2])
  };
}

function distanceBetweenPoints(first: Point | null, second: Point | null): number {
  if (!first || !second) {
    return Number.MAX_SAFE_INTEGER;
  }
  const lat = first.latitude - second.latitude;
  const lng = first.longitude - second.longitude;
  return Math.sqrt(lat * lat + lng * lng);
}

function distance(first: BusinessStop, second: BusinessStop): number {
  return distanceBetweenPoints(pointFromStop(first), pointFromStop(second));
}

function routeDistance(stops: BusinessStop[], startPoint: Point | null, returnToStart: boolean): number {
  if (!stops.length) {
    return 0;
  }
  let total = startPoint ? distanceBetweenPoints(startPoint, pointFromStop(stops[0])) : 0;
  for (let index = 1; index < stops.length; index += 1) {
    total += distance(stops[index - 1], stops[index]);
  }
  if (returnToStart) {
    total += startPoint
      ? distanceBetweenPoints(pointFromStop(stops[stops.length - 1]), startPoint)
      : distance(stops[stops.length - 1], stops[0]);
  }
  return total;
}

function greedyOrderFromStart(stops: BusinessStop[], firstStop: BusinessStop): BusinessStop[] {
  const remaining = stops.filter((stop) => stop.id !== firstStop.id);
  const ordered: BusinessStop[] = [firstStop];
  let current = firstStop;

  while (remaining.length) {
    remaining.sort((a, b) => distance(current, a) - distance(current, b));
    const next = remaining.shift();
    if (!next) {
      break;
    }
    ordered.push(next);
    current = next;
  }

  return ordered;
}

function twoOptImprove(stops: BusinessStop[], startPoint: Point | null, returnToStart: boolean): BusinessStop[] {
  if (stops.length > 40) {
    return stops;
  }

  let best = [...stops];
  let improved = true;
  let passes = 0;

  while (improved && passes < 4) {
    improved = false;
    passes += 1;
    for (let left = 1; left < best.length - 1; left += 1) {
      for (let right = left + 1; right < best.length; right += 1) {
        const candidate = [
          ...best.slice(0, left),
          ...best.slice(left, right + 1).reverse(),
          ...best.slice(right + 1)
        ];
        if (routeDistance(candidate, startPoint, returnToStart) < routeDistance(best, startPoint, returnToStart)) {
          best = candidate;
          improved = true;
        }
      }
    }
  }

  return best;
}

export function orderStopsForRoute(stops: BusinessStop[], startingLocation?: string): BusinessStop[] {
  if (stops.length < 2 || stops.some((stop) => !hasCoordinates(stop))) {
    return stops.map((stop, index) => ({ ...stop, routeStopNumber: index + 1 }));
  }

  const startPoint = pointFromText(startingLocation);
  const returnToStart = Boolean(startingLocation?.trim());
  let ordered: BusinessStop[];

  if (startPoint) {
    const firstStop = [...stops].sort(
      (a, b) => distanceBetweenPoints(startPoint, pointFromStop(a)) - distanceBetweenPoints(startPoint, pointFromStop(b))
    )[0];
    ordered = greedyOrderFromStart(stops, firstStop);
  } else {
    ordered = stops
      .map((firstStop) => greedyOrderFromStart(stops, firstStop))
      .sort((a, b) => routeDistance(a, null, returnToStart) - routeDistance(b, null, returnToStart))[0];
  }

  ordered = twoOptImprove(ordered, startPoint, returnToStart);
  return ordered.map((stop, index) => ({ ...stop, routeStopNumber: index + 1 }));
}

export function completedCount(stops: BusinessStop[]): number {
  return stops.filter((stop) => COMPLETED_ROUTE_STATUSES.includes(stop.status)).length;
}
