(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }
  if (app.renderJobs) {
    return;
  }

  const escapeHtml = app.utils ? app.utils.escapeHtml : (value) => String(value);
  const ICON_TRASH = `
    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M6.5 3.75h7a1 1 0 0 1 .98.804l.22 1.096h2.05a.75.75 0 0 1 0 1.5h-.81l-.52 7.191A2 2 0 0 1 13.426 16H6.574a2 2 0 0 1-1.994-1.659L4.06 7.15h-.81a.75.75 0 0 1 0-1.5H5.3l.22-1.096a1 1 0 0 1 .98-.804Zm-.916 3.4.489 6.974a.5.5 0 0 0 .5.426h6.852a.5.5 0 0 0 .5-.426l.489-6.974H5.584Zm1.397-1.5h5.038l-.13-.65H7.11l-.129.65Zm.894 2.05c.4 0 .725.325.725.725v3.7a.725.725 0 1 1-1.45 0v-3.7c0-.4.324-.725.725-.725Zm4.25 0c.4 0 .725.325.725.725v3.7a.725.725 0 1 1-1.45 0v-3.7c0-.4.324-.725.725-.725Z"
        fill="currentColor"
      ></path>
    </svg>
  `;

  function pickDefaultResult(results) {
    if (!results || results.length === 0) {
      return "";
    }
    const preferred = results.find((result) => result.toLowerCase().endsWith(".txt"));
    return preferred || results[0];
  }

  function summarizeError(message, limit = 160) {
    if (!message) {
      return "";
    }
    const firstLine = String(message).split(/\r?\n/)[0].trim();
    if (!firstLine) {
      return "";
    }
    const condensed = firstLine.replace(/\s+/g, " ");
    if (condensed.length <= limit) {
      return condensed;
    }
    return `${condensed.slice(0, Math.max(limit - 1, 0))}…`;
  }

  function buildOutputList(jobId, results) {
    if (!results || results.length === 0) {
      return "";
    }
    const encodedJobId = encodeURIComponent(jobId);
    const items = results
      .map((result) => {
        const encodedResult = encodeURIComponent(result);
        const safeResult = escapeHtml(result);
        return `
          <li class="detail-result-item">
            <a
              class="detail-result-link"
              href="/results/${encodedJobId}/${encodedResult}"
              target="_blank"
              rel="noopener"
            >
              ${safeResult}
            </a>
          </li>
        `;
      })
      .join("");
    return `
      <div class="detail-block is-outputs">
        <div class="detail-label">Outputs</div>
        <ul class="detail-results">${items}</ul>
      </div>
    `;
  }

  function buildDetailPair(label, valueHtml, options) {
    if (!valueHtml) {
      return "";
    }
    const opts = options || {};
    const titleAttr = opts.title ? ` title="${escapeHtml(opts.title)}"` : "";
    return `
      <div class="detail-pair">
        <dt class="detail-term">${escapeHtml(label)}</dt>
        <dd class="detail-value"${titleAttr}>${valueHtml}</dd>
      </div>
    `;
  }

  function buildMetaLine(label, isoString, className) {
    if (!isoString) {
      return "";
    }
    const classLabel = className || "job-meta";
    return `
      <div class="${classLabel}" data-iso="${escapeHtml(isoString)}" data-label="${escapeHtml(
        label
      )}"></div>
    `;
  }

  function buildMetaLines(job) {
    const lines = [buildMetaLine("Added", job.created_at, "job-meta")];
    if (job.started_at) {
      lines.push(buildMetaLine("Started", job.started_at, "job-meta"));
    }
    if (job.completed_at) {
      lines.push(buildMetaLine("Completed", job.completed_at, "job-meta"));
    }
    return lines.join("");
  }

  function buildProcessingBlock(job) {
    const ui = job && job.ui && typeof job.ui === "object" ? job.ui : null;
    if (!ui) {
      return "";
    }
    const language = ui.language && typeof ui.language === "object" ? ui.language : null;
    const implementation =
      ui.effective_implementation && typeof ui.effective_implementation === "object"
        ? ui.effective_implementation
        : null;
    const implementationId = implementation && implementation.id ? String(implementation.id) : "";
    const implementationTitle =
      implementation && implementation.title
        ? String(implementation.title)
        : implementationId
          ? `Backend: ${implementationId}`
          : "";
    const items = [];
    if (ui.engine_summary) {
      items.push(buildDetailPair("Engine", escapeHtml(String(ui.engine_summary))));
    }
    if (language && (language.label || language.short_label)) {
      items.push(
        buildDetailPair("Language", escapeHtml(String(language.label || language.short_label)))
      );
    }
    if (implementationId) {
      items.push(
        buildDetailPair("Backend", `<code>${escapeHtml(implementationId)}</code>`, {
          title: implementationTitle,
        })
      );
    }
    if (!items.length) {
      return "";
    }
    return `
      <div class="detail-block is-processing">
        <div class="detail-label">Processing</div>
        <dl class="detail-list">
          ${items.join("")}
        </dl>
      </div>
    `;
  }

  function buildTimelineBlock(job, status) {
    const lines = [
      buildMetaLine("Added", job.created_at, "detail-line"),
      job.started_at ? buildMetaLine("Started", job.started_at, "detail-line") : "",
      job.completed_at
        ? buildMetaLine(
            status === "failed" ? "Failed" : "Completed",
            job.completed_at,
            "detail-line"
          )
        : "",
    ].join("");
    return `
      <div class="detail-block is-timeline">
        <div class="detail-label">Timeline</div>
        ${lines}
      </div>
    `;
  }

  function buildJobMetaChips(job) {
    const ui = job && job.ui && typeof job.ui === "object" ? job.ui : null;
    if (!ui) {
      return "";
    }
    const chips = [];
    const engineBadges = Array.isArray(ui.engine_badges) ? ui.engine_badges : [];
    if (engineBadges.length > 0) {
      const engineMarkup = engineBadges
        .map((badge) => {
          const kind = escapeHtml(badge.kind || "engine");
          const mode = escapeHtml(badge.mode || "unknown");
          const title = escapeHtml(badge.title || badge.label || "");
          const label = escapeHtml(badge.label || "");
          return `
            <span class="meta-chip is-${kind} is-${mode}" title="${title}">
              ${label}
            </span>
          `;
        })
        .join("");
      chips.push(`<span class="meta-chips" aria-label="Engine">${engineMarkup}</span>`);
    }
    const language = ui.language && typeof ui.language === "object" ? ui.language : null;
    if (language && language.short_label) {
      chips.push(`
        <span
          class="meta-chip is-language"
          title="Language: ${escapeHtml(language.label || language.short_label)}"
        >
          ${escapeHtml(language.short_label)}
        </span>
      `);
    }
    return chips.join("");
  }

  function buildPreviewMetaText(job) {
    const ui = job && job.ui && typeof job.ui === "object" ? job.ui : null;
    return ui && ui.preview_meta ? String(ui.preview_meta) : "";
  }

  function buildQueueActions(job) {
    const canDelete = job.status === "queued";
    if (!canDelete) {
      return '<div class="job-actions"></div>';
    }
    return `
      <div class="job-actions">
        <button
          class="job-bin"
          type="button"
          data-job-id="${escapeHtml(job.id)}"
          data-job-action="remove"
          aria-label="Remove from queue"
          title="Remove from queue"
        >
          <span class="job-bin-icon" aria-hidden="true">${ICON_TRASH}</span>
          <span class="sr-only">Remove from queue</span>
        </button>
      </div>
    `;
  }

  function buildQueueLabel(position) {
    if (!position || position <= 1) {
      return "Next";
    }
    return `${Math.max(position - 1, 0)} ahead`;
  }

  function pickQueueContextEngine(job, isRunning) {
    const ui = job && job.ui && typeof job.ui === "object" ? job.ui : null;
    if (!ui) {
      return null;
    }
    const effective =
      ui.effective_engine && typeof ui.effective_engine === "object" ? ui.effective_engine : null;
    const requested =
      ui.requested_engine && typeof ui.requested_engine === "object" ? ui.requested_engine : null;
    if (isRunning) {
      return effective || requested;
    }
    return requested || effective;
  }

  function buildQueueContext(job, isRunning) {
    const ui = job && job.ui && typeof job.ui === "object" ? job.ui : null;
    if (!ui) {
      return "";
    }
    const parts = [];
    const engine = pickQueueContextEngine(job, isRunning);
    if (engine && String(engine.mode || "").toLowerCase() === "cloud") {
      const engineLabel = String(engine.short_label || engine.label || "").trim();
      if (engineLabel) {
        parts.push(`${engineLabel} cloud`);
      }
    }
    const language = ui.language && typeof ui.language === "object" ? ui.language : null;
    const languageId = String((language && language.id) || "").toLowerCase();
    const languageLabel = String((language && language.short_label) || "").trim();
    if (languageLabel && languageId && languageId !== "auto") {
      parts.push(languageLabel);
    }
    return parts.join(" · ");
  }

  function buildQueueSummary(job, options) {
    const opts = options || {};
    const isRunning = Boolean(opts.isRunning);
    const queuePosition = opts.queuePosition || 0;
    const context = buildQueueContext(job, isRunning);
    const parts = [];
    if (isRunning) {
      if (job.started_at) {
        parts.push(`
          <span class="job-elapsed" data-started-at="${escapeHtml(job.started_at)}">
            <span class="spinner spinner--status" aria-hidden="true"></span>
            <span data-elapsed-label>Elapsed …</span>
          </span>
        `);
      } else {
        parts.push('<span class="job-summary-text">Running</span>');
      }
    } else {
      parts.push(`<span class="job-summary-text">${escapeHtml(buildQueueLabel(queuePosition))}</span>`);
    }
    if (context) {
      parts.push('<span class="job-summary-separator" aria-hidden="true">·</span>');
      parts.push(
        `<span class="job-summary-context" title="${escapeHtml(context)}">${escapeHtml(context)}</span>`
      );
    }
    return parts.join("");
  }

  function buildQueueRow(job, options) {
    const opts = options || {};
    const isRunning = Boolean(opts.isRunning);
    const queuePosition = opts.queuePosition || 0;
    const statusRaw = String(job.status || "").toLowerCase();
    const statusLabel = statusRaw ? statusRaw[0].toUpperCase() + statusRaw.slice(1) : "Unknown";
    const statusClass = statusRaw === "running" ? "is-running" : statusRaw === "queued" ? "is-queued" : "";
    const badgeClass = statusClass ? `status-badge ${statusClass}` : "status-badge";
    const safeFilename = escapeHtml(job.filename || "Untitled file");
    const summary = buildQueueSummary(job, { isRunning, queuePosition });
    const actions = buildQueueActions(job);
    return `
      <div class="job-row${isRunning ? " is-running" : ""}">
        <div class="job-body">
          <div class="job-topline">
            <div class="job-name" title="${safeFilename}">${safeFilename}</div>
            <span class="${badgeClass}">${escapeHtml(statusLabel)}</span>
          </div>
          <div class="job-subline">
            ${summary}
          </div>
        </div>
        ${actions}
      </div>
    `;
  }

  function buildHistoryMenu(job, results, defaultResult, isOpen) {
    const status = (job.status || "").toLowerCase();
    const encodedJobId = encodeURIComponent(job.id);
    const safeFilename = escapeHtml(job.filename || "Untitled file");
    const previewMeta = escapeHtml(buildPreviewMetaText(job));
    const openAttr = isOpen ? " open" : "";
    const items = [];
    if (status === "done" && defaultResult) {
      items.push(`
        <button
          class="job-menu-item js-only"
          type="button"
          data-action="preview"
          data-job-id="${escapeHtml(job.id)}"
          data-preview-url="/api/jobs/${encodedJobId}/preview?chars=1200"
          data-default-url="/results/${encodedJobId}/${encodeURIComponent(defaultResult)}"
          data-default-filename="${escapeHtml(defaultResult)}"
          data-preview-meta="${previewMeta}"
          aria-haspopup="dialog"
        >
          Preview
        </button>
      `);
      const encodedResult = encodeURIComponent(defaultResult);
      items.push(`
        <a
          class="job-menu-item"
          href="/results/${encodedJobId}/${encodedResult}"
          target="_blank"
          rel="noopener"
        >
          Open file
        </a>
      `);
    }
    if (results && results.length > 0) {
      results.forEach((result) => {
        const encodedResult = encodeURIComponent(result);
        const parts = String(result).split(".");
        const ext = parts.length > 1 ? parts[parts.length - 1].toUpperCase() : "FILE";
        items.push(`
          <a
            class="job-menu-item"
            href="/results/${encodedJobId}/${encodedResult}"
            download="${escapeHtml(result)}"
          >
            Download ${escapeHtml(ext)}
          </a>
        `);
      });
    }
    if (status === "done" && defaultResult) {
      items.push(`
        <button
          class="job-menu-item"
          type="button"
          data-action="copy-preview"
          data-job-id="${escapeHtml(job.id)}"
        >
          Copy preview
        </button>
      `);
    }
    items.push(`
      <button
        class="job-menu-item"
        type="button"
        data-action="copy-filename"
        data-filename="${safeFilename}"
      >
        Copy filename
      </button>
    `);
    items.push('<div class="job-menu-divider" aria-hidden="true"></div>');
    items.push(`
      <button
        class="job-menu-item is-danger"
        type="button"
        data-action="delete-history"
      >
        Delete
      </button>
    `);
    return `
      <details class="job-menu"${openAttr}>
        <summary aria-label="More actions">⋯</summary>
        <div class="job-menu-panel">
          ${items.join("")}
        </div>
      </details>
    `;
  }

  function buildHistoryDetails(job, results, defaultResult, isOpen) {
    const status = (job.status || "").toLowerCase();
    const encodedJobId = encodeURIComponent(job.id);
    const safeFilename = escapeHtml(job.filename || "Untitled file");
    const openAttr = isOpen ? " open" : "";
    const processingBlock = buildProcessingBlock(job);
    const timelineBlock = buildTimelineBlock(job, status);

    const previewBlock =
      status === "done" && defaultResult
        ? `
          <div
            class="detail-block is-preview"
            data-preview-block
            data-preview-url="/api/jobs/${encodedJobId}/preview?chars=300"
          >
            <div class="detail-label">Preview</div>
            <div class="preview-snippet is-loading" data-preview-snippet>
              Loads on open.
            </div>
            <div class="preview-actions">
              <button
                class="preview-action"
                type="button"
                data-action="copy-preview"
                data-job-id="${escapeHtml(job.id)}"
              >
                Copy preview
              </button>
              <a
                class="preview-action"
                href="/results/${encodeURIComponent(job.id)}/${encodeURIComponent(defaultResult)}"
                target="_blank"
                rel="noopener"
              >
                Open
              </a>
            </div>
          </div>
        `
        : "";

    const outputsBlock = buildOutputList(job.id, results);
    const logBlock =
      status === "failed" && job.error_message
        ? `
          <div class="detail-block is-log">
            <div class="detail-label">Failure log</div>
            <div class="detail-log" data-log>${escapeHtml(job.error_message)}</div>
          </div>
        `
        : "";

    return `
      <details class="job-details" data-job-id="${escapeHtml(job.id)}"${openAttr}>
        <summary aria-label="View details for ${safeFilename}">
          <span>Details</span>
          <span class="details-chevron" aria-hidden="true">▾</span>
        </summary>
        <div class="job-details-body">
          ${previewBlock}
          ${logBlock}
          ${outputsBlock}
          ${processingBlock}
          ${timelineBlock}
        </div>
      </details>
    `;
  }

  function buildHistoryRow(job, resultsByJob, openJobs, openMenus) {
    const results = (resultsByJob || {})[job.id] || [];
    const defaultResult = pickDefaultResult(results);
    const safeFilename = escapeHtml(job.filename || "Untitled file");
    const encodedJobId = encodeURIComponent(job.id);
    const status = (job.status || "unknown").toLowerCase();
    const statusLabel = status ? status[0].toUpperCase() + status.slice(1) : "Unknown";
    const statusClass = `is-${escapeHtml(status)}`;
    const errorSummaryText =
      status === "failed" && job.error_message ? summarizeError(job.error_message, 96) : "";
    const isOpen = openJobs ? openJobs.has(job.id) : false;
    const isMenuOpen = openMenus ? openMenus.has(job.id) : false;
    const timeMeta = `
      <div
        class="history-time"
        data-time-meta
        data-status="${escapeHtml(status)}"
        data-created-at="${escapeHtml(job.created_at || "")}"
        data-started-at="${escapeHtml(job.started_at || "")}"
        data-completed-at="${escapeHtml(job.completed_at || "")}"
      ></div>
    `;
    const errorSummary = errorSummaryText
      ? `
        <span class="history-summary-separator" aria-hidden="true">·</span>
        <div class="history-error-summary" title="${escapeHtml(errorSummaryText)}">
          ${escapeHtml(errorSummaryText)}
        </div>
      `
      : "";
    const previewMeta = escapeHtml(buildPreviewMetaText(job));
    const defaultHref =
      status === "done" && defaultResult
        ? `/results/${encodedJobId}/${encodeURIComponent(defaultResult)}`
        : "";
    const downloadAction =
      status === "done" && defaultResult
        ? `
          <a class="job-primary" href="${escapeHtml(defaultHref)}" download="${escapeHtml(defaultResult)}">
            Download
          </a>
        `
        : "";
    const viewLogAction =
      status === "failed"
        ? `
          <button class="job-primary is-secondary" type="button" data-action="view-log">
            Log
          </button>
        `
        : "";
    const primaryAction = [downloadAction, viewLogAction].filter(Boolean).join("");

    return `
      <div
        class="history-row"
        data-job-id="${escapeHtml(job.id)}"
        data-preview-meta="${previewMeta}"
      >
        <div class="history-main">
          <div class="history-title">
            <div class="history-filename" title="${safeFilename}">${safeFilename}</div>
            <div class="status-badge ${statusClass}">${escapeHtml(statusLabel)}</div>
          </div>
          <div class="history-subline">
            ${timeMeta}
            ${errorSummary}
          </div>
        </div>
        <div class="history-actions">
          <div class="history-actions-main">
            ${primaryAction}
          </div>
          ${buildHistoryMenu(job, results, defaultResult, isMenuOpen)}
        </div>
        ${buildHistoryDetails(job, results, defaultResult, isOpen)}
      </div>
    `;
  }

  app.renderJobs = {
    pickDefaultResult,
    summarizeError,
    buildQueueRow,
    buildHistoryRow,
  };
})();
