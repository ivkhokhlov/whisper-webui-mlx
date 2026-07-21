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
    historyPagination,
    historyLoadMore,
    historyPageStatus,
    queueCountEls,
  } = app.dom || {};

  const HISTORY_PAGE_SIZE = 50;
  let historyItems = [];
  let historyPage = null;
  let historyLoaded = false;
  let historyLoading = false;
  let historyRequestId = 0;
  let historyReloadPending = false;

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
    historyClearButton.setAttribute("data-item-count", String(count));
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
      const count = historyCount(history);
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

  function historyResultsIndex(jobs) {
    return Object.fromEntries((jobs || []).map((job) => [job.id, job.results || []]));
  }

  function updateHistoryPagination() {
    if (!historyPagination || !historyLoadMore) {
      return;
    }
    const hasMore = Boolean(historyPage && historyPage.has_more);
    historyPagination.hidden = !historyLoaded || (!hasMore && historyItems.length === 0);
    historyLoadMore.hidden = !hasMore;
    historyLoadMore.disabled = historyLoading;
    if (historyPageStatus) {
      const total = historyPage ? Number(historyPage.total || 0) : 0;
      historyPageStatus.textContent = historyLoaded
        ? `Showing ${historyItems.length} of ${total}`
        : "";
    }
  }

  function renderHistory(listEl, placeholderEl, jobs, resultsByJob) {
    if (!listEl || !placeholderEl) {
      return;
    }
    if (!jobs || jobs.length === 0) {
      listEl.innerHTML = "";
      const total = historyPage ? Number(historyPage.total || 0) : 0;
      placeholderEl.style.display = total === 0 ? "grid" : "none";
      updateHistoryClearState(total);
      if (app.historyView) {
        app.historyView.apply({ persist: false, loaded: historyLoaded, totalCount: total });
      }
      updateHistoryPagination();
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
    const total = historyPage ? Number(historyPage.total || 0) : jobs.length;
    updateHistoryClearState(total);
    if (app.historyView) {
      app.historyView.apply({ persist: false, loaded: historyLoaded, totalCount: total });
    }
    updateHistoryPagination();
  }

  function currentHistoryFilters() {
    return {
      query: app.dom?.historySearch?.value || "",
      status: app.dom?.historyStatus?.value || "all",
      sort: app.dom?.historySort?.value || "newest",
    };
  }

  async function loadHistory(options = {}) {
    const reset = options.reset !== false;
    if (historyLoading) {
      if (!reset) {
        return;
      }
      historyReloadPending = true;
      return;
    }
    if (!reset && !(historyPage && historyPage.has_more)) {
      return;
    }
    if (reset) {
      historyItems = [];
      historyPage = null;
    }
    historyLoading = true;
    updateHistoryPagination();
    const requestId = ++historyRequestId;
    const filters = currentHistoryFilters();
    const params = new URLSearchParams({
      limit: String(HISTORY_PAGE_SIZE),
      offset: String(reset ? 0 : historyItems.length),
      query: filters.query,
      status: filters.status,
      sort: filters.sort,
    });
    try {
      const response = await fetch(`/api/browser/history?${params}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`History request failed with HTTP ${response.status}`);
      }
      const payload = await response.json();
      if (requestId !== historyRequestId) {
        return;
      }
      historyItems = reset ? payload.items || [] : historyItems.concat(payload.items || []);
      historyPage = payload.page || null;
      historyLoaded = true;
      renderHistory(historyList, historyPlaceholder, historyItems, historyResultsIndex(historyItems));
      updateSettingsStorageState(null, { count: historyPage ? historyPage.total : 0 });
    } catch (error) {
      if (requestId === historyRequestId) {
        console.warn("Failed to load history", error);
      }
    } finally {
      if (requestId === historyRequestId) {
        historyLoading = false;
        updateHistoryPagination();
        if (historyReloadPending) {
          historyReloadPending = false;
          loadHistory({ reset: true });
        }
      }
    }
  }

  async function refreshState() {
    try {
      const response = await fetch("/api/browser/state", { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      const queue = payload.queue || [];
      const workerState = payload.worker && payload.worker.status ? payload.worker.status : "Idle";
      renderQueue(queueList, queuePlaceholder, queue, payload.worker || null);
      if (app.toasts) {
        app.toasts.handleNotifications(payload.recent_history || [], {});
      }
      updateSettingsStorageState(queue, { count: payload.history_count || 0 });
      updateHistoryClearState(payload.history_count || 0);
      if (historyLoaded && historyPage) {
        const previousTotal = Number(historyPage.total || 0);
        const nextTotal = Number(payload.history_count || 0);
        if (previousTotal !== nextTotal) {
          loadHistory({ reset: true });
        }
      }
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

  function historyCount(history) {
    if (Array.isArray(history)) {
      return history.length;
    }
    return history && Number.isFinite(Number(history.count)) ? Number(history.count) : 0;
  }

  function initState() {
    if (app.state && app.state.__initialized) {
      return;
    }

    app.state = {
      __initialized: true,
      refreshState,
      loadHistory,
      renderQueue,
      renderHistory,
      updateQueueCount,
      updateHistoryClearState,
      updateSettingsStorageState,
      updateUploadDensity,
    };
    if (historyLoadMore) {
      historyLoadMore.addEventListener("click", () => loadHistory({ reset: false }));
    }
    window.addEventListener("mlx-ui:tab-activated", (event) => {
      if (event.detail && event.detail.tab === "history" && !historyLoaded) {
        loadHistory({ reset: true });
      }
    });
    const activeHistoryPanel = document.querySelector('[data-panel="history"].is-active');
    if (activeHistoryPanel) {
      loadHistory({ reset: true });
    }
  }

  app.state = app.state || {};
  app.state.init = initState;
})();
