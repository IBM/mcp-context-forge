import { safeGetElement } from "./utils";

export function openAddRuleModal() {
  safeGetElement("add-rule-modal", true).classList.remove("hidden");
  safeGetElement("rule-error", true).classList.add("hidden");
  [
    "rule-id",
    "rule-roles",
    "rule-actions",
    "rule-resource-types",
    "rule-resource-ids",
    "rule-reason",
  ].forEach((id) => {
    safeGetElement(id, true).value = "";
  });
}

export function closeAddRuleModal() {
  safeGetElement("add-rule-modal", true).classList.add("hidden");
}

export function splitTrim(str) {
  return str
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export async function submitAddRule() {
  const policyRootPath = window.ROOT_PATH || "";
  const ruleId = safeGetElement("rule-id", true).value.trim();
  const errEl = safeGetElement("rule-error", true);
  if (!ruleId) {
    errEl.textContent = "Rule ID is required.";
    errEl.classList.remove("hidden");
    return;
  }
  const rule = {
    id: ruleId,
    roles: splitTrim(safeGetElement("rule-roles", true).value) || ["*"],
    actions: splitTrim(safeGetElement("rule-actions", true).value) || ["*"],
    resource_types: splitTrim(
      safeGetElement("rule-resource-types", true).value
    ) || ["*"],
    resource_ids: splitTrim(
      safeGetElement("rule-resource-ids", true).value
    ) || ["*"],
    reason: safeGetElement("rule-reason", true).value.trim(),
    conditions: {},
  };
  try {
    const resp = await fetch(`${policyRootPath}/admin/policy/rules`, {
      method: "POST",
      credentials: "same-origin", // pragma: allowlist secret
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.detail || resp.statusText);
    }
    closeAddRuleModal();
    reloadPolicyPartial();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
  }
}

export async function deleteRule(ruleId) {
  const policyRootPath = window.ROOT_PATH || "";
  if (!confirm(`Delete rule "${ruleId}"?`)) return;
  try {
    const resp = await fetch(
      `${policyRootPath}/admin/policy/rules/${encodeURIComponent(ruleId)}`,
      {
        method: "DELETE",
        credentials: "same-origin", // pragma: allowlist secret
      }
    );
    if (!resp.ok) throw new Error("Failed to delete rule");
    reloadPolicyPartial();
  } catch (err) {
    alert("Error: " + err.message);
  }
}

export async function runPolicyTest() {
  const policyRootPath = window.ROOT_PATH || "";
  const email = safeGetElement("test-email", true).value.trim();
  const rolesRaw = safeGetElement("test-roles", true).value.trim();
  const action = safeGetElement("test-action", true).value.trim();
  const resourceType = safeGetElement("test-resource-type", true).value.trim();
  const resourceId = safeGetElement("test-resource-id", true).value.trim();
  const ip = safeGetElement("test-ip", true).value.trim() || "127.0.0.1";
  if (!email || !action || !resourceType || !resourceId) {
    alert("Please fill in Email, Action, Resource Type and Resource ID.");
    return;
  }
  const payload = {
    subject_email: email,
    subject_roles: rolesRaw
      ? rolesRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
      : [],
    action,
    resource_type: resourceType,
    resource_id: resourceId,
    ip,
  };
  try {
    const resp = await fetch(`${policyRootPath}/admin/policy/test`, {
      method: "POST",
      credentials: "same-origin", // pragma: allowlist secret
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    const resultEl = safeGetElement("policy-test-result", true);
    const verdictEl = safeGetElement("policy-test-verdict", true);
    resultEl.classList.remove(
      "hidden",
      "bg-green-50",
      "bg-red-50",
      "border-green-200",
      "border-red-200"
    );
    if (data.decision === "allow") {
      resultEl.classList.add("bg-green-50", "border-green-200");
      verdictEl.innerHTML = '<span class="text-green-700">✅ ALLOWED</span>';
    } else {
      resultEl.classList.add("bg-red-50", "border-red-200");
      verdictEl.innerHTML = '<span class="text-red-700">❌ DENIED</span>';
    }
    safeGetElement("policy-test-reason", true).textContent = data.reason || "";
    safeGetElement("policy-test-policies", true).textContent = data
      .matching_policies?.length
      ? "Matched: " + data.matching_policies.join(", ")
      : "No matching policies";
    safeGetElement("policy-test-timing", true).textContent =
      `${data.duration_ms}ms${data.cached ? " (cached)" : ""}`;
  } catch (err) {
    alert("Test error: " + err.message);
  }
}

export function reloadPolicyPartial() {
  const policyRootPath = window.ROOT_PATH || "";
  const panel = safeGetElement("policy-panel", true);
  if (panel) {
    fetch(`${policyRootPath}/admin/policy/partial`, {
      credentials: "same-origin", // pragma: allowlist secret
      headers: { Accept: "text/html" },
    })
      .then((r) => r.text())
      .then((html) => {
        panel.innerHTML = html;
      });
  }
}
