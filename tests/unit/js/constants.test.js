/**
 * Unit tests for constants.js module
 * Tests: Exported constants and configurations
 */

import { describe, test, expect } from "vitest";
import {
  MASKED_AUTH_VALUE,
  HEADER_NAME_REGEX,
  MAX_HEADER_VALUE_LENGTH,
  MAX_NAME_LENGTH,
  PERFORMANCE_HISTORY_HOURS,
  PERFORMANCE_AGGREGATION_OPTIONS,
  DEFAULT_TEAMS_PER_PAGE,
  PANEL_SEARCH_CONFIG,
  GLOBAL_SEARCH_ENTITY_CONFIG,
} from "../../../mcpgateway/admin_ui/constants.js";

describe("constants", () => {
  test("MASKED_AUTH_VALUE is defined", () => {
    expect(MASKED_AUTH_VALUE).toBe("*****");
  });

  test("HEADER_NAME_REGEX validates header names", () => {
    expect(HEADER_NAME_REGEX.test("Content-Type")).toBe(true);
    expect(HEADER_NAME_REGEX.test("X-Custom-Header")).toBe(true);
    expect(HEADER_NAME_REGEX.test("Authorization")).toBe(true);
    expect(HEADER_NAME_REGEX.test("Invalid Header!")).toBe(false);
    expect(HEADER_NAME_REGEX.test("Header With Spaces")).toBe(false);
  });

  test("MAX_HEADER_VALUE_LENGTH is defined", () => {
    expect(MAX_HEADER_VALUE_LENGTH).toBe(4096);
  });

  test("MAX_NAME_LENGTH is defined", () => {
    expect(MAX_NAME_LENGTH).toBe(255);
  });

  test("PERFORMANCE_HISTORY_HOURS is defined", () => {
    expect(PERFORMANCE_HISTORY_HOURS).toBe(24);
  });

  test("PERFORMANCE_AGGREGATION_OPTIONS contains expected options", () => {
    expect(PERFORMANCE_AGGREGATION_OPTIONS).toHaveProperty("5m");
    expect(PERFORMANCE_AGGREGATION_OPTIONS).toHaveProperty("24h");
    expect(PERFORMANCE_AGGREGATION_OPTIONS["5m"]).toEqual({
      label: "5-minute aggregation",
      query: "5m",
    });
    expect(PERFORMANCE_AGGREGATION_OPTIONS["24h"]).toEqual({
      label: "24-hour aggregation",
      query: "24h",
    });
  });

  test("DEFAULT_TEAMS_PER_PAGE is defined", () => {
    expect(DEFAULT_TEAMS_PER_PAGE).toBe(10);
  });

  test("PANEL_SEARCH_CONFIG contains all expected panels", () => {
    const expectedPanels = ["catalog", "tools", "resources", "prompts", "gateways", "a2a-agents"];
    expectedPanels.forEach((panel) => {
      expect(PANEL_SEARCH_CONFIG).toHaveProperty(panel);
    });
  });

  test("PANEL_SEARCH_CONFIG catalog has correct structure", () => {
    const catalog = PANEL_SEARCH_CONFIG.catalog;
    expect(catalog.tableName).toBe("servers");
    expect(catalog.partialPath).toBe("servers/partial");
    expect(catalog.targetSelector).toBe("#servers-table");
    expect(catalog.indicatorSelector).toBe("#servers-loading");
    expect(catalog.searchInputId).toBe("servers-search-input");
    expect(catalog.tagInputId).toBe("servers-tag-filter");
    expect(catalog.inactiveCheckboxId).toBe("show-inactive-servers");
    expect(catalog.defaultPerPage).toBe(50);
  });

  test("PANEL_SEARCH_CONFIG tools has correct structure", () => {
    const tools = PANEL_SEARCH_CONFIG.tools;
    expect(tools.tableName).toBe("tools");
    expect(tools.partialPath).toBe("tools/partial");
    expect(tools.targetSelector).toBe("#tools-table");
    expect(tools.defaultPerPage).toBe(50);
  });

  test("PANEL_SEARCH_CONFIG resources has correct structure", () => {
    const resources = PANEL_SEARCH_CONFIG.resources;
    expect(resources.tableName).toBe("resources");
    expect(resources.partialPath).toBe("resources/partial");
    expect(resources.targetSelector).toBe("#resources-table");
    expect(resources.defaultPerPage).toBe(50);
  });

  test("PANEL_SEARCH_CONFIG prompts has correct structure", () => {
    const prompts = PANEL_SEARCH_CONFIG.prompts;
    expect(prompts.tableName).toBe("prompts");
    expect(prompts.partialPath).toBe("prompts/partial");
    expect(prompts.targetSelector).toBe("#prompts-table");
    expect(prompts.defaultPerPage).toBe(50);
  });

  test("PANEL_SEARCH_CONFIG gateways has correct structure", () => {
    const gateways = PANEL_SEARCH_CONFIG.gateways;
    expect(gateways.tableName).toBe("gateways");
    expect(gateways.partialPath).toBe("gateways/partial");
    expect(gateways.targetSelector).toBe("#gateways-table");
    expect(gateways.defaultPerPage).toBe(50);
  });

  test("PANEL_SEARCH_CONFIG a2a-agents has correct structure", () => {
    const agents = PANEL_SEARCH_CONFIG["a2a-agents"];
    expect(agents.tableName).toBe("agents");
    expect(agents.partialPath).toBe("a2a/partial");
    expect(agents.targetSelector).toBe("#agents-table");
    expect(agents.defaultPerPage).toBe(50);
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG contains all expected entities", () => {
    const expectedEntities = ["servers", "gateways", "tools", "resources", "prompts", "agents", "teams", "users"];
    expectedEntities.forEach((entity) => {
      expect(GLOBAL_SEARCH_ENTITY_CONFIG).toHaveProperty(entity);
    });
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG servers has correct structure", () => {
    const servers = GLOBAL_SEARCH_ENTITY_CONFIG.servers;
    expect(servers.label).toBe("Servers");
    expect(servers.tab).toBe("catalog");
    expect(servers.viewFunction).toBe("viewServer");
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG gateways has correct structure", () => {
    const gateways = GLOBAL_SEARCH_ENTITY_CONFIG.gateways;
    expect(gateways.label).toBe("Gateways");
    expect(gateways.tab).toBe("gateways");
    expect(gateways.viewFunction).toBe("viewGateway");
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG tools has correct structure", () => {
    const tools = GLOBAL_SEARCH_ENTITY_CONFIG.tools;
    expect(tools.label).toBe("Tools");
    expect(tools.tab).toBe("tools");
    expect(tools.viewFunction).toBe("viewTool");
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG resources has correct structure", () => {
    const resources = GLOBAL_SEARCH_ENTITY_CONFIG.resources;
    expect(resources.label).toBe("Resources");
    expect(resources.tab).toBe("resources");
    expect(resources.viewFunction).toBe("viewResource");
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG prompts has correct structure", () => {
    const prompts = GLOBAL_SEARCH_ENTITY_CONFIG.prompts;
    expect(prompts.label).toBe("Prompts");
    expect(prompts.tab).toBe("prompts");
    expect(prompts.viewFunction).toBe("viewPrompt");
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG agents has correct structure", () => {
    const agents = GLOBAL_SEARCH_ENTITY_CONFIG.agents;
    expect(agents.label).toBe("A2A Agents");
    expect(agents.tab).toBe("a2a-agents");
    expect(agents.viewFunction).toBe("viewA2AAgent");
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG teams has correct structure", () => {
    const teams = GLOBAL_SEARCH_ENTITY_CONFIG.teams;
    expect(teams.label).toBe("Teams");
    expect(teams.tab).toBe("teams");
    expect(teams.viewFunction).toBe("showTeamEditModal");
  });

  test("GLOBAL_SEARCH_ENTITY_CONFIG users has correct structure", () => {
    const users = GLOBAL_SEARCH_ENTITY_CONFIG.users;
    expect(users.label).toBe("Users");
    expect(users.tab).toBe("users");
    expect(users.viewFunction).toBe("showUserEditModal");
  });

  test("all PANEL_SEARCH_CONFIG entries have required fields", () => {
    Object.values(PANEL_SEARCH_CONFIG).forEach((config) => {
      expect(config).toHaveProperty("tableName");
      expect(config).toHaveProperty("partialPath");
      expect(config).toHaveProperty("targetSelector");
      expect(config).toHaveProperty("indicatorSelector");
      expect(config).toHaveProperty("searchInputId");
      expect(config).toHaveProperty("tagInputId");
      expect(config).toHaveProperty("inactiveCheckboxId");
      expect(config).toHaveProperty("defaultPerPage");
    });
  });

  test("all GLOBAL_SEARCH_ENTITY_CONFIG entries have required fields", () => {
    Object.values(GLOBAL_SEARCH_ENTITY_CONFIG).forEach((config) => {
      expect(config).toHaveProperty("label");
      expect(config).toHaveProperty("tab");
      expect(config).toHaveProperty("viewFunction");
    });
  });
});
