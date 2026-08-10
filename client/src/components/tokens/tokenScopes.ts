/**
 * Permission-bucket helpers for the Create Token form (issue #6032).
 *
 * The create form offers coarse "buckets" (read / invoke / create / update /
 * delete) rather than raw `resource.action` scopes. The universe of concrete
 * scopes is the backend permission catalog (`GET /rbac/permissions/available`,
 * i.e. `Permissions` in `mcpgateway/db.py`) — never hardcoded here — filtered to
 * the scopes the caller can actually grant for the selected team
 * (`GET /rbac/my/permissions`). This guarantees the checklist can never offer a
 * scope the backend would reject (`_validate_scope_containment` is fail-secure).
 *
 * A caller holding the `*` wildcard (e.g. a platform admin) can grant every
 * dot-form scope in the catalog. Colon-form permissions (`logs:read`,
 * `admin.sso_providers:create`, …) are excluded: `TokenScopeRequest.validate_permissions`
 * only accepts a single-dot `resource.action`.
 *
 * `servers.use` is displayed under "invoke" (per design) but excluded from the
 * submitted scope list: the backend auto-injects it for any `tools.*` /
 * `resources.*` / `prompts.*` scope, so it is not an independently granted scope.
 */

export type PermissionBucket = "read" | "invoke" | "create" | "update" | "delete";

export const PERMISSION_BUCKET_ORDER: PermissionBucket[] = [
  "read",
  "invoke",
  "create",
  "update",
  "delete",
];

/** Backend-injected transport scope — shown as a chip but never submitted. */
export const AUTO_INJECTED_SCOPE = "servers.use";

const WILDCARD = "*";

/** Verb suffixes that place a `resource.action` scope in a bucket. */
const BUCKET_SUFFIXES: Record<PermissionBucket, string[]> = {
  read: [".read"],
  invoke: [".execute", ".invoke"],
  create: [".create"],
  update: [".update"],
  delete: [".delete"],
};

/**
 * Dot-form catalog scopes the caller can grant. Colon-form scopes are dropped
 * (token-scope validation rejects them); a `*` holder can grant them all.
 */
function grantableScopes(catalog: string[], callerPermissions: string[]): string[] {
  const dotForm = catalog.filter((scope) => scope.includes(".") && !scope.includes(":"));
  if (callerPermissions.includes(WILDCARD)) {
    return dotForm;
  }
  const granted = new Set(callerPermissions);
  return dotForm.filter((scope) => granted.has(scope));
}

function matchesBucket(bucket: PermissionBucket, scope: string): boolean {
  if (bucket === "invoke" && scope === AUTO_INJECTED_SCOPE) {
    return true;
  }
  return BUCKET_SUFFIXES[bucket].some((suffix) => scope.endsWith(suffix));
}

/**
 * Concrete grantable scopes for a bucket, drawn from the catalog and filtered to
 * the caller's permissions.
 */
export function bucketScopes(
  bucket: PermissionBucket,
  catalog: string[],
  callerPermissions: string[],
): string[] {
  return grantableScopes(catalog, callerPermissions).filter((scope) =>
    matchesBucket(bucket, scope),
  );
}

/** Buckets that expand to at least one grantable scope, in display order. */
export function availableBuckets(
  catalog: string[],
  callerPermissions: string[],
): PermissionBucket[] {
  return PERMISSION_BUCKET_ORDER.filter(
    (bucket) => bucketScopes(bucket, catalog, callerPermissions).length > 0,
  );
}

/**
 * Deduplicated union of concrete scopes across the selected buckets, excluding
 * the auto-injected `servers.use` (the backend adds it for MCP-method scopes).
 */
export function selectedScopes(
  selected: PermissionBucket[],
  catalog: string[],
  callerPermissions: string[],
): string[] {
  const scopes = new Set<string>();
  for (const bucket of PERMISSION_BUCKET_ORDER) {
    if (!selected.includes(bucket)) continue;
    for (const scope of bucketScopes(bucket, catalog, callerPermissions)) {
      if (scope !== AUTO_INJECTED_SCOPE) {
        scopes.add(scope);
      }
    }
  }
  return Array.from(scopes);
}
