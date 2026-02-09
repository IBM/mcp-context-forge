/**
* Show notification (simple implementation)
*/
export const showNotification = function (message, type = "info") {
  console.log(`${type.toUpperCase()}: ${message}`);
  
  // Create a simple toast notification
  const toast = document.createElement("div");
  toast.className = `fixed top-4 right-4 z-50 px-4 py-3 rounded-md text-sm font-medium max-w-sm ${
    type === "success"
    ? "bg-green-100 text-green-800 border border-green-400"
    : type === "error"
    ? "bg-red-100 text-red-800 border border-red-400"
    : "bg-blue-100 text-blue-800 border border-blue-400"
  }`;
  toast.textContent = message;
  
  document.body.appendChild(toast);
  
  // Auto-remove after 5 seconds
  setTimeout(() => {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, 5000);
}