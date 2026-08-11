import { getCookie } from "./utils.js";
import { escapeHtml } from "./security.js";

const rootPath = () => window.ROOT_PATH || "";

const byId = (id) => document.getElementById(id);

const errorDetail = (body, fallback) => {
  if (typeof body?.detail === "string") return body.detail;
  if (Array.isArray(body?.detail)) {
    return body.detail
      .map((item) => item.msg || JSON.stringify(item))
      .join("; ");
  }
  return fallback;
};

const requestJson = async (path, options = {}) => {
  const headers = new Headers(options.headers || {});
  const csrfToken = getCookie("mcpgateway_csrf_token");
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`${rootPath()}${path}`, {
    credentials: "same-origin", // pragma: allowlist secret
    ...options,
    headers,
  });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorDetail(body, `Request failed (${response.status})`));
  }
  return body;
};

const button = (
  label,
  action,
  className = "bg-indigo-100 text-indigo-800 hover:bg-indigo-200"
) => {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  element.className = `px-3 py-1 text-sm font-medium rounded-md ${className}`;
  element.addEventListener("click", async () => {
    element.disabled = true;
    try {
      await action();
    } catch (error) {
      setText("sql-source-status", error.message);
    } finally {
      element.disabled = false;
    }
  });
  return element;
};

const labeledCheckbox = (label, checked) => {
  const wrapper = document.createElement("label");
  wrapper.className =
    "inline-flex items-center gap-1 text-xs text-gray-700 dark:text-gray-300";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  wrapper.append(input, document.createTextNode(label));
  return { wrapper, input };
};

const setText = (id, value) => {
  const element = byId(id);
  if (element) element.textContent = value;
};

const renderSources = async () => {
  const container = byId("sql-source-list");
  if (!container) return;
  container.replaceChildren();
  try {
    const sources = await requestJson("/admin/sql/sources");
    sources.forEach((source) => {
      const card = document.createElement("div");
      card.className =
        "border border-gray-200 dark:border-gray-700 rounded-md p-3";
      const title = document.createElement("div");
      title.className = "font-medium text-gray-900 dark:text-gray-200";
      title.textContent = source.name;
      const detail = document.createElement("div");
      detail.className = "text-xs text-gray-600 dark:text-gray-400";
      detail.textContent = `${source.dialect} · ${source.masked_url} · ${source.reachable ? "reachable" : "not tested/unreachable"}`;
      const actions = document.createElement("div");
      actions.className = "mt-2 flex gap-2";
      actions.append(
        button("Test", async () => {
          const result = await requestJson(
            `/admin/sql/sources/${source.id}/test`,
            { method: "POST" }
          );
          setText(
            "sql-source-status",
            result.reachable
              ? "Connection succeeded"
              : `Connection failed: ${result.error || "unknown error"}`
          );
          await renderSources();
        }),
        button("Discover", async () => {
          const tables = await requestJson(
            `/admin/sql/sources/${source.id}/discover`,
            { method: "POST" }
          );
          setText(
            "sql-source-status",
            `Discovered ${tables.length} table/view records`
          );
          await loadSqlCatalog();
        })
      );
      card.append(title, detail, actions);
      container.append(card);
    });
    if (!sources.length)
      container.textContent = "No SQL data sources registered.";
  } catch (error) {
    container.textContent = error.message;
  }
};

