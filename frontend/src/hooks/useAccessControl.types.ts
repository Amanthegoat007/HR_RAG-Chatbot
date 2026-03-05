export interface AccessControlConfig {
  allowedRoles?: string[];
  allowedGroups?: string[];
  requireAll?: boolean; // true = AND logic (must match role AND group), false = OR logic (default)
}
