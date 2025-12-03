# How to Enable Pooling for a Server via UI

## Visual Step-by-Step Guide

This guide shows you exactly how to enable session pooling for a server using the MCP Gateway Admin UI.

---

## Step 1: Navigate to Servers Page

1. Open your browser and go to: `http://localhost:4444/admin`
2. Click on **"Servers"** in the left sidebar menu
3. You'll see a list of all configured servers

**What you'll see:**
- A table with columns: Name, URL, Transport, Status, Actions
- Each server row has multiple action buttons in the Actions column

---

## Step 2: Locate Your Server

Find the server you want to enable pooling for in the list. In your case, look for the server with ID: `c69af0819bda4566af406298d51bc0c5`

**Visual Cue:**
- The server row will show the server name, URL, and transport type
- On the right side, you'll see a grid of action buttons

---

## Step 3: Click "Pool Config" Button

In the Actions column for your server, you'll see several buttons arranged in a grid:

```
Row 1: [Edit]
Row 2: [🔄 Pool Config] [📊 Pool Stats]
Row 3: [Export Config]
Row 4: [Deactivate/Activate] [Delete]
```

**Action:** Click the **"🔄 Pool Config"** button (cyan/teal colored button in Row 2, left side)

**Location in code:** [`admin.html:1977`](../../mcpgateway/templates/admin.html:1977)

---

## Step 4: Pool Configuration Modal Opens

A modal dialog will appear with the title **"🔄 Pool Configuration"**

**What you'll see in the modal:**

### Top Section: Enable Toggle
```
┌─────────────────────────────────────────────────┐
│ 🔄 Pool Configuration                      [X]  │
├─────────────────────────────────────────────────┤
│                                                 │
│ Enable Session Pooling              [Toggle]   │
│                                                 │
```

**Current State:** The toggle will be **OFF** (gray) because pooling is currently disabled

---

## Step 5: Enable Session Pooling

**Action:** Click the toggle switch to turn it **ON**

**What happens:**
- The toggle turns **BLUE** and moves to the right
- Additional configuration fields appear below the toggle
- The form expands to show all pool settings

**Visual Change:**
```
Before (Disabled):
Enable Session Pooling              [○────]  (Gray)

After (Enabled):
Enable Session Pooling              [────●]  (Blue)
```

---

## Step 6: Configure Pool Settings

Once enabled, you'll see these configuration fields:

### 6.1 Pool Strategy (Dropdown)
```
Pool Strategy
[Round Robin ▼]
```

**Options:**
- **Round Robin** (Recommended for general use)
- Least Connections
- Sticky Sessions
- Weighted
- None (Direct)

**Recommendation:** Keep "Round Robin" selected for balanced load distribution

---

### 6.2 Pool Size Configuration (3 fields in a row)
```
Min Size        Max Size        Target Size
[  1  ]         [ 10  ]         [  5  ]
```

**Recommended Settings:**
- **Min Size:** 2 (minimum sessions to maintain)
- **Max Size:** 10 (maximum sessions allowed)
- **Target Size:** 5 (ideal number of sessions)

**What these mean:**
- **Min Size:** Pool will always maintain at least this many sessions
- **Max Size:** Pool will never exceed this many sessions
- **Target Size:** Pool will try to maintain this many sessions under normal load

---

### 6.3 Timeout Configuration (2 fields in a row)
```
Idle Timeout (seconds)    Max Lifetime (seconds)
[    300    ]             [     3600     ]
```

**Recommended Settings:**
- **Idle Timeout:** 300 seconds (5 minutes) - How long an unused session stays alive
- **Max Lifetime:** 3600 seconds (1 hour) - Maximum age of any session

---

### 6.4 Auto-scaling Toggle
```
Enable Auto-scaling                    [Toggle]
Automatically adjust pool size based on demand
```

**Recommendation:** Turn this **ON** (blue) to allow the pool to grow/shrink based on demand

---

### 6.5 Health Check Threshold
```
Health Check Threshold (%)
[    70    ]
Minimum success rate to consider pool healthy
```

**Recommendation:** Keep at 70% - Pool is considered healthy if 70% of health checks pass

---

## Step 7: Save Configuration

At the bottom of the modal, you'll see two buttons:

```
                    [Cancel]  [Save Configuration]
```

**Action:** Click **"Save Configuration"** (blue button on the right)

**What happens:**
1. The configuration is sent to the server
2. A pool is created immediately (no restart needed)
3. You'll see a success notification: "Pool configuration saved successfully"
4. The modal closes automatically

