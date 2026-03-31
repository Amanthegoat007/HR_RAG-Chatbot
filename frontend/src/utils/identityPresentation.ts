import type { User } from "@/types/auth.types";

export interface IdentityPresentation {
  displayName: string;
  roleLabel: string;
  initials: string;
}

const UPPERCASE_TOKENS = new Set(["hr", "it", "qa", "ui", "ux"]);

function toTitleCaseSegment(segment: string): string {
  const normalized = segment.trim().toLowerCase();
  if (!normalized) return "";
  if (UPPERCASE_TOKENS.has(normalized)) {
    return normalized.toUpperCase();
  }
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function humanizeIdentifier(value: string): string {
  const raw = (value || "").split("@")[0].replace(/[_-]+/g, " ").trim();
  if (!raw) return "User";
  return raw
    .split(/\s+/)
    .map(toTitleCaseSegment)
    .filter(Boolean)
    .join(" ");
}

function getRoleLabel(user: User | null): string {
  const roles = user?.roles || [];
  if (roles.includes("ROLE_ADMIN") || roles.includes("ROLE_ADMINISTRATOR")) {
    return "HR Administrator";
  }
  return "Employee";
}

function getInitials(displayName: string): string {
  const parts = displayName.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return "U";
}

export function buildIdentityPresentation(user: User | null): IdentityPresentation {
  const displayName =
    [user?.given_name, user?.family_name].filter(Boolean).join(" ").trim() ||
    user?.name?.trim() ||
    humanizeIdentifier(user?.email || user?.sub || "");

  return {
    displayName,
    roleLabel: getRoleLabel(user),
    initials: getInitials(displayName),
  };
}