const renderTables = async () => {
  const container = byId("sql-table-list");
  if (!container) return;
  container.replaceChildren();
  try {
    const tables = await requestJson("/admin/sql/tables");
    tables.forEach((table) => {
      const card = document.createElement("div");
      card.className =
        "border border-gray-200 dark:border-gray-700 rounded-md p-3";
      const heading = document.createElement("div");
      heading.className = "font-medium text-gray-900 dark:text-gray-200";
      heading.textContent = `${table.schema_name || "default"}.${table.table_name} (${table.object_type})${table.stale ? " · stale" : ""}`;
      const policy = document.createElement("div");
      policy.className = "mt-2 flex flex-wrap gap-3";
      const exposed = labeledCheckbox("Exposed", table.exposed);
      const query = labeledCheckbox("Query", table.allow_query);
      const insert = labeledCheckbox("Insert", table.allow_insert);
      const update = labeledCheckbox("Update", table.allow_update);
      const remove = labeledCheckbox("Delete", table.allow_delete);
      if (table.object_type === "view") {
        insert.input.disabled = true;
        update.input.disabled = true;
        remove.input.disabled = true;
      }
      policy.append(
        exposed.wrapper,
        query.wrapper,
        insert.wrapper,
        update.wrapper,
        remove.wrapper
      );

      const scope = document.createElement("div");
      scope.className = "mt-2 flex flex-wrap gap-2";
      const team = document.createElement("input");
      team.placeholder = "Team UUID (platform admin)";
      team.value = table.team_id || "";
      team.className =
        "px-2 py-1 text-xs rounded border dark:bg-gray-900 dark:border-gray-700 dark:text-gray-200";
      const visibility = document.createElement("select");
      visibility.className =
        "px-2 py-1 text-xs rounded border dark:bg-gray-900 dark:border-gray-700 dark:text-gray-200";
      ["private", "team", "public"].forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = table.visibility === value;
        visibility.append(option);
      });
      scope.append(team, visibility);
      scope.append(
        button("Save policy", async () => {
          await requestJson(`/admin/sql/tables/${table.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              exposed: exposed.input.checked,
              allow_query: query.input.checked,
              allow_insert: insert.input.checked,
              allow_update: update.input.checked,
              allow_delete: remove.input.checked,
              team_id: team.value || null,
              visibility: visibility.value,
            }),
          });
          await loadSqlCatalog();
        })
      );
      card.append(heading, policy, scope);
      container.append(card);
    });
    if (!tables.length)
      container.textContent =
        "No tables are visible. Discover a source or select an assigned team.";
  } catch (error) {
    container.textContent = error.message;
  }
};

const renderRelations = async () => {
  const container = byId("sql-relation-list");
  if (!container) return;
  container.replaceChildren();
  try {
    const relations = await requestJson("/admin/sql/relations");
    relations.forEach((relation) => {
      const row = document.createElement("div");
      row.className =
        "flex items-center justify-between border border-gray-200 dark:border-gray-700 rounded-md p-3";
      const name = document.createElement("span");
      name.className = "text-sm text-gray-800 dark:text-gray-200";
      name.textContent = `${relation.name}: ${relation.local_columns.join(", ")} → ${relation.remote_columns.join(", ")}${relation.stale ? " · stale" : ""}`;
      row.append(
        name,
        button(
          relation.enabled ? "Disable include" : "Enable include",
          async () => {
            await requestJson(`/admin/sql/relations/${relation.id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ enabled: !relation.enabled }),
            });
            await renderRelations();
          }
        )
      );
      container.append(row);
    });
    if (!relations.length)
      container.textContent = "No visible foreign-key relations.";
  } catch (error) {
    container.textContent = error.message;
  }
};

const loadSqlCatalog = async () => {
  await Promise.all([renderSources(), renderTables(), renderRelations()]);
};

const setupSqlPanel = () => {
  const panel = byId("sql-data-panel");
  if (!panel) return;
  byId("sql-refresh-catalog")?.addEventListener("click", loadSqlCatalog);
  byId("sql-source-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = byId("sql-source-name").value.trim();
    const connectionUrl = byId("sql-source-url").value;
    try {
      await requestJson("/admin/sql/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, connection_url: connectionUrl }),
      });
      event.target.reset();
      setText(
        "sql-source-status",
        "Source created. Test and discover it before exposure."
      );
      await loadSqlCatalog();
    } catch (error) {
      setText("sql-source-status", error.message);
    }
  });
  loadSqlCatalog();
};

let debugCatalog = [];

