import fs from "fs";
import path from "path";

import { HelpDatabase } from "../helpDatabase.combined.js";

const UI_DIR = "mcpgateway/admin_ui";

/* -----------------------------
   NORMALIZE (with lowercase)
------------------------------ */

function normalize(id) {
  return id
    .toLowerCase()
    .replace(/^#/, "")
    .replace(/^\./, "")
    .replace(/\$\{.*?\}/g, "*")
    .replace(/["'`]/g, "")
    .trim();
}

/* -----------------------------
   EXTRACT UI IDS FROM FILES
------------------------------ */

function extractIds(content) {
  const ids = new Set();

  const patterns = [
    /safeGetElement\(["'`]([^"'`]+)["'`]\)/g,
    /getElementById\(["'`]([^"'`]+)["'`]\)/g,
    /querySelector\(["'`]#([^"'` ]+)["'`]\)/g,
    /\bid=["'`]([^"'`]+)["'`]/g,
  ];

  for (const p of patterns) {
    for (const m of content.matchAll(p)) {
      const id = normalize(m[1]);
      if (id) ids.add(id);
    }
  }

  return ids;
}

export function scan(dir) {
  const ids = new Set();

  for (const f of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, f.name);

    if (f.isDirectory()) {
      scan(full).forEach(x => ids.add(x));
      continue;
    }

    if (!f.name.endsWith(".js") && !f.name.endsWith(".ts")) continue;

    const content = fs.readFileSync(full, "utf-8");
    extractIds(content).forEach(x => ids.add(x));
  }

  return ids;
}

/* -----------------------------
   CLASSIFY UI
------------------------------ */

function classifyUI(ui) {
  // SYSTEM UI
  if (
    ui.startsWith("selected") ||
    ui.startsWith("search") ||
    ui.includes("table-body") ||
    ui.includes("pagination") ||
    ui.includes("toolbody") ||
    ui.includes("llm-model") ||
    ui.includes("tokens-search")
  ) {
    return "system";
  }

  // INFRA UI
  if (
    ui.startsWith("export-") ||
    ui.startsWith("import-") ||
    ui.startsWith("bulk-") ||
    ui.startsWith("metrics") ||
    ui.includes("panel") ||
    ui.includes("table") ||
    ui.includes("progress")
  ) {
    return "infra";
  }

  // CORE UI (default)
  return "core";
}

/* -----------------------------
   GENERATE UI INTENTS
------------------------------ */

function getIntents(ui) {
  const intents = [];
  const parts = ui.split("-");

  const domain = parts[0] || "misc";
  const feature = parts[1] || "general";

  // Base intent
  intents.push(`${domain}.${feature}`);

  // Structural intents (add as needed)
  if (ui.includes("server")) intents.push("server.core");
  if (ui.includes("tool")) intents.push("tool.core");
  if (ui.includes("gateway")) intents.push("gateway.core");
  if (ui.includes("auth-basic")) intents.push("auth.basic");
  if (ui.includes("auth-bearer")) intents.push("auth.bearer");
  if (ui.includes("auth-headers")) intents.push("auth.headers");
  if (ui.includes("auth-oauth")) intents.push("auth.oauth");
  if (ui.includes("auth")) intents.push("auth.core");
  if (ui.includes("a2a-test")) intents.push("a2a.test");
  if (ui.includes("a2a-agent")) intents.push("a2a.agent");
  if (ui.includes("a2a")) intents.push("a2a.core");
  if (ui.startsWith("edit-")) intents.push("edit.base");

  // Fallback wildcard domenin
  intents.push(domain);

  // Remove duplicates
  return [...new Set(intents)];
}

/* -----------------------------
   BUILD HELP INDEX WITH EXTENDED INTENTIONS
------------------------------ */

function buildHelpIndex() {
  const index = [];

  for (const key of Object.keys(HelpDatabase)) {
    const norm = normalize(key);
    const parts = norm.split(".");

    // Build more granular intents
    const intents = [
      norm,
      parts[0], 
      parts.slice(0, 2).join("."),
    ];
    if(parts.length > 2) {
      intents.push(parts.slice(0, 3).join("."));
    }

    index.push({ key: norm, intents });
  }

  return index;
}

/* -----------------------------
  SEMANTIC SCORE
------------------------------ */

function scoreUI(ui, helpIndex) {
  const uiIntents = getIntents(ui);
  let best = 0;

  for (const help of helpIndex) {
    for (const hi of help.intents) {
      for (const uiI of uiIntents) {
        if (uiI === hi) return 1.0; // potrivire exactă

        if (uiI.startsWith(hi) || hi.startsWith(uiI)) {
          best = Math.max(best, 0.85); // prefix matching
        }

        const uiDomain = uiI.split(".")[0];
        const hiDomain = hi.split(".")[0];

        if (uiDomain === hiDomain) {
          best = Math.max(best, 0.6); // domeniu comun
        }

        // Match cuvânt-cheie simplu (nu fuzzy excesiv)
        const uiWords = ui.split("-");
        const hiWords = hi.split(".");

        const overlap = uiWords.some(w =>
          hiWords.some(h => w.includes(h) || h.includes(w))
        );

        if (overlap) {
          best = Math.max(best, 0.5);
        }
      }
    }
  }

  return best;
}

/* -----------------------------
   RUN PRINCIPAL
------------------------------ */

function run() {
  const uiFields = scan(UI_DIR);

  const coreUI = [];
  const infraUI = [];
  const systemUI = [];

  const coveredCore = [];
  const missingCore = [];
  const lowConfidence = [];
  const missingInfra = [];

  for (const ui of uiFields) {
    const type = classifyUI(ui);
    if (type === "system") systemUI.push(ui);
    else if (type === "infra") infraUI.push(ui);
    else coreUI.push(ui);
  }

  const helpIndex = buildHelpIndex();

  for (const ui of coreUI) {
    const score = scoreUI(ui, helpIndex);
    if (score >= 0.75) {
      coveredCore.push(ui);
    } else {
      missingCore.push(ui);
      lowConfidence.push(ui);
    }
  }

  for (const ui of infraUI) {
    missingInfra.push(ui);
  }

  const coverage = coreUI.length ? (coveredCore.length / coreUI.length) * 100 : 0;

  console.log("\n📊 UI STRATIFICATION\n");
  console.log(`🟢 CORE (needs help): ${coreUI.length}`);
  console.log(`🟡 INFRA (semi-help): ${infraUI.length}`);
  console.log(`🔴 SYSTEM (no help): ${systemUI.length}`);

  console.log("\n🟢 COVERED CORE:");
  coveredCore.slice(0, 100).forEach(c => console.log(" ✔", c));

  console.log("\n🟡 LOW CONFIDENCE CORE:");
  lowConfidence.slice(0, 100).forEach(c => console.log(" -", c));

  console.log("\n🔴 MISSING CORE:");
  missingCore.slice(0, 100).forEach(c => console.log(" -", c));

  console.log("\n🟠 MISSING INFRA:");
  missingInfra.slice(0, 100).forEach(c => console.log(" -", c));

  console.log(`\n📊 REAL COVERAGE (CORE ONLY): ${coverage.toFixed(1)}%\n`);
}

run();
