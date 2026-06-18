/**
 * Event Delegation System for CSP Compliance
 *
 * This module provides a centralized event delegation system that replaces
 * inline event handlers (onclick, oninput, onchange, etc.) with data-action
 * attributes, making the admin UI compliant with strict Content Security Policy.
 *
 * Usage in HTML:
 *   Instead of: <button onclick="Admin.someFunction(arg)">
 *   Use: <button data-action-click="someFunction" data-arg0="arg">
 *
 * The dispatcher automatically:
 * - Parses data-* attributes as function arguments
 * - Handles event types (click, input, change, submit, keydown, etc.)
 * - Calls the appropriate Admin.* method
 * - Supports both simple calls and calls with arguments
 */

/**
 * Parse data attributes from an element to extract function arguments
 * @param {HTMLElement} element - The element with data attributes
 * @returns {Array} - Array of parsed arguments
 */
function parseDataAttributes(element) {
  const args = [];
  const dataset = element.dataset;

  // Collect all data-arg-* attributes in order
  let i = 0;
  while (dataset[`arg${i}`] !== undefined) {
    const value = dataset[`arg${i}`];

    // Handle special 'this' reference
    if (value === 'this') {
      args.push(element);
    } else if (value.startsWith('this.')) {
      // Handle this.property references
      const prop = value.substring(5);
      // Guard against prototype pollution
      if (prop === '__proto__' || prop === 'constructor' || prop === 'prototype') {
        args.push(undefined);
      } else {
        args.push(element[prop]);
      }
    } else {
      // Try to parse as JSON for complex types, fall back to string
      try {
        args.push(JSON.parse(value));
      } catch {
        args.push(value);
      }
    }
    i++;
  }

  // If no numbered args, check for single data-arg
  if (args.length === 0 && dataset.arg !== undefined) {
    const value = dataset.arg;
    if (value === 'this') {
      args.push(element);
    } else if (value.startsWith('this.')) {
      const prop = value.substring(5);
      // Guard against prototype pollution
      if (prop === '__proto__' || prop === 'constructor' || prop === 'prototype') {
        args.push(undefined);
      } else {
        args.push(element[prop]);
      }
    } else {
      try {
        args.push(JSON.parse(value));
      } catch {
        args.push(value);
      }
    }
  }

  return args;
}

/**
 * Execute an action from the Admin namespace
 * @param {string} action - The function name to call
 * @param {Array} args - Arguments to pass to the function
 * @param {Event} event - The original event object
 * @returns {*} - The return value of the called function
 */
function executeAction(action, args, event, eventFirst = false) {
  if (!action) return;

  // Handle nested function paths (e.g., "AppState.reset")
  const parts = action.split('.');
  let fn = window.Admin;

  for (const part of parts) {
    if (fn && typeof fn === 'object') {
      fn = fn[part];
    } else {
      console.error(`Action not found: ${action}`);
      return;
    }
  }

  if (typeof fn === 'function') {
    if (eventFirst) {
      return fn(event, ...args);
    }
    return fn(...args, event);
  } else {
    console.error(`Action is not a function: ${action}`);
  }
}

/**
 * Handle delegated click events
 * @param {Event} event - The click event
 */
function handleDelegatedClick(event) {
  // Handle team selector item clicks (data-action="select-team" on buttons injected
  // via innerHTML, where onclick attributes are stripped by the innerHTML guard).
  const selectTeamTarget = event.target.closest('[data-action="select-team"]');
  if (selectTeamTarget) {
    event.preventDefault();
    if (window.Admin && typeof window.Admin.selectTeamFromSelector === 'function') {
      window.Admin.selectTeamFromSelector(selectTeamTarget);
    }
    return;
  }

  const target = event.target.closest('[data-action-click]');
  if (!target) return;

  const action = target.dataset.actionClick;
  const args = parseDataAttributes(target);

  // Handle explicit stop-propagation request
  if (target.dataset.stopPropagation === 'true') {
    event.stopPropagation();
  }

  // Check if we should prevent default
  if (target.dataset.preventDefault !== 'false') {
    // For links and buttons, prevent default unless explicitly disabled
    if (target.tagName === 'A' || target.tagName === 'BUTTON') {
      event.preventDefault();
    }
  }

  executeAction(action, args, event);
}