const selectedDebugTool = () =>
  debugCatalog.find((tool) => tool.id === byId("api-debug-tool")?.value);

const resolveSchema = (schema, rootSchema) => {
  const reference = schema?.$ref;
  if (!reference?.startsWith("#/$defs/")) return schema || {};
  const name = decodeURIComponent(
    reference
      .slice("#/$defs/".length)
      .replaceAll("~1", "/")
      .replaceAll("~0", "~")
  );
  return rootSchema?.$defs?.[name] || schema;
};

const createSchemaControl = (
  name,
  schema,
  path,
  required,
  rootSchema,
  example
) => {
  const resolved = resolveSchema(schema, rootSchema);
  const wrapper = document.createElement("div");
  wrapper.className = "space-y-1";
  const label = document.createElement("label");
  label.className =
    "block text-xs font-medium text-gray-700 dark:text-gray-300";
  label.textContent = `${name}${required ? " *" : ""}`;
  wrapper.append(label);

  const properties = resolved.properties || {};
  if (
    (resolved.type === "object" || Object.keys(properties).length) &&
    Object.keys(properties).length
  ) {
    const fieldset = document.createElement("div");
    fieldset.className =
      "ml-2 pl-3 border-l border-gray-300 dark:border-gray-600 space-y-2";
    const requiredFields = new Set(resolved.required || []);
    Object.entries(properties).forEach(([childName, childSchema]) => {
      fieldset.append(
        createSchemaControl(
          childName,
          childSchema,
          [...path, childName],
          requiredFields.has(childName),
          rootSchema,
          example?.[childName]
        )
      );
    });
    wrapper.append(fieldset);
    return wrapper;
  }

  let control;
  let kind = "string";
  if (Array.isArray(resolved.enum)) {
    control = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "— unset —";
    control.append(empty);
    resolved.enum.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      control.append(option);
    });
  } else if (resolved.type === "boolean") {
    control = document.createElement("select");
    [
      ["", "— unset —"],
      ["true", "true"],
      ["false", "false"],
    ].forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      control.append(option);
    });
    kind = "boolean";
  } else if (resolved.type === "integer" || resolved.type === "number") {
    control = document.createElement("input");
    control.type = "number";
    control.step = resolved.type === "integer" ? "1" : "any";
    if (resolved.minimum !== undefined) control.min = String(resolved.minimum);
    if (resolved.maximum !== undefined) control.max = String(resolved.maximum);
    kind = resolved.type;
  } else if (
    resolved.type === "array" ||
    resolved.type === "object" ||
    resolved.additionalProperties
  ) {
    control = document.createElement("textarea");
    control.rows = 2;
    control.placeholder = resolved.type === "array" ? "[]" : "{}";
    kind = "json";
  } else {
    control = document.createElement("input");
    control.type =
      resolved.format === "date"
        ? "date"
        : resolved.format === "time"
          ? "time"
          : resolved.format === "date-time"
            ? "datetime-local"
            : "text";
  }
  control.className =
    "px-2 py-1 w-full text-xs rounded border dark:bg-gray-900 dark:border-gray-700 dark:text-gray-200";
  control.dataset.debugPath = JSON.stringify(path);
  control.dataset.debugKind = kind;
  if (example !== undefined && example !== null)
    control.value = kind === "json" ? JSON.stringify(example) : String(example);
  wrapper.append(control);
  return wrapper;
};

const renderDebugFields = (tool) => {
  const container = byId("api-debug-generated-fields");
  if (!container) return;
  container.replaceChildren();
  const schema = tool?.input_schema || {};
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  const example = Array.isArray(schema.examples)
    ? schema.examples[0] || {}
    : {};
  Object.entries(properties).forEach(([name, propertySchema]) => {
    container.append(
      createSchemaControl(
        name,
        propertySchema,
        [name],
        required.has(name),
        schema,
        example[name]
      )
    );
  });
  if (!Object.keys(properties).length)
    container.textContent =
      "This tool does not declare editable input properties.";
};

