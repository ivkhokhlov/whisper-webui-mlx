(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const { historyList, historyClearButton } = app.dom || {};

  async function deleteHistoryJob(jobId) {
    const response = await fetch(`/api/history/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      payload = {};
    }
    if (!response.ok) {
      const message = payload && payload.detail ? payload.detail : "Failed to delete history item.";
      throw new Error(message);
    }
    return payload;
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

  function getHistoryRowSummary(row) {
    const filenameEl = row ? row.querySelector(".history-filename") : null;
    const filename = filenameEl ? filenameEl.textContent.trim() : "Untitled file";
    const timeEl = row ? row.querySelector("[data-time-meta]") : null;
    const createdAt = timeEl ? timeEl.getAttribute("data-created-at") || "" : "";
    const startedAt = timeEl ? timeEl.getAttribute("data-started-at") || "" : "";
    const completedAt = timeEl ? timeEl.getAttribute("data-completed-at") || "" : "";
    const anchorIso = completedAt || startedAt || createdAt;
    const absolute = app.time ? app.time.formatTimestamp(anchorIso).absolute : "";
    const duration = app.time
      ? app.time.calculateDuration(startedAt || createdAt, completedAt)
      : "";
    const outputLinks = row ? Array.from(row.querySelectorAll(".detail-result-link")) : [];
    const outputs = outputLinks
      .map((link) => link.textContent.trim())
      .filter((text) => Boolean(text));
    return {
      filename,
      absoluteTime: absolute,
      duration,
      outputs,
    };
  }

  function buildHistoryDeleteMessage(summary) {
    const timeParts = [];
    if (summary.absoluteTime) {
      timeParts.push(summary.absoluteTime);
    }
    if (summary.duration) {
      timeParts.push(summary.duration);
    }
    const timeText = timeParts.length ? ` (${timeParts.join(" · ")})` : "";
    const lines = [
      `Delete "${summary.filename}"${timeText}?`,
      "This removes the job from History and deletes its stored outputs (transcripts/logs) from disk.",
    ];
    if (summary.outputs.length) {
      lines.push(`Outputs: ${summary.outputs.join(", ")}`);
    }
    lines.push("Downloaded files, clipboard contents, and Telegram copies aren't removed.");
    return lines.join("\n");
  }

  function buildHistoryClearMessage(count) {
    const label = count === 1 ? "item" : "items";
    return [
      "Delete all results?",
      `This will delete ${count} completed ${label} and remove their stored outputs (transcripts/logs) from disk.`,
      "This can't be undone.",
      "Downloaded files, clipboard contents, and Telegram copies aren't removed.",
    ].join("\n");
  }

  function initHistoryActions() {
    if (app.historyActions && app.historyActions.__initialized) {
      return;
    }

    if (historyClearButton) {
      historyClearButton.addEventListener("click", async () => {
        if (historyClearButton.disabled) {
          return;
        }
        const count = historyList ? historyList.querySelectorAll(".history-row").length : 0;
        if (!count) {
          if (app.state) {
            app.state.updateHistoryClearState(0);
          }
          return;
        }
        const confirmed = app.modals
          ? await app.modals.openConfirmModal({
              title: "Delete completed history",
              message: buildHistoryClearMessage(count),
              confirmText: "Delete all",
              cancelText: "Cancel",
            })
          : false;
        if (!confirmed) {
          return;
        }
        historyClearButton.setAttribute("disabled", "disabled");
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
          console.warn("Failed to clear history", error);
          if (app.toasts) {
            app.toasts.notifySystem("History", "Couldn’t delete history. Try again.", "error", {
              key: "history:clear:error",
              cooldown: 1500,
            });
          }
        } finally {
          if (app.state) {
            await app.state.refreshState();
          }
        }
      });
    }

    if (historyList) {
      historyList.addEventListener("click", async (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const actionEl = target.closest("[data-action]");
        if (!actionEl) {
          return;
        }
        const action = actionEl.getAttribute("data-action");
        const row = actionEl.closest(".history-row");
        if (!row || !action) {
          return;
        }
        if (action === "view-log") {
          const details = row.querySelector(".job-details");
          if (details && !details.open) {
            details.open = true;
          }
          const log = row.querySelector("[data-log]");
          if (log) {
            log.scrollIntoView({
              behavior: app.utils && app.utils.prefersReducedMotion() ? "auto" : "smooth",
              block: "nearest",
            });
          }
        }
        if (action === "copy-filename") {
          const filename = actionEl.getAttribute("data-filename") || "";
          if (!filename) {
            return;
          }
          const success = app.utils ? await app.utils.copyToClipboard(filename) : false;
          if (success) {
            if (app.toasts) {
              app.toasts.notifySystem("Clipboard", "Filename copied.", "success", {
                key: "clipboard:filename",
                cooldown: 1200,
                duration: 4200,
              });
            }
          } else if (app.toasts) {
            app.toasts.notifySystem("Clipboard", "Couldn’t copy filename. Try again.", "error", {
              key: "clipboard:filename:error",
              cooldown: 1500,
            });
          }
        }
        if (action === "copy-preview") {
          const jobId = actionEl.getAttribute("data-job-id") || row.getAttribute("data-job-id");
          if (!jobId) {
            return;
          }
          if (app.modals) {
            await app.modals.copyPreviewForJob(jobId, row);
          }
        }
        if (action === "preview") {
          if (app.modals) {
            await app.modals.openPreviewForHistoryRow(row, actionEl);
          }
        }
        if (action === "delete-history") {
          const jobId = row.getAttribute("data-job-id");
          if (!jobId) {
            return;
          }
          const summary = getHistoryRowSummary(row);
          const confirmed = app.modals
            ? await app.modals.openConfirmModal({
                title: "Delete history item",
                message: buildHistoryDeleteMessage(summary),
                confirmText: "Delete",
                cancelText: "Cancel",
              })
            : false;
          if (!confirmed) {
            return;
          }
          actionEl.setAttribute("disabled", "disabled");
          try {
            await deleteHistoryJob(jobId);
            if (app.toasts) {
              app.toasts.notifySystem("History", `Deleted “${summary.filename}”.`, "success", {
                key: "history:delete",
                cooldown: 0,
                duration: 5200,
              });
            }
          } catch (error) {
            console.warn("Failed to delete history item", error);
            if (app.toasts) {
              app.toasts.notifySystem(
                "History",
                summary.filename
                  ? `Couldn’t delete “${summary.filename}”. Try again.`
                  : "Couldn’t delete history item. Try again.",
                "error",
                {
                  key: "history:delete:error",
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
        const menu = actionEl.closest(".job-menu");
        if (menu) {
          menu.removeAttribute("open");
        }
      });
    }

    app.historyActions = {
      __initialized: true,
      buildHistoryClearMessage,
    };
  }

  app.historyActions = app.historyActions || {};
  app.historyActions.init = initHistoryActions;
})();
