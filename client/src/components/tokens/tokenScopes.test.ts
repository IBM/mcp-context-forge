import { describe, it, expect } from "vitest";

import { availableBuckets, bucketScopes, selectedScopes } from "./tokenScopes";

// A representative slice of the backend permission catalog
// (GET /rbac/permissions/available -> all_permissions), including colon-form and
// non-verb scopes that must be filtered out.
const CATALOG = [
  "a2a.invoke",
  "a2a.read",
  "admin.overview",
  "logs:read",
  "prompts.execute",
  "prompts.read",
  "resources.read",
  "resources.share",
  "servers.manage",
  "servers.read",
  "servers.use",
  "tools.create",
  "tools.execute",
  "tools.read",
  "users.read",
];

// A non-admin caller that holds only a subset of the catalog.
const CALLER = [
  "tools.read",
  "resources.read",
  "tools.execute",
  "prompts.execute",
  "servers.use",
  "tools.create",
];

describe("bucketScopes", () => {
  it("expands a bucket to the caller's matching catalog scopes, in catalog order", () => {
    expect(bucketScopes("read", CATALOG, CALLER)).toEqual(["resources.read", "tools.read"]);
    expect(bucketScopes("create", CATALOG, CALLER)).toEqual(["tools.create"]);
  });

  it("includes servers.use under invoke when the caller holds it", () => {
    expect(bucketScopes("invoke", CATALOG, CALLER)).toEqual([
      "prompts.execute",
      "servers.use",
      "tools.execute",
    ]);
  });

  it("grants every dot-form catalog scope in a bucket to a wildcard caller", () => {
    expect(bucketScopes("read", CATALOG, ["*"])).toEqual([
      "a2a.read",
      "prompts.read",
      "resources.read",
      "servers.read",
      "tools.read",
      "users.read",
    ]);
  });

  it("never surfaces colon-form or non-verb scopes", () => {
    const all = [
      ...bucketScopes("read", CATALOG, ["*"]),
      ...bucketScopes("invoke", CATALOG, ["*"]),
      ...bucketScopes("create", CATALOG, ["*"]),
    ];
    expect(all).not.toContain("logs:read");
    expect(all).not.toContain("admin.overview");
    expect(all).not.toContain("resources.share");
    expect(all).not.toContain("servers.manage");
  });

  it("returns nothing for a verb the caller cannot grant", () => {
    expect(bucketScopes("delete", CATALOG, CALLER)).toEqual([]);
  });
});

describe("availableBuckets", () => {
  it("lists only buckets with at least one grantable scope, in display order", () => {
    expect(availableBuckets(CATALOG, CALLER)).toEqual(["read", "invoke", "create"]);
  });

  it("is empty when the caller can grant nothing from the catalog", () => {
    expect(availableBuckets(CATALOG, [])).toEqual([]);
  });
});

describe("selectedScopes", () => {
  it("unions the concrete scopes across selected buckets, deduped", () => {
    expect(selectedScopes(["read", "create"], CATALOG, CALLER)).toEqual([
      "resources.read",
      "tools.read",
      "tools.create",
    ]);
  });

  it("excludes the auto-injected servers.use from the submitted set", () => {
    expect(selectedScopes(["invoke"], CATALOG, CALLER)).toEqual([
      "prompts.execute",
      "tools.execute",
    ]);
  });

  it("ignores buckets the caller cannot grant", () => {
    expect(selectedScopes(["delete"], CATALOG, CALLER)).toEqual([]);
  });
});