const generatedArguments = () => {
  const result = {};
  document
    .querySelectorAll("#api-debug-generated-fields [data-debug-path]")
    .forEach((control) => {
      if (control.value === "") return;
      const path = JSON.parse(control.dataset.debugPath);
      let value = control.value;
      if (control.dataset.debugKind === "json") value = JSON.parse(value);
      if (control.dataset.debugKind === "integer")
        value = Number.parseInt(value, 10);
      if (control.dataset.debugKind === "number")
        value = Number.parseFloat(value);
      if (control.dataset.debugKind === "boolean") value = value === "true";
      let target = result;
      path.slice(0, -1).forEach((part) => {
        target[part] ||= {};
        target = target[part];
      });
      target[path.at(-1)] = value;
    });
  return result;
};

const updateDebugSchema = () => {
  const tool = selectedDebugTool();
  setText(
    "api-debug-schema",
    tool ? JSON.stringify(tool.input_schema || {}, null, 2) : ""
  );
  renderDebugFields(tool);
};

const parseObject = (id, label) => {
  const raw = byId(id)?.value || "{}";
  const value = JSON.parse(raw);
  if (!value || Array.isArray(value) || typeof value !== "object")
    throw new Error(`${label} must be a JSON object`);
  return value;
};

const debugPayload = () => ({
  tool_id: byId("api-debug-tool").value,
  arguments: parseObject("api-debug-arguments", "Arguments"),
  headers: parseObject("api-debug-headers", "Headers"),
  metadata: parseObject("api-debug-metadata", "Metadata"),
  deadline_seconds: Number(byId("api-debug-deadline").value || 30),
});

const invokeDebug = async () => {
  setText("api-debug-output", "Invoking…");
  try {
    const result = await requestJson("/admin/debug/invoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(debugPayload()),
    });
    setText(
      "api-debug-meta",
      `${result.protocol} · ${result.status_code} · ${result.duration_ms.toFixed(2)} ms · trace ${result.trace_id || "n/a"}`
    );
    setText("api-debug-output", JSON.stringify(result.result, null, 2));
  } catch (error) {
    setText("api-debug-meta", "Invocation failed");
    setText("api-debug-output", error.message);
  }
};

const streamDebug = async () => {
  setText("api-debug-output", "Connecting…\n");
  try {
    const headers = new Headers({ "Content-Type": "application/json" });
    const csrfToken = getCookie("mcpgateway_csrf_token");
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
    const response = await fetch(`${rootPath()}/admin/debug/stream`, {
      method: "POST",
      credentials: "same-origin", // pragma: allowlist secret
      headers,
      body: JSON.stringify(debugPayload()),
    });
    if (!response.ok || !response.body) {
      const body = await response.json().catch(() => ({}));
      throw new Error(errorDetail(body, `Stream failed (${response.status})`));
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let output = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);
        if (!rawEvent) continue;
        let eventType = "message";
        const dataLines = [];
        for (const line of rawEvent.split("\n")) {
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        const prefix = eventType !== "message" ? `[${eventType}] ` : "";
        output += prefix + (dataLines.join("") || "") + "\n";
      }
      setText("api-debug-output", output);
    }
  } catch (error) {
    setText("api-debug-output", error.message);
  }
};

