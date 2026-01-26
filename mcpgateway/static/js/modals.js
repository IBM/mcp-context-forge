((Admin) => {
    // ===================================================================
    // ENHANCED MODAL FUNCTIONS with Security and State Management
    // ===================================================================

    Admin.openModal = function (modalId) {
        try {
            if (Admin.AppState.isModalActive(modalId)) {
                console.warn(`Modal ${modalId} is already active`);
                return;
            }

            const modal = Admin.safeGetElement(modalId);
            if (!modal) {
                console.error(`Modal ${modalId} not found`);
                return;
            }

            // Reset modal state
            const resetModelVariable = false;
            if (resetModelVariable) {
                Admin.resetModalState(modalId);
            }

            modal.classList.remove("hidden");
            Admin.AppState.setModalActive(modalId);

            console.log(`✓ Opened modal: ${modalId}`);
        } catch (error) {
            console.error(`Error opening modal ${modalId}:`, error);
        }
    };

    Admin.closeModal = function (modalId, clearId = null) {
        try {
            const modal = Admin.safeGetElement(modalId);
            if (!modal) {
                console.error(`Modal ${modalId} not found`);
                return;
            }

            // Clear specified content if provided
            if (clearId) {
                const resultEl = Admin.safeGetElement(clearId);
                if (resultEl) {
                    resultEl.innerHTML = "";
                }
            }

            // Clean up specific modal types
            if (modalId === "gateway-test-modal") {
                Admin.cleanupGatewayTestModal();
            } else if (modalId === "tool-test-modal") {
                Admin.cleanupToolTestModal();
            } else if (modalId === "prompt-test-modal") {
                Admin.cleanupPromptTestModal();
            } else if (modalId === "resource-test-modal") {
                Admin.cleanupResourceTestModal();
            } else if (modalId === "a2a-test-modal") {
                Admin.cleanupA2ATestModal();
            }

            modal.classList.add("hidden");
            Admin.AppState.setModalInactive(modalId);

            console.log(`✓ Closed modal: ${modalId}`);
        } catch (error) {
            console.error(`Error closing modal ${modalId}:`, error);
        }
    };

    Admin.resetModalState = function (modalId) {
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
    };
})(window.Admin)