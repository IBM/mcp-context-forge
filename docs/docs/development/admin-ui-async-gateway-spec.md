# Admin UI Async Gateway Lifecycle Specification

This document specifies the Admin UI changes required to support asynchronous gateway lifecycle operations.

---

## Overview

The Admin UI must display gateway status information and provide polling behavior for pending/deleting gateways when the `GATEWAY_ASYNC_LIFECYCLE_ENABLED` feature flag is enabled.

---

## Status Badge Updates

### Current Implementation (Line 159-164 in gateways_partial.html)

```html
<td class="px-6 py-4 whitespace-nowrap text-sm">
  {% if gateway.enabled %}
  <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800">Active</span>
  {% else %}
  <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800">Inactive</span>
  {% endif %}
</td>
```

### Required Implementation

```html
<td class="px-6 py-4 whitespace-nowrap text-sm">
  {% if gateway.status == 'pending' %}
  <div class="flex flex-col gap-1">
    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
      ⏳ Pending
    </span>
    {% if gateway.status_message %}
    <span class="text-xs text-gray-600 dark:text-gray-400">{{ gateway.status_message }}</span>
    {% endif %}
  </div>
  {% elif gateway.status == 'deleting' %}
  <div class="flex flex-col gap-1">
    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-orange-100 text-orange-800">
      🗑️ Deleting
    </span>
    {% if gateway.status_message %}
    <span class="text-xs text-gray-600 dark:text-gray-400">{{ gateway.status_message }}</span>
    {% endif %}
  </div>
  {% elif gateway.status == 'active' and gateway.enabled %}
  <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800">✓ Active</span>
  {% else %}
  <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800">✗ Inactive</span>
  {% endif %}
</td>
```

---

## Retry Metadata Display

Add a new column after "Status" to display retry metadata for pending gateways.

### Table Header Addition

```html
<th class="px-6 py-3 text-left text-xs font-medium text-gray-800 dark:text-gray-200 uppercase tracking-wider">Retry Info</th>
```

### Table Cell Implementation

```html
<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300">
  {% if gateway.status == 'pending' and gateway.registration_attempts > 0 %}
  <div class="flex flex-col gap-1">
    <span class="text-xs">Attempts: {{ gateway.registration_attempts }}</span>
    {% if gateway.next_retry_at %}
    <span class="text-xs text-gray-400 dark:text-gray-500">
      Next: {{ gateway.next_retry_at[:19] if gateway.next_retry_at is string else gateway.next_retry_at.strftime('%H:%M:%S') }}
    </span>
    {% endif %}
  </div>
  {% else %}
  <span class="text-gray-400 dark:text-gray-600 text-xs">—</span>
  {% endif %}
</td>
```

---

## Polling Behavior

### Alpine.js Polling Component

Add polling behavior to the gateways table for pending/deleting gateways:

```html
<div x-data="gatewayPolling()" x-init="init()">
  <table id="gateways-table" class="min-w-full divide-y divide-gray-200">
    <!-- existing table content -->
  </table>
</div>

<script>
function gatewayPolling() {
  return {
    pollInterval: null,
    pollIntervalSeconds: 5,
    
    init() {
      // Check if any gateways are pending/deleting
      if (this.hasPendingGateways()) {
        this.startPolling();
      }
    },
    
    hasPendingGateways() {
      const rows = document.querySelectorAll('#gateways-table-body tr');
      return Array.from(rows).some(row => {
        const statusBadge = row.querySelector('span[class*="bg-yellow-100"], span[class*="bg-orange-100"]');
        return statusBadge !== null;
      });
    },
    
    startPolling() {
      if (this.pollInterval) return; // Already polling
      
      this.pollInterval = setInterval(() => {
        // Trigger HTMX refresh
        htmx.trigger('#gateways-table', 'refresh');
        
        // Stop polling if no more pending gateways
        setTimeout(() => {
          if (!this.hasPendingGateways()) {
            this.stopPolling();
          }
        }, 1000);
      }, this.pollIntervalSeconds * 1000);
    },
    
    stopPolling() {
      if (this.pollInterval) {
        clearInterval(this.pollInterval);
        this.pollInterval = null;
      }
    }
  };
}
</script>
```

### HTMX Polling Attribute (Alternative)

