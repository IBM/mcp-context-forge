// ===================================================================
// ENHANCED MODAL FUNCTIONS with Security and State Management
// ===================================================================

import { AppState } from './appState.js';
import { safeGetElement } from './utils.js';

// Callback registry for cleanup functions defined in other modules
const cleanupCallbacks = {
    gatewayTest: null,
    toolTest: null,
    promptTest: null,
    resourceTest: null,
    a2aTest: null,
};

export function registerModalCleanup(modalType, callback) {
    if (modalType in cleanupCallbacks) {
        cleanupCallbacks[modalType] = callback;
    }
}

export function openModal(modalId) {
    try {
        if (AppState.isModalActive(modalId)) {
            console.warn(`Modal ${modalId} is already active`);
            return;
        }

        const modal = safeGetElement(modalId);
        if (!modal) {
            console.error(`Modal ${modalId} not found`);
            return;
        }

        // Reset modal state
        const resetModelVariable = false;
        if (resetModelVariable) {
            resetModalState(modalId);
        }

        modal.classList.remove("hidden");
        AppState.setModalActive(modalId);

        console.log(`✓ Opened modal: ${modalId}`);
    } catch (error) {
        console.error(`Error opening modal ${modalId}:`, error);
    }
}

export function closeModal(modalId, clearId = null) {
    try {
        const modal = safeGetElement(modalId);
        if (!modal) {
            console.error(`Modal ${modalId} not found`);
            return;
        }

        // Clear specified content if provided
        if (clearId) {
            const resultEl = safeGetElement(clearId);
            if (resultEl) {
                resultEl.innerHTML = "";
            }
        }

        // Clean up specific modal types via registered callbacks
        if (modalId === "gateway-test-modal" && cleanupCallbacks.gatewayTest) {
            cleanupCallbacks.gatewayTest();
        } else if (modalId === "tool-test-modal" && cleanupCallbacks.toolTest) {
            cleanupCallbacks.toolTest();
        } else if (modalId === "prompt-test-modal" && cleanupCallbacks.promptTest) {
            cleanupCallbacks.promptTest();
        } else if (modalId === "resource-test-modal" && cleanupCallbacks.resourceTest) {
            cleanupCallbacks.resourceTest();
        } else if (modalId === "a2a-test-modal" && cleanupCallbacks.a2aTest) {
            cleanupCallbacks.a2aTest();
        }

        modal.classList.add("hidden");
        AppState.setModalInactive(modalId);

        console.log(`✓ Closed modal: ${modalId}`);
    } catch (error) {
        console.error(`Error closing modal ${modalId}:`, error);
    }
}

export function resetModalState(modalId) {
    try {
        // Clear any dynamic content
        const modalContent = document.querySelector(
            `#${modalId} [data-dynamic-content]`,
        );
        if (modalContent) {
            modalContent.innerHTML = "";
        }

        // Reset any forms in the modal
        const forms = document.querySelectorAll(`#${modalId} form`);
        forms.forEach((form) => {
            try {
                form.reset();
                // Clear any error messages
                const errorElements = form.querySelectorAll(".error-message");
                errorElements.forEach((el) => el.remove());
                // Clear inline validation error styling
                const inlineErrors = form.querySelectorAll(
                    "p[data-error-message-for]",
                );
                inlineErrors.forEach((el) => el.classList.add("invisible"));
                // Clear red border styling from inputs
                const invalidInputs = form.querySelectorAll(
                    ".border-red-500, .focus\\:ring-red-500, .dark\\:border-red-500, .dark\\:ring-red-500",
                );
                invalidInputs.forEach((el) => {
                    el.classList.remove(
                        "border-red-500",
                        "focus:ring-red-500",
                        "dark:border-red-500",
                        "dark:ring-red-500",
                    );
                    el.setCustomValidity("");
                });
            } catch (error) {
                console.error("Error resetting form:", error);
            }
        });

        console.log(`✓ Reset modal state: ${modalId}`);
    } catch (error) {
        console.error(`Error resetting modal state ${modalId}:`, error);
    }
}
