(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }
  if (app.time) {
    return;
  }

  const relativeFormatter =
    typeof Intl !== "undefined" && Intl.RelativeTimeFormat
      ? new Intl.RelativeTimeFormat(undefined, { numeric: "auto", style: "short" })
      : null;

  function formatRelative(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
      return "";
    }
    const diffMs = date.getTime() - Date.now();
    const absMs = Math.abs(diffMs);
    if (absMs < 45000) {
      return "just now";
    }
    const units = [
      ["year", 31536000000],
      ["month", 2592000000],
      ["day", 86400000],
      ["hour", 3600000],
      ["minute", 60000],
    ];
    for (const [unit, unitMs] of units) {
      if (absMs >= unitMs) {
        const value = Math.round(diffMs / unitMs);
        if (relativeFormatter) {
          return relativeFormatter.format(value, unit);
        }
        const rounded = Math.abs(value);
        return `${rounded} ${unit}${rounded === 1 ? "" : "s"} ${
          value < 0 ? "ago" : "from now"
        }`;
      }
    }
    const seconds = Math.round(diffMs / 1000);
    if (relativeFormatter) {
      return relativeFormatter.format(seconds, "second");
    }
    const absSeconds = Math.abs(seconds);
    return `${absSeconds} sec ${seconds < 0 ? "ago" : "from now"}`;
  }

  function formatTimestamp(isoString) {
    if (!isoString) {
      return { absolute: "", relative: "" };
    }
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) {
      return { absolute: isoString, relative: "" };
    }
    let absolute = "";
    try {
      absolute = date.toLocaleString([], {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (error) {
      absolute = date.toLocaleString();
    }
    return { absolute, relative: formatRelative(date) };
  }

  function formatDuration(ms) {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const paddedMinutes = String(minutes).padStart(2, "0");
    const paddedSeconds = String(seconds).padStart(2, "0");
    if (hours > 0) {
      return `${String(hours).padStart(2, "0")}:${paddedMinutes}:${paddedSeconds}`;
    }
    return `${paddedMinutes}:${paddedSeconds}`;
  }

  function formatElapsed(isoString) {
    if (!isoString) {
      return "";
    }
    const startedAt = new Date(isoString);
    if (Number.isNaN(startedAt.getTime())) {
      return "";
    }
    return formatDuration(Date.now() - startedAt.getTime());
  }

  function calculateDuration(startIso, endIso) {
    if (!startIso || !endIso) {
      return "";
    }
    const start = new Date(startIso);
    const end = new Date(endIso);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      return "";
    }
    const diff = Math.max(0, end.getTime() - start.getTime());
    if (!diff) {
      return "";
    }
    return formatDuration(diff);
  }

  function formatTimeMeta(status, createdAt, startedAt, completedAt) {
    const normalized = String(status || "").toLowerCase();
    let label = "Updated";
    if (normalized === "done") {
      label = "Completed";
    } else if (normalized === "failed") {
      label = "Failed";
    } else if (normalized === "running") {
      label = "Running";
    } else if (normalized === "queued") {
      label = "Queued";
    }
    const anchorIso =
      normalized === "done" || normalized === "failed"
        ? completedAt || startedAt || createdAt
        : normalized === "running"
          ? startedAt || createdAt
          : createdAt || startedAt || completedAt;
    const { absolute, relative } = formatTimestamp(anchorIso);
    const timeText = relative || absolute;
    if (!timeText) {
      return { text: "", title: "" };
    }
    let text = `${label} ${timeText}`;
    if ((normalized === "done" || normalized === "failed") && completedAt) {
      const duration = calculateDuration(startedAt || createdAt, completedAt);
      if (duration) {
        text += ` · ${duration}`;
      }
    }
    return { text, title: absolute };
  }

  function hydrateTimeMeta(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-time-meta]").forEach((element) => {
      const status = element.getAttribute("data-status") || "";
      const createdAt = element.getAttribute("data-created-at") || "";
      const startedAt = element.getAttribute("data-started-at") || "";
      const completedAt = element.getAttribute("data-completed-at") || "";
      const meta = formatTimeMeta(status, createdAt, startedAt, completedAt);
      if (!meta.text) {
        return;
      }
      element.textContent = meta.text;
      if (meta.title) {
        element.setAttribute("title", meta.title);
      }
    });
  }

  function hydrateTimestamps(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-iso][data-label]").forEach((element) => {
      const isoString = element.getAttribute("data-iso");
      const label = element.getAttribute("data-label") || "";
      const { absolute, relative } = formatTimestamp(isoString);
      if (!absolute) {
        return;
      }
      const relativeText = relative ? ` · ${relative}` : "";
      element.textContent = `${label} ${absolute}${relativeText}`;
    });
  }

  function hydrateElapsed(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-started-at]").forEach((element) => {
      const isoString = element.getAttribute("data-started-at");
      if (!isoString) {
        element.textContent = "";
        return;
      }
      const elapsed = formatElapsed(isoString);
      element.textContent = elapsed ? `Elapsed ${elapsed}` : "Elapsed …";
    });
  }

  app.time = {
    formatTimestamp,
    formatDuration,
    formatElapsed,
    calculateDuration,
    formatTimeMeta,
    hydrateTimeMeta,
    hydrateTimestamps,
    hydrateElapsed,
  };
})();