Simpler approach using HTMX's built-in polling:

```html
<table 
  id="gateways-table" 
  class="min-w-full divide-y divide-gray-200"
  hx-get="{{ root_path }}/admin/gateways/partial"
  hx-trigger="refresh from:body, every 5s[document.querySelector('#gateways-table-body tr span.bg-yellow-100, #gateways-table-body tr span.bg-orange-100')]"
  hx-swap="outerHTML"
  hx-indicator="#gateways-loading"
>
  <!-- existing table content -->
</table>
```

**Explanation:**
- `every 5s[condition]` - Poll every 5 seconds only if condition is true
- Condition checks for presence of pending (yellow) or deleting (orange) status badges
- Automatically stops polling when no pending/deleting gateways exist

---

## CSS Additions

Add status-specific badge styles to `admin.css`:

```css
/* Gateway status badges */
.gateway-status-pending {
    background-color: rgb(254 243 199); /* yellow-100 */
    color: rgb(146 64 14); /* yellow-800 */
}

.gateway-status-deleting {
    background-color: rgb(255 237 213); /* orange-100 */
    color: rgb(154 52 18); /* orange-800 */
}

.gateway-status-active {
    background-color: rgb(220 252 231); /* green-100 */
    color: rgb(22 101 52); /* green-800 */
}

.gateway-status-inactive {
    background-color: rgb(254 226 226); /* red-100 */
    color: rgb(153 27 27); /* red-800 */
}

/* Dark mode variants */
.dark .gateway-status-pending {
    background-color: rgb(113 63 18 / 40%); /* yellow-800 with opacity */
    color: rgb(253 224 71); /* yellow-300 */
}

.dark .gateway-status-deleting {
    background-color: rgb(124 45 18 / 40%); /* orange-800 with opacity */
    color: rgb(253 186 116); /* orange-300 */
}

.dark .gateway-status-active {
    background-color: rgb(22 101 52 / 40%); /* green-800 with opacity */
    color: rgb(134 239 172); /* green-300 */
}

.dark .gateway-status-inactive {
    background-color: rgb(153 27 27 / 40%); /* red-800 with opacity */
    color: rgb(252 165 165); /* red-300 */
}

/* Retry info styling */
.gateway-retry-info {
    font-size: 0.75rem;
    line-height: 1rem;
    color: rgb(107 114 128); /* gray-500 */
}

.dark .gateway-retry-info {
    color: rgb(156 163 175); /* gray-400 */
}
```

---

## Action Menu Updates

### Disable Actions for Pending/Deleting Gateways

Update the action menu to disable certain actions when gateway is pending or deleting:

```html
{% if can_modify %}
<!-- Edit (disabled for pending/deleting) -->
<button
  type="button"
  role="menuitem"
  tabindex="0"
  @click="dispatch('editGateway', {{ gateway.id|tojson_attr }})"
  class="w-full flex items-center px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 {% if gateway.status in ['pending', 'deleting'] %}opacity-50 cursor-not-allowed{% endif %}"
  {% if gateway.status in ['pending', 'deleting'] %}disabled{% endif %}
>Edit</button>

<!-- Activate / Deactivate (disabled for pending/deleting) -->
<form 
  method="POST" 
  action="{{ root_path }}/admin/gateways/{{ gateway.id }}/state" 
  class="contents {% if gateway.status in ['pending', 'deleting'] %}opacity-50 cursor-not-allowed{% endif %}" 
  @submit="menuOpen = false" 
  data-action-submit="handleToggleSubmit" 
  data-arg0="gateways"
>
  <input type="hidden" name="activate" value="{{ 'false' if gateway.enabled else 'true' }}" />
  <button
    type="submit"
    role="menuitem"
    tabindex="0"
    class="w-full flex items-center px-4 py-2 text-sm {% if gateway.enabled %}text-yellow-600 dark:text-yellow-400{% else %}text-green-600 dark:text-green-400{% endif %} hover:bg-gray-100 dark:hover:bg-gray-700"
    {% if gateway.status in ['pending', 'deleting'] %}disabled{% endif %}
  >{% if gateway.enabled %}Deactivate{% else %}Activate{% endif %}</button>
</form>

<!-- Delete (always enabled - cancels pending operations) -->
<form method="POST" action="{{ root_path }}/admin/gateways/{{ gateway.id }}/delete" class="contents" @submit="menuOpen = false" data-action-submit="handleDeleteSubmit" data-arg0="gateway" data-arg1="{{ gateway_label|tojson_attr }}" data-arg2="gateways">
  <button
    type="submit"
    role="menuitem"
    tabindex="0"
    class="w-full flex items-center px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-700"
  >{% if gateway.status == 'pending' %}Cancel{% else %}Delete{% endif %}</button>
</form>
{% endif %}
```

