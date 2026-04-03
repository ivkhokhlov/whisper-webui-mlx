(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const { queueList } = app.dom || {};

  async function deleteQueuedJob(jobId) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to remove job.");
    }
  }

  function initQueueActions() {
    if (app.queueActions && app.queueActions.__initialized) {
      return;
    }

    if (queueList) {
      queueList.addEventListener("click", async (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const button = target.closest(".job-bin");
        if (!button) {
          return;
        }
        const jobId = button.getAttribute("data-job-id");
        if (!jobId) {
          return;
        }
        const row = button.closest(".job-row");
        const filenameEl = row ? row.querySelector(".job-name") : null;
        const filename = filenameEl ? filenameEl.textContent.trim() : "";
        const confirmed = app.modals
          ? await app.modals.openConfirmModal({
              title: "Remove from queue",
              message: filename
                ? `Remove “${filename}” from the queue?\nThis deletes the local copy stored for processing.`
                : "Remove this item from the queue?\nThis deletes the local copy stored for processing.",
              confirmText: "Remove",
              cancelText: "Cancel",
            })
          : false;
        if (!confirmed) {
          return;
        }
        button.setAttribute("disabled", "disabled");
        try {
          await deleteQueuedJob(jobId);
          if (app.toasts) {
            app.toasts.notifySystem(
              "Queue",
              filename ? `Removed “${filename}”.` : "Removed from queue.",
              "success",
              {
                key: "queue:remove",
                cooldown: 0,
                duration: 5200,
              }
            );
          }
        } catch (error) {
          console.warn("Failed to remove queued job", error);
          if (app.toasts) {
            app.toasts.notifySystem(
              "Queue",
              filename
                ? `Couldn’t remove “${filename}”. Try again.`
                : "Couldn’t remove from queue. Try again.",
              "error",
              {
                key: "queue:remove:error",
                cooldown: 1500,
              }
            );
          }
        } finally {
          if (app.state) {
            await app.state.refreshState();
          }
        }
      });
    }

    app.queueActions = {
      __initialized: true,
    };
  }

  app.queueActions = app.queueActions || {};
  app.queueActions.init = initQueueActions;
})();