---

## Step 8: Verify Pool Creation

After saving, verify the pool was created:

### Option A: Check Pool Stats Button
1. Click the **"📊 Pool Stats"** button (same row as Pool Config)
2. A modal should now open showing pool statistics
3. **Before:** You got a 503 error
4. **After:** You see pool stats with session counts and health score

### Option B: Check Pool Health Dashboard
1. Click **"Pool Health"** in the left sidebar menu
2. You should see your server's pool listed
3. Status should show as "healthy" with a green indicator

---

## Complete Configuration Example

Here's a recommended configuration for a typical server:

```
✅ Enable Session Pooling: ON

Pool Strategy: Round Robin

Pool Sizes:
  Min Size: 2
  Max Size: 10
  Target Size: 5

Timeouts:
  Idle Timeout: 300 seconds (5 minutes)
  Max Lifetime: 3600 seconds (1 hour)

✅ Enable Auto-scaling: ON

Health Check Threshold: 70%
```

---

## Troubleshooting

### Issue: Pool Config button doesn't respond

**Solution:**
1. Check browser console (F12) for JavaScript errors
2. Verify `pools.js` is loaded: Look for "POOL MANAGEMENT" in console
3. Refresh the page and try again

### Issue: Modal opens but fields are empty

**Solution:**
1. Check if the server exists in the database
2. Verify you have permission to read server configuration
3. Check network tab (F12) for API errors

### Issue: Save button doesn't work

**Solution:**
1. Verify all required fields are filled
2. Check that Min Size ≤ Target Size ≤ Max Size
3. Check browser console for validation errors

### Issue: Configuration saves but pool not created

**Solution:**
1. Check if global pooling is enabled: `SESSION_POOL_ENABLED=true` in `.env`
2. Restart the gateway if you changed the `.env` file
3. Check server logs for pool creation errors

---

## What Happens Behind the Scenes

### When you click "Save Configuration":

1. **JavaScript** ([`pools.js:229`](../../mcpgateway/static/pools.js:229)):
   - Collects form data
   - Validates configuration
   - Sends POST request to `/servers/{id}/pool/config`

2. **Backend** ([`main.py:2155`](../../mcpgateway/main.py:2155)):
   - Updates server record in database
   - Sets `pool_enabled = True`
   - Calls `SessionPoolManager.get_or_create_pool()`
   - Creates pool immediately (no restart needed)

3. **Pool Manager** ([`session_pool_manager.py`](../../mcpgateway/cache/session_pool_manager.py)):
   - Creates new `SessionPool` instance
   - Initializes sessions based on `min_size`
   - Starts health check background task
   - Registers pool in internal registry

---

## Verification Checklist

After enabling pooling, verify these items:

- [ ] Pool Config modal shows "Enable Session Pooling" as ON (blue toggle)
- [ ] Pool Stats button opens modal without 503 error
- [ ] Pool Stats shows correct session counts (e.g., "Total: 5, Active: 0, Available: 5")
- [ ] Pool Health dashboard lists your server's pool
- [ ] Pool health score is 100 (or close to it)
- [ ] Server status shows as "active" with pooling enabled

---

## Quick Reference: Button Locations

In the Servers table, each server has these buttons:

```
┌─────────────────────────────────────────────┐
│ Server Name: My Server                      │
│ URL: http://localhost:3000                  │
│ Transport: SSE                              │
│                                             │
│ Actions:                                    │
│   Row 1: [Edit]                            │
│   Row 2: [🔄 Pool Config] [📊 Pool Stats]  │ ← HERE
│   Row 3: [Export Config]                   │
│   Row 4: [Activate] [Delete]               │
└─────────────────────────────────────────────┘
```

**Pool Config Button:**
- **Icon:** 🔄
- **Color:** Cyan/Teal
- **Location:** Row 2, Left side
- **Tooltip:** "Configure session pooling for this server"

**Pool Stats Button:**
- **Icon:** 📊
- **Color:** Teal
- **Location:** Row 2, Right side
- **Tooltip:** "View pool statistics and health"

---

## Summary

**To enable pooling for a server:**

1. Go to **Servers** page
2. Find your server in the list
3. Click **"🔄 Pool Config"** button (Row 2, left side)
4. Toggle **"Enable Session Pooling"** to ON (blue)
5. Configure pool settings (or use defaults)
6. Click **"Save Configuration"**
7. Verify by clicking **"📊 Pool Stats"** button

**That's it!** Your server now has session pooling enabled and you can view pool statistics without getting 503 errors.