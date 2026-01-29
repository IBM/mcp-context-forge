((Admin) => {
    // Global event handler for Escape key on modals
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            // Find any active modal
            const activeModal = Array.from(Admin.AppState.activeModals)[0];
            if (activeModal) {
                Admin.closeModal(activeModal);
            }
        }
    });

    // DOCUMENT ME
    document.addEventListener("DOMContentLoaded", () => {
        // Use #tool-ops-main-content-wrapper as the event delegation target because
        // #toolBody gets replaced by HTMX swaps. The wrapper survives swaps.
        const toolOpsWrapper = Admin.safeGetElement(
            "tool-ops-main-content-wrapper",
        );
        const selectedList = Admin.safeGetElement("selectedList");
        const selectedCount = Admin.safeGetElement("selectedCount");
        const searchBox = Admin.safeGetElement("searchBox");

        let selectedTools = [];
        let selectedToolIds = [];

        if (toolOpsWrapper !== null) {
            // ✅ Use event delegation on wrapper (survives HTMX swaps)
            toolOpsWrapper.addEventListener("change", (event) => {
                const cb = event.target;
                if (cb.classList.contains("tool-checkbox")) {
                    const toolName = cb.getAttribute("data-tool");
                    if (cb.checked) {
                        if (!selectedTools.includes(toolName)) {
                            selectedTools.push(toolName.split("###")[0]);
                            selectedToolIds.push(toolName.split("###")[1]);
                        }
                    } else {
                        selectedTools = selectedTools.filter(
                            (t) => t !== toolName.split("###")[0],
                        );
                        selectedToolIds = selectedToolIds.filter(
                            (t) => t !== toolName.split("###")[1],
                        );
                    }
                    Admin.updateSelectedList();
                }
            });
        }

        Admin.updateSelectedList = function () {
            selectedList.innerHTML = "";
            if (selectedTools.length === 0) {
                selectedList.textContent = "No tools selected";
            } else {
                selectedTools.forEach((tool) => {
                    const item = document.createElement("div");
                    item.className =
                        "flex items-center justify-between bg-indigo-100 text-indigo-800 px-3 py-1 rounded-md";
                    item.innerHTML = `
                        <span>${tool}</span>
                        <button class="text-indigo-500 hover:text-indigo-700 font-bold remove-btn">&times;</button>
                    `;
                    item.querySelector(".remove-btn").addEventListener(
                        "click",
                        () => {
                            selectedTools = selectedTools.filter((t) => t !== tool);
                            const box = document.querySelector(`
                                .tool-checkbox[data-tool="${tool}"]`);
                            if (box) {
                                box.checked = false;
                            }
                            Admin.updateSelectedList();
                        },
                    );
                    selectedList.appendChild(item);
                });
            }
            selectedCount.textContent = selectedTools.length;
        }

        // --- Search logic ---
        if (searchBox !== null) {
            searchBox.addEventListener("input", () => {
                const query = searchBox.value.trim().toLowerCase();
                // Search within #toolBody (which is inside #tool-ops-main-content-wrapper)
                document
                    .querySelectorAll("#tool-ops-main-content-wrapper #toolBody tr")
                    .forEach((row) => {
                        const name = row.dataset.name;
                        row.style.display =
                            name && name.includes(query) ? "" : "none";
                    });
            });
        }

        // Generic API call for Enrich/Validate
        Admin.callEnrichment = async function () {
            // const selectedTools = Admin.getSelectedTools();

            if (selectedTools.length === 0) {
                Admin.showErrorMessage("⚠️ Please select at least one tool.");
                return;
            }
            try {
                console.log(selectedToolIds);
                selectedToolIds.forEach((toolId) => {
                    console.log(toolId);
                    fetch(`/toolops/enrichment/enrich_tool?tool_id=${toolId}`, {
                        method: "POST",
                        headers: {
                            "Cache-Control": "no-cache",
                            Pragma: "no-cache",
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify({ tool_id: toolId }),
                    });
                });
                Admin.showSuccessMessage("Tool description enrichment has started.");
                // Uncheck all checkboxes
                document.querySelectorAll(".tool-checkbox").forEach((cb) => {
                    cb.checked = false;
                });

                // Empty the selected tools array
                selectedTools = [];
                selectedToolIds = [];

                // Update the selected tools list UI
                Admin.updateSelectedList();
            } catch (err) {
                //   responseDiv.textContent = `❌ Error: ${err.message}`;
                Admin.showErrorMessage(`❌ Error: ${err.message}`);
            }
        };

        Admin.generateBulkTestCases = async function () {
            const testCases = parseInt(
                Admin.safeGetElement("gen-bulk-testcase-count").value,
            );
            const variations = parseInt(
                Admin.safeGetElement("gen-bulk-nl-variation-count").value,
            );

            if (!testCases || !variations || testCases < 1 || variations < 1) {
                Admin.showErrorMessage(
                    "⚠️ Please enter valid numbers for test cases and variations.",
                );
                return;
            }

            try {
                for (const toolId of selectedToolIds) {
                    fetch(
                        `/toolops/validation/generate_testcases?tool_id=${toolId}&number_of_test_cases=${testCases}&number_of_nl_variations=${variations}&mode=generate`,
                        {
                            method: "POST",
                            headers: {
                                "Cache-Control": "no-cache",
                                Pragma: "no-cache",
                                "Content-Type": "application/json",
                            },
                            body: JSON.stringify({ tool_id: toolId }),
                        },
                    );
                }
                Admin.showSuccessMessage(
                    "Test case generation for tool validation has started.",
                );
                // Reset selections
                document.querySelectorAll(".tool-checkbox").forEach((cb) => {
                    cb.checked = false;
                });
                selectedTools = [];
                selectedToolIds = [];
                Admin.updateSelectedList();

                // Close modal immediately after clicking Generate
                Admin.closeModal("bulk-testcase-gen-modal");
            } catch (err) {
                Admin.showErrorMessage(`❌ Error: ${err.message}`);
            }
        }

        Admin.openTestCaseModal = function () {
            if (selectedToolIds.length === 0) {
                Admin.showErrorMessage("⚠️ Please select at least one tool.");
                return;
            }

            // Show modal
            document
                .getElementById("bulk-testcase-gen-modal")
                .classList.remove("hidden");
            document
                .getElementById("bulk-generate-btn")
                .addEventListener("click", Admin.generateBulkTestCases);
        }

        Admin.clearAllSelections = function () {
            // Uncheck all checkboxes
            document.querySelectorAll(".tool-checkbox").forEach((cb) => {
                cb.checked = false;
            });

            // Empty the selected tools array
            selectedTools = [];
            selectedToolIds = [];

            // Update the selected tools list UI
            Admin.updateSelectedList();
        }
        // Button listeners
        const enrichToolsBtn = Admin.safeGetElement("enrichToolsBtn");

        if (enrichToolsBtn !== null) {
            document
                .getElementById("enrichToolsBtn")
                .addEventListener("click", () => Admin.callEnrichment());
            document
                .getElementById("validateToolsBtn")
                .addEventListener("click", () => Admin.openTestCaseModal());
            document
                .getElementById("clearToolsBtn")
                .addEventListener("click", () => Admin.clearAllSelections());
        }
    });
})(window.Admin)