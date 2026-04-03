(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  async function clearHistoryJobs() {
    const response = await fetch("/api/history/clear", {
      method: "POST",
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      payload = {};
    }
    if (!response.ok) {
      const message = payload && payload.detail ? payload.detail : "Failed to clear history.";
      throw new Error(message);
    }
    return payload;
  }

  async function clearUploadsStorage() {
    const response = await fetch("/api/settings/clear-uploads", {
      method: "POST",
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to clear uploads.");
    }
  }

  async function clearResultsStorage() {
    const response = await fetch("/api/settings/clear-results", {
      method: "POST",
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to clear results.");
    }
  }

  function initStorageActions() {
    if (app.storageActions && app.storageActions.__initialized) {
      return;
    }

    document.querySelectorAll("[data-storage-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!(button instanceof HTMLElement) || button.hasAttribute("disabled")) {
          return;
        }
        const action = button.getAttribute("data-storage-action") || "";
        if (!action) {
          return;
        }

        if (action === "clear-history") {
          const historyList = app.dom ? app.dom.historyList : null;
          const count = historyList ? historyList.querySelectorAll(".history-row").length : 0;
          if (!count) {
            if (app.toasts) {
              app.toasts.notifySystem("History", "Already empty.", "success", {
                key: "history:empty",
                cooldown: 2500,
                duration: 4200,
              });
            }
            return;
          }
          const confirmed = app.modals
            ? await app.modals.openConfirmModal({
                title: "Delete history",
                message: app.historyActions
                  ? app.historyActions.buildHistoryClearMessage(count)
                  : "Delete all history?",
                confirmText: "Delete all",
                cancelText: "Cancel",
              })
            : false;
          if (!confirmed) {
            return;
          }
          button.setAttribute("disabled", "disabled");
          try {
            const payload = await clearHistoryJobs();
            if (payload && payload.failed_results) {
              const failedCount = payload.failed_results;
              const deletedCount = payload.deleted_jobs || 0;
              const label = deletedCount === 1 ? "item" : "items";
              if (app.toasts) {
                app.toasts.notifySystem(
                  "History",
                  `Deleted ${deletedCount} ${label}. ${failedCount} result folders couldn’t be removed.`,
                  "error",
                  {
                    key: "history:clear:partial",
                    cooldown: 2000,
                  }
                );
              }
            } else {
              const deletedCount = payload && payload.deleted_jobs ? payload.deleted_jobs : count;
              const label = deletedCount === 1 ? "item" : "items";
              if (app.toasts) {
                app.toasts.notifySystem("History", `Deleted ${deletedCount} ${label}.`, "success", {
                  key: "history:clear",
                  cooldown: 0,
                  duration: 5200,
                });
              }
            }
          } catch (error) {
            console.warn("Failed to clear history (settings)", error);
            if (app.toasts) {
              app.toasts.notifySystem("History", "Can’t delete history. Try again.", "error", {
                key: "history:clear:error",
                cooldown: 1500,
              });
            }
          } finally {
            if (app.state) {
              await app.state.refreshState();
            }
            button.removeAttribute("disabled");
          }
          return;
        }

        if (action === "clear-uploads") {
          const confirmed = app.modals
            ? await app.modals.openConfirmModal({
                title: "Clear queued uploads",
                message:
                  "Deletes local processing copies.\nYour original files stay as-is.",
                confirmText: "Clear uploads",
                cancelText: "Cancel",
              })
            : false;
          if (!confirmed) {
            return;
          }
          button.setAttribute("disabled", "disabled");
          try {
            await clearUploadsStorage();
            if (app.toasts) {
              app.toasts.notifySystem("Storage", "Cleared queued uploads.", "success", {
                key: "storage:clear-uploads",
                cooldown: 0,
                duration: 5200,
              });
            }
          } catch (error) {
            console.warn("Failed to clear uploads", error);
            if (app.toasts) {
              app.toasts.notifySystem("Storage", "Can’t clear queued uploads. Try again.", "error", {
                key: "storage:clear-uploads:error",
                cooldown: 1500,
              });
            }
          } finally {
            if (app.state) {
              await app.state.refreshState();
            }
            button.removeAttribute("disabled");
          }
          return;
        }

        if (action === "clear-results") {
          const confirmed = app.modals
            ? await app.modals.openConfirmModal({
                title: "Clear results folder",
                message:
                  "Deletes stored transcript files from this Mac.\nHistory stays, but downloads may stop working.",
                confirmText: "Clear results",
                cancelText: "Cancel",
              })
            : false;
          if (!confirmed) {
            return;
          }
          button.setAttribute("disabled", "disabled");
          try {
            await clearResultsStorage();
            if (app.toasts) {
              app.toasts.notifySystem("Storage", "Cleared results folder.", "success", {
                key: "storage:clear-results",
                cooldown: 0,
                duration: 5200,
              });
            }
          } catch (error) {
            console.warn("Failed to clear results", error);
            if (app.toasts) {
              app.toasts.notifySystem("Storage", "Can’t clear results folder. Try again.", "error", {
                key: "storage:clear-results:error",
                cooldown: 1500,
              });
            }
          } finally {
            if (app.state) {
              await app.state.refreshState();
            }
            button.removeAttribute("disabled");
          }
        }
      });
    });

    app.storageActions = {
      __initialized: true,
    };
  }

  app.storageActions = app.storageActions || {};
  app.storageActions.init = initStorageActions;
})();
