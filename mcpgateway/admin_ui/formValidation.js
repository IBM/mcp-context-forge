// ===================================================================
// ENHANCED FORM VALIDATION for All Forms
// ===================================================================

import { validateInputName, validateUrl } from "./security.js";

const errorClasses = [
  "border-red-500",
  "focus:ring-red-500",
  "dark:border-red-500",
  "dark:ring-red-500",
];

function ensureErrorId(field, errorMessageElement) {
  if (!errorMessageElement) return null;
  if (!errorMessageElement.id) {
    const baseId = field.id || field.name || "field";
    errorMessageElement.id = `${baseId}-error`;
  }
  return errorMessageElement.id;
}

function addDescribedBy(field, id) {
  if (!id) return;
  const currentIds = (field.getAttribute("aria-describedby") || "")
    .split(/\s+/)
    .filter(Boolean);
  if (!currentIds.includes(id)) {
    currentIds.push(id);
  }
  field.setAttribute("aria-describedby", currentIds.join(" "));
}

function removeDescribedBy(field, id) {
  if (!id) return;
  const remainingIds = (field.getAttribute("aria-describedby") || "")
    .split(/\s+/)
    .filter((currentId) => currentId && currentId !== id);
  if (remainingIds.length > 0) {
    field.setAttribute("aria-describedby", remainingIds.join(" "));
  } else {
    field.removeAttribute("aria-describedby");
  }
}

function showFieldError(field, errorMessageElement, message) {
  field.setCustomValidity(message);
  field.setAttribute("aria-invalid", "true");
  field.classList.add(...errorClasses);

  if (errorMessageElement) {
    const errorId = ensureErrorId(field, errorMessageElement);
    errorMessageElement.innerText = message;
    errorMessageElement.setAttribute("role", "status");
    errorMessageElement.setAttribute("aria-live", "polite");
    errorMessageElement.classList.remove("invisible");
    addDescribedBy(field, errorId);
  }
}

function clearFieldError(field, errorMessageElement) {
  field.setCustomValidity("");
  field.setAttribute("aria-invalid", "false");
  field.classList.remove(...errorClasses);

  if (errorMessageElement) {
    const errorId = ensureErrorId(field, errorMessageElement);
    errorMessageElement.classList.add("invisible");
    removeDescribedBy(field, errorId);
  }
}

export const setupFormValidation = function () {
  // Add validation to all forms on the page
  const forms = document.querySelectorAll("form");

  forms.forEach((form) => {
    // Add validation to name fields
    // Target only the actual technical name inputs (avoid matching displayName)
    const nameFields = Array.from(
      form.querySelectorAll(
        'input[name="name"], input[name="customName"], input[name="custom_name"]',
      ),
    ).filter((f) => {
      // Exclude hidden inputs and any display-name-like fields so
      // display names remain optional and aren't validated here.
      if (!f) return false;
      if (f.type && f.type.toLowerCase() === "hidden") return false;
      if (/display/i.test(f.name || "")) return false;
      return true;
    });

    nameFields.forEach((field) => {
      field.addEventListener("blur", function () {
        const parentNode = this.parentNode;
        const inputLabel = parentNode?.querySelector(
          `label[for="${this.id}"]`,
        );
        const errorMessageElement = parentNode?.querySelector(
          'p[data-error-message-for="name"]',
        );
        const validation = validateInputName(
          this.value,
          inputLabel?.innerText,
        );
        if (!validation.valid) {
          showFieldError(this, errorMessageElement, validation.error);
        } else {
          clearFieldError(this, errorMessageElement);
          this.value = validation.value;
        }
      });
    });

    // Add validation to URL fields
    const urlFields = form.querySelectorAll(
      'input[name*="url"], input[name*="URL"]',
    );
    urlFields.forEach((field) => {
      field.addEventListener("blur", function () {
        // Skip validation for empty optional URL fields
        if (!this.value && !this.required) {
          const errorMessageElement = this.parentNode?.querySelector(
            'p[data-error-message-for="url"]',
          );
          clearFieldError(this, errorMessageElement);
          return;
        }
        const parentNode = this.parentNode;
        const inputLabel = parentNode?.querySelector(
          `label[for="${this.id}"]`,
        );
        const errorMessageElement = parentNode?.querySelector(
          'p[data-error-message-for="url"]',
        );
        const validation = validateUrl(
          this.value,
          inputLabel?.innerText,
        );
        if (!validation.valid) {
          showFieldError(this, errorMessageElement, validation.error);
        } else {
          clearFieldError(this, errorMessageElement);
          this.value = validation.value;
        }
      });
    });
  });
}
