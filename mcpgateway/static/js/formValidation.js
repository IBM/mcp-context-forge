// ===================================================================
// ENHANCED FORM VALIDATION for All Forms
// ===================================================================

import { validateInputName } from "./security";

export const setupFormValidation = function () {
  // Add validation to all forms on the page
  const forms = document.querySelectorAll("form");
  
  forms.forEach((form) => {
    // Add validation to name fields
    const nameFields = form.querySelectorAll(
      'input[name*="name"], input[name*="Name"]',
    );
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
          this.setCustomValidity(validation.error);
          this.classList.add(
            "border-red-500",
            "focus:ring-red-500",
            "dark:border-red-500",
            "dark:ring-red-500",
          );
          if (errorMessageElement) {
            errorMessageElement.innerText = validation.error;
            errorMessageElement.classList.remove("invisible");
          }
        } else {
          this.setCustomValidity("");
          this.value = validation.value;
          this.classList.remove(
            "border-red-500",
            "focus:ring-red-500",
            "dark:border-red-500",
            "dark:ring-red-500",
          );
          if (errorMessageElement) {
            errorMessageElement.classList.add("invisible");
          }
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
          this.setCustomValidity("");
          this.classList.remove(
            "border-red-500",
            "focus:ring-red-500",
            "dark:border-red-500",
            "dark:ring-red-500",
          );
          const errorMessageElement = this.parentNode?.querySelector(
            'p[data-error-message-for="url"]',
          );
          if (errorMessageElement) {
            errorMessageElement.classList.add("invisible");
          }
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
          this.setCustomValidity(validation.error);
          this.classList.add(
            "border-red-500",
            "focus:ring-red-500",
            "dark:border-red-500",
            "dark:ring-red-500",
          );
          if (errorMessageElement) {
            errorMessageElement.innerText = validation.error;
            errorMessageElement.classList.remove("invisible");
          }
        } else {
          this.setCustomValidity("");
          this.value = validation.value;
          this.classList.remove(
            "border-red-500",
            "focus:ring-red-500",
            "dark:border-red-500",
            "dark:ring-red-500",
          );
          if (errorMessageElement) {
            errorMessageElement.classList.add("invisible");
          }
        }
      });
    });
  });
}