const loadDebugHistory = async () => {
  const container = byId("api-debug-history-list");
  if (!container) return;
  try {
    const items = await requestJson("/admin/debug/history");
    container.replaceChildren();
    if (!items.length) {
      container.textContent = "No debug history for your account.";
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "flex items-center justify-between text-xs p-2 rounded bg-gray-50 dark:bg-gray-800";
      const left = document.createElement("span");
      left.className = "text-gray-700 dark:text-gray-300";
      left.textContent = `[${item.protocol}] ${item.status_code || "?"} \u00b7 ${item.duration_ms?.toFixed(1) || "?"} ms \u00b7 ${item.created_at?.slice(0, 19) || ""}`;
      const replayBtn = document.createElement("button");
      replayBtn.type = "button";
      replayBtn.className = "px-2 py-0.5 text-xs rounded bg-indigo-100 text-indigo-800 hover:bg-indigo-200";
      replayBtn.textContent = "Replay";
      replayBtn.addEventListener("click", async () => {
        if (item.tool_id) {
          byId("api-debug-tool").value = item.tool_id;
          updateDebugSchema();
        }
        try {
          const parsed = item.request_preview?.arguments;
          if (parsed) byId("api-debug-arguments").value = JSON.stringify(parsed, null, 2);
        } catch (_) {}
        await invokeDebug();
      });
      row.append(left, replayBtn);
      container.append(row);
    });
  } catch (error) {
    container.textContent = error.message;
  }
};

const setupDebugPanel = async () => {
  if (!byId("api-debug-panel")) return;
  try {
    const catalog = await requestJson("/admin/debug/catalog");
    debugCatalog = catalog.data || [];
    const select = byId("api-debug-tool");
    select.replaceChildren();
    debugCatalog.forEach((tool) => {
      const option = document.createElement("option");
      option.value = tool.id;
      option.textContent = `[${tool.protocol}] ${tool.name}`;
      select.append(option);
    });
    select.addEventListener("change", updateDebugSchema);
    updateDebugSchema();
  } catch (error) {
    setText("api-debug-output", error.message);
  }
  byId("api-debug-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await invokeDebug();
  });
  byId("api-debug-repeat")?.addEventListener("click", invokeDebug);
  byId("api-debug-load-history")?.addEventListener("click", loadDebugHistory);
  loadDebugHistory();
  byId("api-debug-stream")?.addEventListener("click", streamDebug);
  byId("api-debug-apply-generated")?.addEventListener("click", () => {
    try {
      byId("api-debug-arguments").value = JSON.stringify(
        generatedArguments(),
        null,
        2
      );
      setText(
        "api-debug-output",
        "Generated parameter values copied to Arguments JSON."
      );
    } catch (error) {
      setText(
        "api-debug-output",
        `Generated parameter value is invalid: ${error.message}`
      );
    }
  });
  try {
    const stats = await requestJson("/admin/debug/stats");
    setText("api-debug-stats", JSON.stringify(stats, null, 2));
  } catch (error) {
    setText("api-debug-stats", error.message);
  }
};

