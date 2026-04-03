(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const {
    historyList,
    historySearch,
    historyStatus,
    historySort,
    historyViewSummary,
    historyFilterEmpty,
    historyClearFilters,
  } = app.dom || {};

  const HISTORY_VIEW_STORAGE_KEY =
    (app.constants && app.constants.HISTORY_VIEW_STORAGE_KEY) || "mlx-ui:history-view";
  const HISTORY_SORT_VALUES =
    (app.constants && app.constants.HISTORY_SORT_VALUES) || new Set(["newest", "oldest", "name"]);
  const HISTORY_STATUS_VALUES =
    (app.constants && app.constants.HISTORY_STATUS_VALUES) || new Set(["all", "done", "failed"]);

  function loadHistoryViewState() {
    const defaults = {
      query: "",
      status: "all",
      sort: "newest",
    };
    try {
      const raw = localStorage.getItem(HISTORY_VIEW_STORAGE_KEY);
      if (!raw) {
        return defaults;
      }
      const parsed = JSON.parse(raw);
      const query = typeof parsed.query === "string" ? parsed.query : defaults.query;
      const status = HISTORY_STATUS_VALUES.has(parsed.status) ? parsed.status : defaults.status;
      const sort = HISTORY_SORT_VALUES.has(parsed.sort) ? parsed.sort : defaults.sort;
      return {
        query,
        status,
        sort,
      };
    } catch (error) {
      return defaults;
    }
  }

  function persistHistoryViewState() {
    if (!historySearch || !historyStatus || !historySort) {
      return;
    }
    const payload = {
      query: historySearch.value || "",
      status: historyStatus.value || "all",
      sort: historySort.value || "newest",
    };
    try {
      localStorage.setItem(HISTORY_VIEW_STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
      // localStorage may be disabled; UI should still work.
    }
  }

  function parseIsoMs(value) {
    if (!value) {
      return 0;
    }
    const ms = Date.parse(value);
    return Number.isNaN(ms) ? 0 : ms;
  }

  function getHistoryRowMeta(row) {
    const filenameEl = row ? row.querySelector(".history-filename") : null;
    const filename = filenameEl ? filenameEl.textContent.trim() : "";
    const filenameLower = filename.toLowerCase();
    const timeMetaEl = row ? row.querySelector("[data-time-meta]") : null;
    const status = timeMetaEl
      ? (timeMetaEl.getAttribute("data-status") || "").toLowerCase()
      : "";
    const createdAt = timeMetaEl ? timeMetaEl.getAttribute("data-created-at") || "" : "";
    const startedAt = timeMetaEl ? timeMetaEl.getAttribute("data-started-at") || "" : "";
    const completedAt = timeMetaEl ? timeMetaEl.getAttribute("data-completed-at") || "" : "";
    const anchorIso = completedAt || startedAt || createdAt;
    return {
      filename,
      filenameLower,
      status,
      anchorMs: parseIsoMs(anchorIso),
    };
  }

  function updateHistorySummary(visibleCount, totalCount, state) {
    if (!historyViewSummary) {
      return;
    }
    if (!totalCount) {
      historyViewSummary.textContent = "";
      historyViewSummary.hidden = true;
      return;
    }
    const query = String(state.query || "").trim();
    const isDefault = !query && state.status === "all" && state.sort === "newest";
    if (isDefault) {
      historyViewSummary.textContent = "";
      historyViewSummary.hidden = true;
      return;
    }
    historyViewSummary.hidden = false;
    if (visibleCount === totalCount) {
      historyViewSummary.textContent = `${totalCount} ${totalCount === 1 ? "item" : "items"}`;
      return;
    }
    historyViewSummary.textContent = `Showing ${visibleCount} of ${totalCount}`;
  }

  function updateHistoryFilteredEmpty(isVisible, state) {
    if (!historyFilterEmpty) {
      return;
    }
    historyFilterEmpty.hidden = !isVisible;
    if (!isVisible) {
      return;
    }
    const body = historyFilterEmpty.querySelector("#history-filter-body");
    if (!body) {
      return;
    }
    const parts = [];
    const query = String(state.query || "").trim();
    if (query) {
      parts.push(`“${query}”`);
    }
    if (state.status && state.status !== "all") {
      parts.push(`status: ${state.status}`);
    }
    const context = parts.length ? ` for ${parts.join(" · ")}` : "";
    body.textContent = `No history items match${context}. Try another search or clear filters.`;
  }

  function applyHistoryView(options = {}) {
    if (!historyList || !historySearch || !historyStatus || !historySort) {
      return;
    }
    const state = {
      query: historySearch.value || "",
      status: historyStatus.value || "all",
      sort: historySort.value || "newest",
    };
    const query = state.query.trim().toLowerCase();
    const statusFilter = state.status;
    const sortMode = state.sort;

    const rows = Array.from(historyList.querySelectorAll(".history-row"));
    const totalCount = rows.length;
    if (totalCount === 0) {
      historyList.style.display = "grid";
      updateHistoryFilteredEmpty(false, state);
      updateHistorySummary(0, 0, state);
      return;
    }

    const metaRows = rows.map((row) => {
      const meta = getHistoryRowMeta(row);
      return { row, meta };
    });

    metaRows.sort((a, b) => {
      if (sortMode === "name") {
        const aName = a.meta.filenameLower;
        const bName = b.meta.filenameLower;
        const byName = aName.localeCompare(bName, undefined, { sensitivity: "base" });
        if (byName !== 0) {
          return byName;
        }
        return b.meta.anchorMs - a.meta.anchorMs;
      }
      if (sortMode === "oldest") {
        return a.meta.anchorMs - b.meta.anchorMs;
      }
      return b.meta.anchorMs - a.meta.anchorMs;
    });

    const fragment = document.createDocumentFragment();
    let visibleCount = 0;
    metaRows.forEach(({ row, meta }) => {
      const matchesQuery = !query || meta.filenameLower.includes(query);
      const matchesStatus = statusFilter === "all" || meta.status === statusFilter;
      const matches = matchesQuery && matchesStatus;
      row.hidden = !matches;
      if (matches) {
        visibleCount += 1;
      }
      fragment.appendChild(row);
    });
    historyList.appendChild(fragment);

    if (visibleCount === 0) {
      historyList.style.display = "none";
      updateHistoryFilteredEmpty(true, state);
    } else {
      historyList.style.display = "grid";
      updateHistoryFilteredEmpty(false, state);
    }
    updateHistorySummary(visibleCount, totalCount, state);
    if (options.persist !== false) {
      persistHistoryViewState();
    }
  }

  function initHistoryView() {
    if (app.historyView && app.historyView.__initialized) {
      return;
    }

    if (historySearch && historyStatus && historySort) {
      const initialView = loadHistoryViewState();
      historySearch.value = initialView.query;
      historyStatus.value = initialView.status;
      historySort.value = initialView.sort;
      applyHistoryView({ persist: false });

      let historySearchTimeout = null;
      historySearch.addEventListener("input", () => {
        window.clearTimeout(historySearchTimeout);
        historySearchTimeout = window.setTimeout(() => {
          applyHistoryView();
        }, 120);
      });
      historyStatus.addEventListener("change", () => applyHistoryView());
      historySort.addEventListener("change", () => applyHistoryView());
    }

    if (historyClearFilters) {
      historyClearFilters.addEventListener("click", () => {
        if (historySearch) {
          historySearch.value = "";
        }
        if (historyStatus) {
          historyStatus.value = "all";
        }
        if (historySort) {
          historySort.value = "newest";
        }
        applyHistoryView();
        if (historySearch) {
          historySearch.focus();
        }
      });
    }

    app.historyView = {
      __initialized: true,
      apply: applyHistoryView,
    };
  }

  app.historyView = app.historyView || {};
  app.historyView.init = initHistoryView;
})();
