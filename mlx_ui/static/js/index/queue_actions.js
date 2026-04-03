(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const { queueList } = app.dom || {};

  async function readErrorMessage(response, fallbackMessage) {
    const raw = await response.text();
    if (!raw) {
      return fallbackMessage;
    }
    try {
      const payload = JSON.parse(raw);
      if (payload && typeof payload.detail === "string" && payload.detail.trim()) {
        return payload.detail.trim();
      }
    } catch (_error) {
      // Fall back to the raw response body below.
    }
    return raw || fallbackMessage;
  }

  async function deleteQueuedJob(jobId) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Failed to remove job."));
    }
  }

  async function cancelRunningJob(jobId) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Failed to stop job."));
    }
    return response.json();
  }

  function getRowFilename(button) {
    const row = button.closest(".job-row");
    const filenameEl = row ? row.querySelector(".job-name") : null;
    return filenameEl ? filenameEl.textContent.trim() : "";
  }

  async function handleRemoveAction(button) {
    const jobId = button.getAttribute("data-job-id");
    if (!jobId) {
      return;
    }
    const filename = getRowFilename(button);
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
  }

  async function handleCancelAction(button) {
    const jobId = button.getAttribute("data-job-id");
    if (!jobId || button.disabled) {
      return;
    }
    const filename = getRowFilename(button);
    const confirmed = app.modals
      ? await app.modals.openConfirmModal({
          title: "Stop active task",
          message: filename
            ? `Stop “${filename}”?\nPartial outputs will be discarded.`
            : "Stop the active task?\nPartial outputs will be discarded.",
          confirmText: "Stop",
          cancelText: "Keep running",
        })
      : false;
    if (!confirmed) {
      return;
    }
    button.disabled = true;
    try {
      const payload = await cancelRunningJob(jobId);
      const state = payload && payload.state ? String(payload.state) : "stopping";
      if (app.toasts) {
        app.toasts.notifySystem(
          "Worker",
          state === "cancelled"
            ? filename
              ? `Stopped “${filename}”.`
              : "Stopped the active task."
            : filename
              ? `Stopping “${filename}”…`
              : "Stopping the active task…",
          "success",
          {
            key: "worker:cancel",
            cooldown: 0,
            duration: 5200,
          }
        );
      }
    } catch (error) {
      console.warn("Failed to stop running job", error);
      if (app.toasts) {
        app.toasts.notifySystem(
          "Worker",
          filename
            ? `Couldn’t stop “${filename}”. Try again.`
            : "Couldn’t stop the active task. Try again.",
          "error",
          {
            key: "worker:cancel:error",
            cooldown: 1500,
          }
        );
      }
    } finally {
      if (app.state) {
        await app.state.refreshState();
      }
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
        const action = button.getAttribute("data-job-action");
        if (action === "remove") {
          await handleRemoveAction(button);
        } else if (action === "cancel") {
          await handleCancelAction(button);
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
