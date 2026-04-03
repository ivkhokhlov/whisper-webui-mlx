(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }
  if (app.workerCard) {
    return;
  }

  const {
    workerCard: workerCardEl,
    workerStatus,
    workerIndicator,
  } = app.dom || {};

  function updateWorkerElapsed() {
    // Worker timing is shown in the active queue row, not in the header card.
  }

  function setWorkerCardState(worker) {
    if (!worker || !workerStatus) {
      return;
    }
    const status = worker.status || "Idle";
    workerStatus.textContent = status;
    if (workerCardEl) {
      const normalizedStatus = String(status).trim().toLowerCase();
      workerCardEl.classList.remove(
        "is-running",
        "is-stopping",
        "is-paused",
        "is-failed",
        "is-error"
      );
      if (normalizedStatus === "running") {
        workerCardEl.classList.add("is-running");
      } else if (normalizedStatus === "stopping") {
        workerCardEl.classList.add("is-stopping");
      } else if (normalizedStatus === "paused") {
        workerCardEl.classList.add("is-paused");
      } else if (normalizedStatus === "failed") {
        workerCardEl.classList.add("is-failed");
      } else if (normalizedStatus === "error") {
        workerCardEl.classList.add("is-error");
      }
    }
    if (workerIndicator) {
      const normalizedStatus = String(status).trim().toLowerCase();
      // Keep the indicator mounted for all states so the pill never "jumps" in width.
      workerIndicator.hidden = false;
      workerIndicator.classList.remove("is-running", "is-stopping");
      if (normalizedStatus === "running") {
        workerIndicator.classList.add("is-running");
      } else if (normalizedStatus === "stopping") {
        workerIndicator.classList.add("is-stopping");
      }
    }
  }

  app.workerCard = {
    updateElapsed: updateWorkerElapsed,
    setState: setWorkerCardState,
  };
})();
