# ⚠️ OUTDATED DOCUMENTS NOTICE

## This directory contains OUTDATED design documents for Issue #5402

**Please use the V2 documents instead.**

---

## Current Documents (Use These) ✅

1. **ISSUE_5402_FINAL_DESIGN_V2.md** - Complete technical design (VirtualServer UUID approach)
2. **ISSUE_5402_APPROACH_COMPARISON_V2.md** - Detailed comparison of 3 approaches
3. **ISSUE_5402_SUMMARY_V2.md** - Executive summary (quick reference)
4. **ISSUE_5402_MIGRATION_GUIDE.md** - Migration from legacy to new approach

---

## Outdated Documents (Do Not Use) ❌

These documents are **SUPERSEDED** by the V2 documents above:

- ~~ISSUE_5402_FINAL_DESIGN.md~~ - Used domain-based approach (can't handle multi-system)
- ~~ISSUE_5402_PLUGIN_ARCHITECTURE.md~~ - Separate plugins approach (unnecessary complexity)
- ~~ISSUE_5402_APPROACH_COMPARISON.md~~ - Only compared 2 approaches (missing VirtualServer UUID)
- ~~ISSUE_5402_ANALYSIS_AND_PLAN.md~~ - Early analysis (predates architect's recommendation)
- ~~ISSUE_5402_ARCHITECTURE.md~~ - Generic architecture (not specific to chosen approach)
- ~~ISSUE_5402_SUMMARY.md~~ - Old summary (domain-based approach)
- ~~ISSUE_5402_VALIDATION.md~~ - Validation for old approach
- ~~ISSUE_5402_README.md~~ - General readme (not approach-specific)
- ~~ISSUE_5402_CHECKLIST.md~~ - Checklist for old approach
- ~~ISSUE_5402_GIT_WORKFLOW.md~~ - Git workflow (not approach-specific)
- ~~ISSUE_5402_AGENT_CHANGES.md~~ - Agent changes for old approach
- ~~ISSUE_5402_AGENT_CODE_LOCATIONS.md~~ - Code locations for old approach

---

## What Changed?

### Old Approach (Domains)
- Used domain extracted from gateway URL as lookup key
- ❌ **Could not handle multi-system virtual servers** (FATAL FLAW)
- Credentials stored at: `{user_id}/{domain}`
- Example: `user@example.com/github.com`

### New Approach (VirtualServer UUID) ✅
- Uses virtual server UUID (already in request path) as lookup key
- ✅ **Native multi-system support** via credential array with system field
- Credentials stored at: `{user_id}/{virtualServerUuid}`
- Example: `user@example.com/vs-dev-tools-abc123`

### Why the Change?

Based on **architect's recommendation** (madhav165's GitHub comment on Issue #5402):

> Credentials are already stored against virtual server UUIDs in destiny-services (`mcpServerCredential` table links `mcpServerUuid` → credential). Instead of tag matching or alias mapping, vault should store a **self-describing struct** at path `{user_id}/{virtualServerUuid}`

**Key benefits**:
1. ✅ Handles multi-system virtual servers (domain-based cannot)
2. ✅ Self-describing credentials (includes authType, headerName, system)
3. ✅ Aligns with existing destiny-services model
4. ✅ Uses infrastructure that already exists (UUIDs)
5. ✅ Better routing (system field matches to backend)

---

## Migration Guide

If you've already started implementation based on old documents:

1. **Stop work on domain-based approach**
2. **Read ISSUE_5402_FINAL_DESIGN_V2.md** (complete new design)
3. **Review ISSUE_5402_APPROACH_COMPARISON_V2.md** (understand why UUID is better)
4. **Follow ISSUE_5402_MIGRATION_GUIDE.md** (step-by-step migration)

---

## Questions?

- GitHub Issue: #5402
- Slack: #vault-migration
- Architect: madhav165
- Documentation: See V2 documents listed above

---

**Last Updated**: 2026-07-02  
**Reason**: Adopted architect-recommended VirtualServer UUID approach after GitHub comment analysis
