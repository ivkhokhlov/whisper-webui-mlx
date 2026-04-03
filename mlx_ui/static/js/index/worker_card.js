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
    workerCurrent,
    workerFilename,
    workerMeta,
    workerQueued,
    workerElapsed,
    workerContext,
    workerStopButton,
  } = app.dom || {};

  let workerStartedAt = workerElapsed ? workerElapsed.dataset.startedAt || "" : "";

  function updateWorkerElapsed() {
    if (!workerElapsed) {
      return;
    }
    if (!workerStartedAt) {
      workerElapsed.textContent = "";
      return;
    }
    const elapsed = app.time ? app.time.formatElapsed(workerStartedAt) : "";
    workerElapsed.textContent = elapsed ? `Elapsed ${elapsed}` : "Elapsed …";
  }

  function buildWorkerContext(currentJobUi, isActive) {
    if (!isActive || !currentJobUi) {
      return "";
    }

    const parts = [];
    const engine =
      currentJobUi.effective_engine || currentJobUi.requested_engine || null;
    if (engine) {
      const baseLabel = engine.short_label || engine.label || "";
      if (baseLabel) {
        parts.push(engine.cloud ? `${baseLabel} cloud` : baseLabel);
      }
    }

    const languageLabel =
      currentJobUi.language && currentJobUi.language.label
        ? String(currentJobUi.language.label)
        : "";
    if (languageLabel && languageLabel !== "Detect automatically") {
      parts.push(languageLabel);
    }

    return parts.slice(0, 2).join(" · ");
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

    const queuedCount =
      typeof worker.queue_length === "number"
        ? worker.queue_length
        : Number.isFinite(Number(worker.queue_length))
          ? Number(worker.queue_length)
          : 0;
    if (workerQueued) {
      workerQueued.textContent = `${queuedCount} queued`;
      workerQueued.hidden = queuedCount <= 0;
    }

    const filename = worker.filename || "";
    const isActive = (status === "Running" || status === "Stopping") && Boolean(filename);
    if (workerCurrent) {
      workerCurrent.hidden = !isActive;
    }
    if (workerFilename) {
      if (isActive) {
        workerFilename.textContent = filename;
        workerFilename.title = filename;
        workerFilename.setAttribute("aria-label", filename);
      } else {
        workerFilename.textContent = "";
        workerFilename.removeAttribute("title");
        workerFilename.setAttribute("aria-label", "");
      }
    }

    workerStartedAt = isActive ? worker.started_at || "" : "";
    if (workerElapsed) {
      workerElapsed.dataset.startedAt = workerStartedAt;
      workerElapsed.hidden = !workerStartedAt;
      updateWorkerElapsed();
    }

    const currentJobUi = worker.current_job_ui || null;
    if (workerMeta) {
      workerMeta.hidden = queuedCount <= 0 && !workerStartedAt;
    }
    if (workerContext) {
      const contextText = buildWorkerContext(currentJobUi, isActive);
      workerContext.textContent = contextText;
      workerContext.hidden = !contextText;
    }
    if (workerStopButton) {
      const jobId = worker.job_id ? String(worker.job_id) : "";
      const canCancel = Boolean(worker.can_cancel);
      const stopLabel = status === "Stopping" ? "Stopping current task" : "Stop current task";
      workerStopButton.hidden = !jobId || !isActive;
      workerStopButton.dataset.jobId = jobId;
      workerStopButton.disabled = !canCancel;
      workerStopButton.setAttribute("aria-label", stopLabel);
      workerStopButton.title = stopLabel;
      workerStopButton.classList.toggle("is-pending", isActive && !canCancel);
    }
  }

  app.workerCard = {
    updateElapsed: updateWorkerElapsed,
    setState: setWorkerCardState,
  };
})();