---

## Loading Indicator

Add a loading indicator for polling updates:

```html
<div id="gateways-loading" class="htmx-indicator">
  <div class="fixed top-4 right-4 bg-blue-500 text-white px-4 py-2 rounded-lg shadow-lg flex items-center gap-2 z-50">
    <svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
    </svg>
    <span>Refreshing gateways...</span>
  </div>
</div>
```

---

## User Experience Flow

### Creating a Gateway (Async Mode)

1. User clicks "Create Gateway" button
2. Form submitted via POST /admin/gateways
3. Server returns 202 Accepted
4. UI shows gateway with "⏳ Pending" badge and "Gateway registration queued" message
5. Polling starts automatically (every 5 seconds)
6. Status updates to "✓ Active" when worker completes
7. Polling stops automatically

### Updating a Gateway (Async Mode)

1. User clicks "Edit" and submits changes
2. Server returns 202 Accepted
3. Gateway status changes to "⏳ Pending" with "Gateway update queued" message
4. Gateway stops serving requests during update
5. Polling continues until status returns to "✓ Active"
6. Gateway resumes serving with new configuration

### Deleting a Gateway (Async Mode)

1. User clicks "Delete" (or "Cancel" for pending gateway)
2. Server returns 202 Accepted
3. Gateway status changes to "🗑️ Deleting" with "Gateway deletion queued" message
4. Polling continues until gateway is removed from list
5. Table refreshes to show gateway removed

### Canceling a Pending Operation

1. User clicks "Cancel" on pending gateway
2. DELETE request sent to server
3. Status changes to "🗑️ Deleting"
4. Worker stops retry loop and performs cleanup
5. Gateway removed from list

---

## Accessibility Considerations

### Screen Reader Support

```html
<span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800" role="status" aria-live="polite">
  <span class="sr-only">Gateway status:</span>
  ⏳ Pending
</span>
```

### Keyboard Navigation

- Ensure polling doesn't interfere with keyboard focus
- Preserve focus position after table refresh
- Add aria-busy="true" during polling

```html
<table 
  id="gateways-table" 
  class="min-w-full divide-y divide-gray-200"
  aria-busy="false"
  x-data="{ polling: false }"
  :aria-busy="polling.toString()"
>
```

---

## Testing Checklist

- [ ] Status badges display correctly for all states (pending, active, deleting, inactive)
- [ ] `status_message` displays below status badge
- [ ] Retry metadata (attempts, next_retry_at) displays for pending gateways
- [ ] Polling starts automatically when pending/deleting gateways exist
- [ ] Polling stops automatically when no pending/deleting gateways exist
- [ ] Table refreshes every 5 seconds during polling
- [ ] User focus preserved during polling refresh
- [ ] Edit/Activate actions disabled for pending/deleting gateways
- [ ] Delete button changes to "Cancel" for pending gateways
- [ ] Loading indicator shows during refresh
- [ ] Dark mode styles work correctly
- [ ] Screen reader announces status changes
- [ ] Keyboard navigation works during polling

---

## Implementation Files

| File | Changes Required |
|------|------------------|
| `mcpgateway/templates/gateways_partial.html` | Update status column, add retry info column, add polling behavior |
| `mcpgateway/static/admin.css` | Add status badge styles and dark mode variants |
| `mcpgateway/static/js/admin.js` | Add polling logic (if using Alpine.js approach) |
| `mcpgateway/routers/admin.py` | Ensure gateway responses include `status`, `status_message`, `registration_attempts`, `next_retry_at` |

---

## Related Documentation

- [API Reference](../manage/gateway-lifecycle-async.md) - API response shapes
- [Rollout Guide](../using/async-gateway-rollout.md) - Feature enablement
- [Troubleshooting Guide](gateway-troubleshooting.md) - Common issues