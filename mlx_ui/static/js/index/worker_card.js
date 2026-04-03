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

  function buildWorkerContext(currentJobUi, isRunning) {
    if (!isRunning || !currentJobUi) {
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
      workerCardEl.classList.toggle("is-running", status === "Running");
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
    const isRunning = status === "Running" && Boolean(filename);
    if (workerCurrent) {
      workerCurrent.hidden = !isRunning;
    }
    if (workerFilename) {
      if (isRunning) {
        workerFilename.textContent = filename;
        workerFilename.title = filename;
        workerFilename.setAttribute("aria-label", filename);
      } else {
        workerFilename.textContent = "";
        workerFilename.removeAttribute("title");
        workerFilename.setAttribute("aria-label", "");
      }
    }

    workerStartedAt = isRunning ? worker.started_at || "" : "";
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
      const contextText = buildWorkerContext(currentJobUi, isRunning);
      workerContext.textContent = contextText;
      workerContext.hidden = !contextText;
    }
  }

  app.workerCard = {
    updateElapsed: updateWorkerElapsed,
    setState: setWorkerCardState,
  };
})();
