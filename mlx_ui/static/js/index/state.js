(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const {
    queueList,
    queuePlaceholder,
    historyList,
    historyPlaceholder,
    workerStatus,
    historyClearButton,
    queueCountEls,
  } = app.dom || {};

  function updateQueueCount(count) {
    const label = count === 1 ? "file" : "files";
    (queueCountEls || []).forEach((element) => {
      element.textContent = `${count} ${label} queued`;
    });
  }

  function updateHistoryClearState(count) {
    if (!historyClearButton) {
      return;
    }
    historyClearButton.disabled = !count;
  }

  function updateUploadDensity(queue, worker) {
    if (!app.uploads || typeof app.uploads.setQueueBusy !== "function") {
      return;
    }
    const queueCount = Array.isArray(queue) ? queue.length : 0;
    const workerStatus = worker && worker.status ? String(worker.status) : "";
    const isBusy = queueCount > 0 || workerStatus === "Running" || workerStatus === "Stopping";
    app.uploads.setQueueBusy(isBusy);
  }

  function updateSettingsStorageState(queue, history) {
    const historyButton = document.querySelector("[data-storage-action='clear-history']");
    const historyHint = document.querySelector("[data-storage-history-hint]");
    if (historyButton instanceof HTMLButtonElement) {
      const count = Array.isArray(history) ? history.length : 0;
      historyButton.disabled = !count;
      historyButton.setAttribute("data-item-count", String(count));
      historyButton.textContent = "Delete history";
      if (historyHint) {
        historyHint.textContent = count
          ? `Deletes ${count} saved ${count === 1 ? "entry" : "entries"}.`
          : "No saved history.";
      }
    }

    const uploadsButton = document.querySelector("[data-storage-action='clear-uploads']");
    const uploadsHint = document.querySelector("[data-storage-uploads-hint]");
    if (uploadsButton instanceof HTMLButtonElement) {
      const count = Array.isArray(queue) ? queue.length : 0;
      uploadsButton.disabled = count > 0;
      uploadsButton.setAttribute("data-item-count", String(count));
      if (uploadsHint) {
        uploadsHint.textContent = count
          ? "Queue must be empty first."
          : "Deletes local processing copies.";
      }
    }
  }

  function renderQueue(listEl, placeholderEl, jobs, worker) {
    if (!listEl) {
      return;
    }
    if (!jobs || jobs.length === 0) {
      listEl.innerHTML = "";
      if (placeholderEl) {
        placeholderEl.style.display = "grid";
      }
      return;
    }
    if (placeholderEl) {
      placeholderEl.style.display = "none";
    }
    const hasRunning = jobs.some((job) => job.status === "running");
    const workerJobId = worker && worker.job_id ? String(worker.job_id) : "";
    let queuedIndex = 0;
    const rendered = [];
    for (const job of jobs) {
      const isRunning = job.status === "running";
      const workerState = isRunning && workerJobId && String(job.id) === workerJobId ? worker : null;
      let queuePosition = 0;
      if (job.status === "queued") {
        queuedIndex += 1;
        queuePosition = queuedIndex + (hasRunning ? 1 : 0);
      }
      rendered.push(
        app.renderJobs.buildQueueRow(job, {
          queuePosition,
          isRunning,
          workerState,
        })
      );
    }
    listEl.innerHTML = rendered.join("");
    if (app.time) {
      app.time.hydrateTimestamps(listEl);
      app.time.hydrateElapsed(listEl);
    }
  }

  function renderHistory(listEl, placeholderEl, jobs, resultsByJob) {
    if (!listEl || !placeholderEl) {
      return;
    }
    if (!jobs || jobs.length === 0) {
      listEl.innerHTML = "";
      placeholderEl.style.display = "grid";
      updateHistoryClearState(0);
      if (app.historyView) {
        app.historyView.apply({ persist: false });
      }
      return;
    }
    const openJobs = new Set();
    const openMenus = new Set();
    listEl.querySelectorAll(".job-details[open]").forEach((details) => {
      const row = details.closest(".history-row");
      const jobId = row ? row.getAttribute("data-job-id") : "";
      if (jobId) {
        openJobs.add(jobId);
      }
    });
    listEl.querySelectorAll(".job-menu[open]").forEach((menu) => {
      const row = menu.closest(".history-row");
      const jobId = row ? row.getAttribute("data-job-id") : "";
      if (jobId) {
        openMenus.add(jobId);
      }
    });
    placeholderEl.style.display = "none";
    listEl.innerHTML = jobs
      .map((job) => app.renderJobs.buildHistoryRow(job, resultsByJob, openJobs, openMenus))
      .join("");
    if (app.time) {
      app.time.hydrateTimestamps(listEl);
      app.time.hydrateTimeMeta(listEl);
    }
    if (app.modals) {
      app.modals.wireHistoryDetails(listEl);
      app.modals.wireHistoryMenus(listEl);
    }
    updateHistoryClearState(jobs.length);
    if (app.historyView) {
      app.historyView.apply({ persist: false });
    }
  }

  async function refreshState() {
    try {
      const response = await fetch("/api/state", { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      const resultsByJob = payload.results_by_job || {};
      const queue = payload.queue || [];
      const workerState = payload.worker && payload.worker.status ? payload.worker.status : "Idle";
      renderQueue(queueList, queuePlaceholder, queue, payload.worker || null);
      renderHistory(historyList, historyPlaceholder, payload.history || [], resultsByJob);
      if (app.toasts) {
        app.toasts.handleNotifications(payload.history || [], resultsByJob);
      }
      updateSettingsStorageState(queue, payload.history || []);
      updateQueueCount(queue.filter((job) => job.status === "queued").length);
      updateUploadDensity(queue, payload.worker || null);
      if (payload.worker && workerStatus && app.workerCard) {
        app.workerCard.setState(payload.worker);
      } else if (workerStatus) {
        workerStatus.textContent = workerState || "Idle";
      }
    } catch (error) {
      console.warn("Failed to refresh state", error);
    }
  }

  function initState() {
    if (app.state && app.state.__initialized) {
      return;
    }

    app.state = {
      __initialized: true,
      refreshState,
      renderQueue,
      renderHistory,
      updateQueueCount,
      updateHistoryClearState,
      updateSettingsStorageState,
      updateUploadDensity,
    };
  }

  app.state = app.state || {};
  app.state.init = initState;
})();