/**
 * Handle delegated input events
 * @param {Event} event - The input event
 */
function handleDelegatedInput(event) {
  const target = event.target.closest('[data-action-input]');
  if (!target) return;

  const action = target.dataset.actionInput;
  const args = parseDataAttributes(target);

  // Add the input value as first argument if no args specified
  if (args.length === 0) {
    args.push(target.value);
  }

  executeAction(action, args, event);
}

/**
 * Handle delegated change events
 * @param {Event} event - The change event
 */
function handleDelegatedChange(event) {
  const target = event.target.closest('[data-action-change]');
  if (!target) return;

  const action = target.dataset.actionChange;
  const args = parseDataAttributes(target);

  // Add the changed value as first argument if no args specified
  if (args.length === 0) {
    if (target.type === 'checkbox') {
      args.push(target.checked);
    } else {
      args.push(target.value);
    }
  }

  executeAction(action, args, event);
}

/**
 * Handle delegated submit events
 * @param {Event} event - The submit event
 */
function handleDelegatedSubmit(event) {
  const target = event.target.closest('[data-action-submit]');
  if (!target) return;

  const action = target.dataset.actionSubmit;
  const args = parseDataAttributes(target);

  // Prevent default form submission unless explicitly disabled
  if (target.dataset.preventDefault !== 'false') {
    event.preventDefault();
  }

  const result = executeAction(action, args, event, true);

  // If the action returns false, prevent form submission
  if (result === false) {
    event.preventDefault();
  }
}

/**
 * Handle delegated keydown events
 * @param {Event} event - The keydown event
 */
function handleDelegatedKeydown(event) {
  const target = event.target.closest('[data-action-keydown]');
  if (!target) return;

  const action = target.dataset.actionKeydown;
  const args = parseDataAttributes(target);

  executeAction(action, args, event);
}

/**
 * Handle delegated focus events
 * @param {Event} event - The focus event
 */
function handleDelegatedFocus(event) {
  const target = event.target.closest('[data-action-focus]');
  if (!target) return;

  const action = target.dataset.actionFocus;
  const args = parseDataAttributes(target);

  executeAction(action, args, event);
}

/**
 * Handle delegated blur events
 * @param {Event} event - The blur event
 */
function handleDelegatedBlur(event) {
  const target = event.target.closest('[data-action-blur]');
  if (!target) return;

  const action = target.dataset.actionBlur;
  const args = parseDataAttributes(target);

  executeAction(action, args, event);
}

/**
 * Handle delegated reset events
 * @param {Event} event - The reset event
 */
function handleDelegatedReset(event) {
  const target = event.target.closest('[data-action-reset]');
  if (!target) return;

  const action = target.dataset.actionReset;
  const args = parseDataAttributes(target);

  executeAction(action, args, event);
}

/**
 * Initialize the event delegation system
 * This should be called once when the page loads
 */
let initialized = false;

/**
 * Show a confirm dialog and submit the form if confirmed.
 * For use with data-action-submit on forms that need confirmation.
 * @param {Event} event - The submit event
 * @param {string} message - The confirmation message
 * @returns {boolean} - false if cancelled (prevents submission)
 */
function confirmAction(event, message) {
  if (!confirm(message)) {
    event.preventDefault();
    return false;
  }
  return true;
}

/**
 * Helper: click an element by ID
 * @param {string} id - Element ID
 */
function clickElement(id) {
  const el = document.getElementById(id);
  if (el) el.click();
}

/**
 * Helper: hide an element by ID
 * @param {string} id - Element ID
 */
function hideElement(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

/**
 * Helper: toggle a CSS class on an element by ID
 * @param {string} id - Element ID
 * @param {string} className - Class to toggle
 */
function toggleElementClass(id, className) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle(className);
}

