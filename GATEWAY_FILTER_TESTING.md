# Gateway Filter Testing Guide

## Overview
This document describes how to test the new gateway filtering functionality for associated tools, prompts, and resources.

## What Was Changed

### Backend (Already Existed)
The backend API endpoints already supported filtering by `gateway_id`:
- `/admin/tools/partial?gateway_id=<id1>,<id2>`
- `/admin/resources/partial?gateway_id=<id1>,<id2>`
- `/admin/prompts/partial?gateway_id=<id1>,<id2>`

### Frontend (New Implementation)
Added JavaScript functionality to:
1. Log gateway_id when MCP server checkbox is clicked
2. Collect all selected gateway IDs
3. Automatically reload tools/resources/prompts filtered by selected gateways

## Testing Steps

### 1. Open Browser Console
Press `F12` or `Ctrl+Shift+I` to open Developer Tools and switch to the Console tab.

### 2. Navigate to Create Virtual Server
Go to the admin interface and click "Create Virtual Server" or open the virtual server creation form.

### 3. Test Individual MCP Server Selection

**Action:** Click on an MCP server checkbox to select it.

**Expected Console Output:**
```
[MCP Server Selection] Gateway ID: df212f5e971a41e3917edcfae9a66711, Name: mcp-server, Checked: true
[Filter Update] Reloading associated items for gateway IDs: df212f5e971a41e3917edcfae9a66711
```

**Expected Behavior:**
- The tools, resources, and prompts lists should reload
- Only items associated with the selected gateway should be displayed

### 4. Test Multiple MCP Server Selection

**Action:** Select a second MCP server checkbox.

**Expected Console Output:**
```
[MCP Server Selection] Gateway ID: 885756888a8d43f2a62791e50c388494, Name: mcp-http, Checked: true
[Filter Update] Reloading associated items for gateway IDs: df212f5e971a41e3917edcfae9a66711,885756888a8d43f2a62791e50c388494
```

**Expected Behavior:**
- Tools/resources/prompts from BOTH selected gateways should now be visible

### 5. Test Deselection

**Action:** Uncheck one of the selected MCP servers.

**Expected Console Output:**
```
[MCP Server Selection] Gateway ID: df212f5e971a41e3917edcfae9a66711, Name: mcp-server, Checked: false
[Filter Update] Reloading associated items for gateway IDs: 885756888a8d43f2a62791e50c388494
```

**Expected Behavior:**
- Only tools/resources/prompts from the remaining selected gateway should be visible

### 6. Test Clear All Button

**Action:** Click the "Clear All" button under the Associated MCP Servers section.

**Expected Console Output:**
```
[Filter Update] Reloading associated items for gateway IDs: none (showing all)
```

**Expected Behavior:**
- All MCP server checkboxes should be unchecked
- ALL tools/resources/prompts should be displayed (no filter applied)

### 7. Test Select All Button

**Action:** Click the "Select All" button under the Associated MCP Servers section.

**Expected Console Output:**
```
[Filter Update] Reloading associated items for gateway IDs: <comma-separated list of all gateway IDs>
```

**Expected Behavior:**
- All visible MCP server checkboxes should be checked
- Tools/resources/prompts from ALL selected gateways should be displayed

### 8. Test Search + Filter

**Action:** 
1. Type a search term in the "Search for MCP servers..." box
2. Select one of the filtered MCP servers

**Expected Behavior:**
- Search should filter the visible MCP servers
- Selecting a filtered server should still trigger the filter reload
- Tools/resources/prompts should update based on selected gateway

## Validation Points

### ✅ Gateway ID Logging
- [ ] Gateway ID is logged when checkbox is clicked
- [ ] Gateway name is shown in the log
- [ ] Checked status (true/false) is accurate

### ✅ Filter Application
- [ ] Tools list reloads with gateway_id parameter
- [ ] Resources list reloads with gateway_id parameter
- [ ] Prompts list reloads with gateway_id parameter
- [ ] Multiple gateway IDs are comma-separated in the URL

### ✅ UI Responsiveness
- [ ] Lists reload smoothly without page refresh
- [ ] Loading indicators appear during reload (if implemented)
- [ ] Previously selected tools/resources/prompts are cleared after filter change
- [ ] Pills/badges update correctly to show selected items

### ✅ Edge Cases
- [ ] Works with no gateways selected (shows all items)
- [ ] Works with one gateway selected
- [ ] Works with multiple gateways selected
- [ ] Works after using "Select All"
- [ ] Works after using "Clear All"
- [ ] Works with search filter active

## Network Inspection

Open the Network tab in Developer Tools to verify the correct API calls:

**Expected API Calls:**
```
GET /admin/tools/partial?page=1&per_page=50&render=selector&gateway_id=df212f5e971a41e3917edcfae9a66711
GET /admin/resources/partial?page=1&per_page=50&render=selector&gateway_id=df212f5e971a41e3917edcfae9a66711
GET /admin/prompts/partial?page=1&per_page=50&render=selector&gateway_id=df212f5e971a41e3917edcfae9a66711
```

## Troubleshooting

### Issue: No console logs appear
**Solution:** Make sure browser console is open and not filtered. Check that JavaScript is enabled.

### Issue: Lists don't reload
**Solution:** Check if HTMX is loaded (`window.htmx` should be defined in console). Verify network requests are succeeding.

### Issue: Wrong items shown after filtering
**Solution:** Check the gateway_id parameter in the network tab. Verify the backend returns correct data for those IDs.

### Issue: "initToolSelect is not defined" error
**Solution:** Ensure the HTMX response includes the callback to initialize the select functions, or verify the functions are called after content loads.

## Code Locations

### JavaScript Functions
- `getSelectedGatewayIds()` - Collects all selected gateway IDs
- `reloadAssociatedItems()` - Triggers reload of tools/resources/prompts
- `initGatewaySelect()` - Main initialization function for gateway selection

### Backend Endpoints
- `mcpgateway/admin.py` - `admin_tools_partial_html()`, `admin_resources_partial_html()`, `admin_prompts_partial_html()`

### Frontend Files
- `mcpgateway/static/admin.js` - Main JavaScript implementation
- `mcpgateway/templates/admin.html` - HTML template with HTMX attributes