const showGrpcSyncPreview = async (box) => {
  const serviceId = box.dataset.serviceId;
  const candidateId = box.dataset.candidateId;
  const panel = box.querySelector(".grpc-sync-preview-panel");
  const body = box.querySelector(".grpc-sync-preview-body");
  if (!serviceId || !candidateId || !panel || !body) return;
  const toggle = box.querySelector(".grpc-sync-preview-toggle");
  if (toggle) toggle.classList.remove("hidden");
  panel.classList.remove("hidden");
  body.textContent = "Loading…";
  try {
    const preview = await requestJson(
      `/admin/grpc/${serviceId}/schemas/${candidateId}/preview`
    );
    const rows = [
      ["Added", "added_tools", "bg-green-100 text-green-800"],
      ["Modified", "modified_tools", "bg-yellow-100 text-yellow-800"],
      ["Disabled", "disabled_tools", "bg-red-100 text-red-800"],
      ["Re-approval", "methods_needing_reapproval", "bg-orange-100 text-orange-800"],
    ];
    const listHtml = (items, chipClass) =>
      items.length
        ? `<ul class="space-y-0.5">${items
            .map((item) => `<li><span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${chipClass}">${escapeHtml(item)}</span></li>`)
            .join("")}</ul>`
        : '<p class="text-gray-500 dark:text-gray-400">None</p>';
    const rendered = rows
      .map(
        ([label, key, chip]) =>
          `<div>
            <div class="flex items-center gap-2">
              <span class="font-medium">${label}</span>
              <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">${(preview[key] || []).length}</span>
            </div>
            ${listHtml(preview[key] || [], chip)}
          </div>`
      )
      .join("");
    const warning = preview.warning
      ? `<p class="text-amber-700 dark:text-amber-400 mt-1">⚠️ ${escapeHtml(preview.warning)}</p>`
      : "";
    body.innerHTML = `<div class="space-y-2">${rendered}${warning}</div>`;
  } catch (error) {
    body.textContent = `Preview failed: ${error.message}`;
  }
};

const setupGrpcOperations = () => {
  document.querySelectorAll(".grpc-schema-upload").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = form.querySelector('button[type="submit"]');
      const original = submit.textContent;
      const activateCheckbox = form.querySelector('input[name="activate"]');
      // A bare unchecked checkbox sends nothing, and FastAPI's Form(default=True)
      // would treat the candidate as an activation. Send activate=false explicitly.
      const activate = activateCheckbox?.checked ?? true;
      submit.disabled = true;
      submit.textContent = "Importing…";
      try {
        const fd = new FormData(form);
        if (!activate) fd.set("activate", "false");
        const artifact = await requestJson(
          `/admin/grpc/${form.dataset.serviceId}/schemas/import`,
          {
            method: "POST",
            body: fd,
          }
        );
        submit.textContent = `Imported v${artifact.version}`;
        if (artifact && !artifact.is_active && artifact.id) {
          window.setTimeout(() => {
            const previewBox = form.parentElement.querySelector(".grpc-sync-preview");
            if (previewBox) {
              previewBox.dataset.candidateId = artifact.id;
              const toggle = previewBox.querySelector(".grpc-sync-preview-toggle");
              if (toggle) toggle.classList.remove("hidden");
              showGrpcSyncPreview(previewBox);
            }
          }, 200);
        } else {
          window.setTimeout(() => window.location.reload(), 500);
        }
      } catch (error) {
        submit.textContent = error.message;
        window.setTimeout(() => {
          submit.textContent = original;
          submit.disabled = false;
        }, 3000);
      }
    });
  });
  document.querySelectorAll(".grpc-sync-preview").forEach((box) => {
    const toggle = box.querySelector(".grpc-sync-preview-toggle");
    const close = box.querySelector(".grpc-sync-preview-close");
    const panel = box.querySelector(".grpc-sync-preview-panel");
    if (toggle) {
      toggle.addEventListener("click", () => {
        if (panel) {
          if (panel.classList.contains("hidden")) {
            showGrpcSyncPreview(box);
          } else {
            panel.classList.add("hidden");
          }
        }
      });
    }
    if (close) {
      close.addEventListener("click", () => {
        if (panel) panel.classList.add("hidden");
      });
    }
  });
  document.querySelectorAll(".grpc-health-check").forEach((control) => {
    control.addEventListener("click", async () => {
      control.disabled = true;
      try {
        const result = await requestJson(
          `/admin/grpc/${control.dataset.serviceId}/health`,
          { method: "POST" }
        );
        control.textContent = `${result.status} · ${Math.round(result.latency_ms || 0)} ms`;
      } catch (error) {
        control.textContent = error.message;
      } finally {
        window.setTimeout(() => {
          control.disabled = false;
        }, 1000);
      }
    });
  });
  document
    .querySelectorAll(".grpc-metrics-summary")
    .forEach(async (container) => {
      try {
        const metrics = await requestJson(
          `/admin/grpc/${container.dataset.serviceId}/metrics?hours=24`
        );
        container.textContent = JSON.stringify(
          {
            calls: metrics.total_calls,
            error_rate: metrics.error_rate,
            p50: metrics.p50,
            p95: metrics.p95,
            p99: metrics.p99,
            status_distribution: metrics.status_distribution,
            trend: metrics.trend,
          },
          null,
          2
        );
      } catch (error) {
        container.textContent = error.message;
      }
    });
};

export const initializeDataOperations = function () {
  setupSqlPanel();
  setupDebugPanel();
  setupGrpcOperations();
};
