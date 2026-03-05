import { useAppSelector } from "@/store/hooks";

import type { AccessControlConfig } from "./useAccessControl.types";

export type { AccessControlConfig };

export function useAccessControl() {
  const userRoles = useAppSelector((state) => state.auth.roles || []);
  const userGroups = useAppSelector((state) => state.auth.groups || []);

  /**
   * Check if user has access based on configuration
   * @param config - Access control configuration
   * @returns true if user has access, false otherwise
   */
  const hasAccess = (config: AccessControlConfig): boolean => {
    const { allowedRoles = [], allowedGroups = [], requireAll = true } = config;

    // If no restrictions defined, allow access
    if (allowedRoles.length === 0 && allowedGroups.length === 0) {
      return true;
    }

    // Normalize groups to lowercase for case-insensitive comparison
    const normalizedUserGroups = userGroups.map((g) => g.toLowerCase());
    const normalizedAllowedGroups = allowedGroups.map((g) => g.toLowerCase());

    // Check if user has any of the allowed roles
    const hasRole =
      allowedRoles.length === 0 ||
      allowedRoles.some((role) => userRoles.includes(role));

    // Check if user belongs to any of the allowed groups
    // Support hierarchical matching: a user in '/zones/ZONE_SOUTH/circles/BETA'
    // matches a requirement for '/zones/ZONE_SOUTH'
    const hasGroup =
      allowedGroups.length === 0 ||
      normalizedAllowedGroups.some((allowedGroup) =>
        normalizedUserGroups.some(
          (userGroup) =>
            userGroup === allowedGroup ||
            userGroup.startsWith(allowedGroup + "/"),
        ),
      );

    // Return based on requireAll flag
    if (requireAll) {
      // AND logic: must satisfy both role and group requirements
      const roleCheck = allowedRoles.length === 0 || hasRole;
      const groupCheck = allowedGroups.length === 0 || hasGroup;
      return roleCheck && groupCheck;
    } else {
      // OR logic: satisfy either role or group requirement
      return hasRole || hasGroup;
    }
  };

  return {
    hasAccess,
    userRoles,
    userGroups,
  };
}
