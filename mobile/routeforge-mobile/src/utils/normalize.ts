import type { BusinessStop, HiddenBusiness } from "../models";

export function normalizeText(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function normalizePhone(value: string): string {
  return value.replace(/\D/g, "");
}

export function hiddenBusinessFromStop(stop: BusinessStop, reason: string): HiddenBusiness {
  return {
    id: `${Date.now()}-${stop.id}`,
    normalizedName: normalizeText(stop.name),
    normalizedAddress: normalizeText(stop.address),
    phone: normalizePhone(stop.phone),
    reason,
    hiddenAt: new Date().toISOString()
  };
}

export function isStopHidden(stop: BusinessStop, hiddenBusinesses: HiddenBusiness[]): boolean {
  const normalizedName = normalizeText(stop.name);
  const normalizedAddress = normalizeText(stop.address);
  const phone = normalizePhone(stop.phone);

  return hiddenBusinesses.some((hidden) => {
    const nameMatch = hidden.normalizedName && hidden.normalizedName === normalizedName;
    const addressMatch = hidden.normalizedAddress && hidden.normalizedAddress === normalizedAddress;
    const phoneMatch = hidden.phone && phone && hidden.phone === phone;
    return Boolean(phoneMatch || (nameMatch && addressMatch));
  });
}