/**
 * Helper: toggle visibility of a one-time auth hint
 * @param {string} hintId - Hint element ID
 * @param {Event} event - Change event
 */
function toggleOneTimeAuthHint(hintId, event) {
  const el = document.getElementById(hintId);
  if (el) el.style.display = event.target.checked ? 'block' : 'none';
}

/**
 * Helper: clear custom validity on an input
 * @param {Event} event - Input event
 */
function clearCustomValidity(event) {
  event.target.setCustomValidity('');
}

/**
 * Helper: auto-resize a textarea to fit content
 * @param {Event} event - Input event
 */
function autoResizeTextarea(event) {
  const el = event.target;
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

/**
 * Helper: remove the closest .fixed ancestor
 * @param {Event} event - Click event
 */
function removeClosestFixed(event) {
  const el = event.target.closest('.fixed');
  if (el) el.remove();
}

/**
 * Helper: execute bulk import dropdown toggle and reload page
 */
function executeBulkImportAndReload() {
  if (typeof toggleBulkImportDropdown === 'function') {
    toggleBulkImportDropdown();
  }
  window.location.reload();
}

/**
 * Helper: clear the associatedTools select on form reset
 * @param {Event} event - Reset event
 */
function clearAssociatedTools(event) {
  const el = document.getElementById('associatedTools');
  if (el) el.selectedIndex = -1;
}

/**
 * Helper: delay execution of an Admin action
 * @param {string} actionName - Name of the action on window.Admin
 * @param {number} delayMs - Delay in milliseconds
 */
function delayAction(actionName, delayMs) {
  setTimeout(() => {
    if (window.Admin && typeof window.Admin[actionName] === 'function') {
      window.Admin[actionName]();
    }
  }, delayMs);
}

/**
 * Helper: toggle UAID fields from a change event
 * @param {string} formSuffix - Suffix for the form (e.g., 'a2a')
 * @param {Event} event - Change event
 */
function toggleUAIDFieldsFromEvent(formSuffix, event) {
  if (window.Admin && typeof window.Admin.toggleUAIDFields === 'function') {
    window.Admin.toggleUAIDFields(formSuffix, event.target.checked);
  }
}

/**
 * Reset the initialization flag (for testing only)
 */
export function resetEventDelegation() {
  initialized = false;
}

export function initializeEventDelegation() {
  if (initialized) return;
  initialized = true;

  // Use capture phase to ensure we catch events before other handlers
  const options = { capture: true };

  // Register delegated event listeners on document
  document.addEventListener('click', handleDelegatedClick, options);
  document.addEventListener('input', handleDelegatedInput, options);
  document.addEventListener('change', handleDelegatedChange, options);
  document.addEventListener('submit', handleDelegatedSubmit, options);
  document.addEventListener('keydown', handleDelegatedKeydown, options);
  document.addEventListener('focus', handleDelegatedFocus, options);
  document.addEventListener('blur', handleDelegatedBlur, options);
  document.addEventListener('reset', handleDelegatedReset, options);

  // Set flag for Playwright tests to wait for initialization
  if (window.Admin) {
    window.Admin.eventDelegationInitialized = true;
    window.Admin.confirmAction = confirmAction;
    window.Admin.clickElement = clickElement;
    window.Admin.hideElement = hideElement;
    window.Admin.toggleElementClass = toggleElementClass;
    window.Admin.toggleOneTimeAuthHint = toggleOneTimeAuthHint;
    window.Admin.clearCustomValidity = clearCustomValidity;
    window.Admin.autoResizeTextarea = autoResizeTextarea;
    window.Admin.removeClosestFixed = removeClosestFixed;
    window.Admin.executeBulkImportAndReload = executeBulkImportAndReload;
    window.Admin.clearAssociatedTools = clearAssociatedTools;
    window.Admin.delayAction = delayAction;
    window.Admin.toggleUAIDFieldsFromEvent = toggleUAIDFieldsFromEvent;
  }
}
