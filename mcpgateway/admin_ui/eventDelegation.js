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
      args.push(element[prop]);
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
      args.push(element[prop]);
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
function executeAction(action, args, event) {
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
    // Add event as last argument if the function might need it
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
  const target = event.target.closest('[data-action-click]');
  if (!target) return;

  const action = target.dataset.actionClick;
  const args = parseDataAttributes(target);

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

  const result = executeAction(action, args, event);

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
 * Initialize the event delegation system
 * This should be called once when the page loads
 */
export function initializeEventDelegation() {
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

  console.log('Event delegation system initialized for CSP compliance');
}
