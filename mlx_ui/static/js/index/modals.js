(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const {
    historyList,
    previewModal,
    previewModalTitle,
    previewModalMeta,
    previewModalText,
    previewModalCopy,
    previewModalOpenLink,
    previewModalDownloadLink,
    confirmModal,
    confirmModalTitle,
    confirmModalMessage,
    confirmModalOk,
    confirmModalCancel,
  } = app.dom || {};

  const previewCache = new Map();

  const notifySystem = (...args) => {
    if (app.toasts) {
      app.toasts.notifySystem(...args);
    }
  };

  function previewCacheKey(jobId, url) {
    const key = url || jobId || "";
    return String(key);
  }

  async function fetchPreviewSnippet(jobId, url) {
    const key = previewCacheKey(jobId, url);
    if (key && previewCache.has(key)) {
      return previewCache.get(key);
    }
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Failed to load preview.");
    }
    const payload = await response.json();
    const data = {
      snippet: payload.snippet || "",
      truncated: Boolean(payload.truncated),
      filename: payload.filename || "",
    };
    if (key) {
      previewCache.set(key, data);
    }
    return data;
  }

  function updatePreviewBlock(block, payload) {
    if (!block) {
      return;
    }
    const snippetEl = block.querySelector("[data-preview-snippet]");
    if (!snippetEl) {
      return;
    }
    let text = payload.snippet || "";
    if (!text) {
      text = "No preview available.";
    } else if (payload.truncated) {
      text = `${text}…`;
    }
    snippetEl.textContent = text;
    snippetEl.classList.remove("is-loading");
    block.dataset.previewState = "loaded";
  }

  async function loadPreviewBlock(block) {
    if (
      !block ||
      block.dataset.previewState === "loading" ||
      block.dataset.previewState === "loaded"
    ) {
      return;
    }
    const row = block.closest(".history-row");
    const jobId = row ? row.getAttribute("data-job-id") : "";
    const url = block.getAttribute("data-preview-url") || "";
    if (!jobId || !url) {
      return;
    }
    block.dataset.previewState = "loading";
    const snippetEl = block.querySelector("[data-preview-snippet]");
    if (snippetEl) {
      snippetEl.textContent = "Loading preview…";
      snippetEl.classList.add("is-loading");
    }
    try {
      const payload = await fetchPreviewSnippet(jobId, url);
      updatePreviewBlock(block, payload);
    } catch (error) {
      console.warn("Failed to load preview", error);
      if (snippetEl) {
        snippetEl.textContent = "Preview unavailable.";
        snippetEl.classList.remove("is-loading");
      }
      block.dataset.previewState = "";
    }
  }

  async function copyPreviewForJob(jobId, row) {
    const block = row ? row.querySelector("[data-preview-block]") : null;
    if (!block) {
      notifySystem("Preview", "No preview available.", "error", {
        key: "preview:unavailable",
        cooldown: 2500,
      });
      return;
    }
    const url = block.getAttribute("data-preview-url") || "";
    if (!url) {
      notifySystem("Preview", "No preview available.", "error", {
        key: "preview:unavailable",
        cooldown: 2500,
      });
      return;
    }
    try {
      const payload = await fetchPreviewSnippet(jobId, url);
      updatePreviewBlock(block, payload);
      const text = payload.snippet ? (payload.truncated ? `${payload.snippet}…` : payload.snippet) : "";
      if (!text) {
        notifySystem("Preview", "No preview available.", "error", {
          key: "preview:unavailable",
          cooldown: 2500,
        });
        return;
      }
      const success = app.utils ? await app.utils.copyToClipboard(text) : false;
      if (success) {
        notifySystem("Clipboard", "Preview copied.", "success", {
          key: "clipboard:preview",
          cooldown: 1200,
          duration: 4500,
        });
      } else {
        throw new Error("Copy failed");
      }
    } catch (error) {
      console.warn("Failed to copy preview", error);
      notifySystem("Clipboard", "Couldn’t copy preview. Try again.", "error", {
        key: "clipboard:preview:error",
        cooldown: 1500,
      });
    }
  }

  const PREVIEW_MODAL_CHARS = 1200;
  let previewModalToken = 0;
  let previewModalReturnFocus = null;
  let previewModalCurrentText = "";

  function isPreviewModalOpen() {
    return Boolean(previewModal && !previewModal.hidden);
  }

  function getPreviewPanel() {
    return previewModal ? previewModal.querySelector(".modal__panel") : null;
  }

  function getPreviewFocusable(container) {
    if (!container) {
      return [];
    }
    const selectors = [
      "button:not([disabled])",
      "a[href]",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ];
    return Array.from(container.querySelectorAll(selectors.join(","))).filter((element) => {
      if (!(element instanceof HTMLElement)) {
        return false;
      }
      if (element.hasAttribute("hidden")) {
        return false;
      }
      return element.getClientRects().length > 0;
    });
  }

  function trapPreviewFocus(event) {
    const panel = getPreviewPanel();
    const focusable = getPreviewFocusable(panel);
    if (!focusable.length) {
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (!(active instanceof HTMLElement) || !panel || !panel.contains(active)) {
      event.preventDefault();
      first.focus();
      return;
    }
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onPreviewModalKeyDown(event) {
    if (!isPreviewModalOpen()) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closePreviewModal();
      return;
    }
    if (event.key === "Tab") {
      trapPreviewFocus(event);
    }
  }

  function setPreviewModalLinks(url, filename) {
    if (!previewModalOpenLink || !previewModalDownloadLink) {
      return;
    }
    const cleanUrl = url || "";
    const cleanName = filename || "";

    if (cleanUrl) {
      previewModalOpenLink.hidden = false;
      previewModalOpenLink.setAttribute("href", cleanUrl);
    } else {
      previewModalOpenLink.hidden = true;
      previewModalOpenLink.removeAttribute("href");
    }

    if (cleanUrl) {
      previewModalDownloadLink.hidden = false;
      previewModalDownloadLink.setAttribute("href", cleanUrl);
      if (cleanName) {
        previewModalDownloadLink.setAttribute("download", cleanName);
      } else {
        previewModalDownloadLink.setAttribute("download", "");
      }
    } else {
      previewModalDownloadLink.hidden = true;
      previewModalDownloadLink.removeAttribute("href");
      previewModalDownloadLink.setAttribute("download", "");
    }
  }

  function openPreviewModal() {
    if (!previewModal) {
      return;
    }
    previewModalReturnFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!previewModal.hidden) {
      return;
    }
    previewModal.hidden = false;
    document.body.classList.add("is-modal-open");
    document.addEventListener("keydown", onPreviewModalKeyDown);
    const closeButton = previewModal.querySelector("[data-preview-close].modal__close");
    if (closeButton instanceof HTMLElement) {
      closeButton.focus();
    }
  }

  function closePreviewModal() {
    if (!previewModal) {
      return;
    }
    previewModalToken += 1;
    previewModal.hidden = true;
    document.body.classList.remove("is-modal-open");
    document.removeEventListener("keydown", onPreviewModalKeyDown);
    previewModalCurrentText = "";
    if (previewModalCopy) {
      previewModalCopy.disabled = true;
    }
    if (previewModalText) {
      previewModalText.textContent = "";
      previewModalText.classList.remove("is-loading");
    }
    if (previewModalMeta) {
      previewModalMeta.textContent = `Preview snippet (up to ${PREVIEW_MODAL_CHARS} characters). Use Open or Download for the full file.`;
    }
    setPreviewModalLinks("", "");
    if (previewModalReturnFocus && document.contains(previewModalReturnFocus)) {
      previewModalReturnFocus.focus();
    }
    previewModalReturnFocus = null;
  }

  let confirmModalResolve = null;
  let confirmModalReturnFocus = null;

  function isConfirmModalOpen() {
    return Boolean(confirmModal && !confirmModal.hidden);
  }

  function getConfirmPanel() {
    return confirmModal ? confirmModal.querySelector(".modal__panel") : null;
  }

  function trapConfirmFocus(event) {
    const panel = getConfirmPanel();
    const focusable = getPreviewFocusable(panel);
    if (!focusable.length) {
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (!(active instanceof HTMLElement) || !panel || !panel.contains(active)) {
      event.preventDefault();
      first.focus();
      return;
    }
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onConfirmModalKeyDown(event) {
    if (!isConfirmModalOpen()) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeConfirmModal(false);
      return;
    }
    if (event.key === "Tab") {
      trapConfirmFocus(event);
    }
  }

  function closeConfirmModal(result) {
    if (!confirmModal) {
      return;
    }
    confirmModal.hidden = true;
    document.body.classList.remove("is-modal-open");
    document.removeEventListener("keydown", onConfirmModalKeyDown);
    const resolver = confirmModalResolve;
    confirmModalResolve = null;
    if (confirmModalReturnFocus && document.contains(confirmModalReturnFocus)) {
      confirmModalReturnFocus.focus();
    }
    confirmModalReturnFocus = null;
    if (resolver) {
      resolver(Boolean(result));
    }
  }

  function openConfirmModal(options) {
    if (!confirmModal || !confirmModalTitle || !confirmModalMessage) {
      return Promise.resolve(false);
    }
    if (isPreviewModalOpen()) {
      closePreviewModal();
    }
    if (confirmModalResolve) {
      confirmModalResolve(false);
      confirmModalResolve = null;
    }
    const opts = options || {};
    confirmModalTitle.textContent = opts.title || "Confirm action";
    confirmModalMessage.textContent = opts.message || "Are you sure?";
    if (confirmModalOk instanceof HTMLElement) {
      confirmModalOk.textContent = opts.confirmText || "Delete";
    }
    if (confirmModalCancel instanceof HTMLElement) {
      confirmModalCancel.textContent = opts.cancelText || "Cancel";
    }
    confirmModalReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    confirmModal.hidden = false;
    document.body.classList.add("is-modal-open");
    document.addEventListener("keydown", onConfirmModalKeyDown);
    return new Promise((resolve) => {
      confirmModalResolve = resolve;
      const focusTarget = confirmModalCancel instanceof HTMLElement ? confirmModalCancel : confirmModal;
      if (focusTarget instanceof HTMLElement) {
        focusTarget.focus();
      }
    });
  }

  async function openPreviewForHistoryRow(row, actionEl) {
    if (!row || !actionEl) {
      return;
    }
    if (!previewModal || !previewModalTitle || !previewModalMeta || !previewModalText) {
      return;
    }
    const jobId = actionEl.getAttribute("data-job-id") || row.getAttribute("data-job-id") || "";
    if (!jobId) {
      return;
    }
    const jobFilenameEl = row.querySelector(".history-filename");
    const jobFilename = jobFilenameEl ? jobFilenameEl.textContent.trim() : "Transcript preview";
    const urlFromEl = actionEl.getAttribute("data-preview-url") || "";
    const previewUrl =
      urlFromEl || `/api/jobs/${encodeURIComponent(jobId)}/preview?chars=${PREVIEW_MODAL_CHARS}`;
    const fallbackUrl = actionEl.getAttribute("data-default-url") || "";
    const fallbackFilename = actionEl.getAttribute("data-default-filename") || "";
    const previewMetaText =
      actionEl.getAttribute("data-preview-meta") || row.getAttribute("data-preview-meta") || "";

    previewModalToken += 1;
    const token = previewModalToken;

    previewModalTitle.textContent = jobFilename || "Transcript preview";
    previewModalMeta.textContent = previewMetaText
      ? `${previewMetaText} · Loading preview snippet (up to ${PREVIEW_MODAL_CHARS} characters)…`
      : `Loading preview snippet (up to ${PREVIEW_MODAL_CHARS} characters)…`;
    previewModalText.textContent = "Loading preview…";
    previewModalText.classList.add("is-loading");
    previewModalCurrentText = "";
    if (previewModalCopy) {
      previewModalCopy.disabled = true;
    }
    if (fallbackUrl) {
      setPreviewModalLinks(fallbackUrl, fallbackFilename);
    } else {
      setPreviewModalLinks("", "");
    }

    openPreviewModal();

    try {
      const payload = await fetchPreviewSnippet(jobId, previewUrl);
      if (token !== previewModalToken) {
        return;
      }
      const rawText = payload.snippet || "";
      const shownText = rawText ? (payload.truncated ? `${rawText}…` : rawText) : "";
      previewModalCurrentText = shownText;

      const resultFilename = payload.filename || fallbackFilename;
      const resultUrl = resultFilename
        ? `/results/${encodeURIComponent(jobId)}/${encodeURIComponent(resultFilename)}`
        : fallbackUrl;

      if (resultUrl) {
        setPreviewModalLinks(resultUrl, resultFilename || fallbackFilename);
      } else {
        setPreviewModalLinks("", "");
      }
      previewModalMeta.textContent = previewMetaText
        ? `${previewMetaText} · Preview snippet (up to ${PREVIEW_MODAL_CHARS} characters). Use Open or Download for the full file.`
        : `Preview snippet (up to ${PREVIEW_MODAL_CHARS} characters). Use Open or Download for the full file.`;

      if (!shownText) {
        previewModalText.textContent = "No preview available.";
        previewModalMeta.textContent = "No preview text was found for this item.";
        previewModalText.classList.remove("is-loading");
        return;
      }
      previewModalText.textContent = shownText;
      previewModalText.classList.remove("is-loading");
      const sourceLabel = resultFilename ? `Output: ${resultFilename}` : "Output: unavailable";
      const limitLabel = `Preview snippet (up to ${PREVIEW_MODAL_CHARS} characters)`;
      const moreLabel = payload.truncated ? " · more available" : "";
      previewModalMeta.textContent = `${sourceLabel} · ${limitLabel}${moreLabel}. Use Open or Download for the full file.`;
      if (previewModalCopy) {
        previewModalCopy.disabled = false;
      }
    } catch (error) {
      console.warn("Failed to load preview", error);
      if (token !== previewModalToken) {
        return;
      }
      previewModalText.textContent = "Preview unavailable.";
      previewModalText.classList.remove("is-loading");
      previewModalMeta.textContent = "Could not load preview text. Try Open or Download instead.";
    }
  }

  function wireHistoryDetails(listEl) {
    if (!listEl) {
      return;
    }
    listEl.querySelectorAll(".job-details").forEach((details) => {
      details.addEventListener("toggle", () => {
        if (!details.open) {
          return;
        }
        const previewBlock = details.querySelector("[data-preview-block]");
        if (previewBlock) {
          void loadPreviewBlock(previewBlock);
        }
      });
      if (details.open) {
        const previewBlock = details.querySelector("[data-preview-block]");
        if (previewBlock) {
          void loadPreviewBlock(previewBlock);
        }
      }
    });
  }

  let historyMenuPlacementFrame = 0;

  function resetHistoryMenuPlacement(menu) {
    if (!(menu instanceof HTMLElement)) {
      return;
    }
    menu.classList.remove("is-drop-up", "is-align-left");
    const panel = menu.querySelector(".job-menu-panel");
    if (!(panel instanceof HTMLElement)) {
      return;
    }
    panel.style.removeProperty("--menu-shift-x");
    panel.style.removeProperty("--menu-max-height");
  }

  function positionHistoryMenu(menu) {
    if (!(menu instanceof HTMLDetailsElement) || !menu.open) {
      resetHistoryMenuPlacement(menu);
      return;
    }

    const summary = menu.querySelector("summary");
    const panel = menu.querySelector(".job-menu-panel");
    if (!(summary instanceof HTMLElement) || !(panel instanceof HTMLElement)) {
      return;
    }

    resetHistoryMenuPlacement(menu);

    const visualViewport = window.visualViewport;
    const viewportWidth = visualViewport
      ? visualViewport.width
      : document.documentElement.clientWidth || window.innerWidth || 0;
    const viewportHeight = visualViewport
      ? visualViewport.height
      : window.innerHeight || document.documentElement.clientHeight || 0;
    const viewportLeft = visualViewport ? visualViewport.offsetLeft : 0;
    const viewportTop = visualViewport ? visualViewport.offsetTop : 0;
    const viewportRight = viewportLeft + viewportWidth;
    const viewportBottom = viewportTop + viewportHeight;
    const gutter = viewportWidth <= 520 ? 12 : 16;
    const summaryRect = summary.getBoundingClientRect();
    const spaceBelow = Math.max(0, viewportBottom - summaryRect.bottom - gutter);
    const spaceAbove = Math.max(0, summaryRect.top - viewportTop - gutter);

    let panelRect = panel.getBoundingClientRect();
    if (panelRect.height > spaceBelow && spaceAbove > spaceBelow) {
      menu.classList.add("is-drop-up");
      panelRect = panel.getBoundingClientRect();
    }

    const availableHeight = Math.max(
      0,
      menu.classList.contains("is-drop-up") ? spaceAbove : spaceBelow
    );
    panel.style.setProperty("--menu-max-height", `${Math.floor(availableHeight)}px`);
    panelRect = panel.getBoundingClientRect();

    const spaceLeft = Math.max(0, summaryRect.right - viewportLeft - gutter);
    const spaceRight = Math.max(0, viewportRight - summaryRect.left - gutter);
    if (panelRect.left < viewportLeft + gutter && spaceRight > spaceLeft) {
      menu.classList.add("is-align-left");
      panelRect = panel.getBoundingClientRect();
    }

    let shiftX = 0;
    if (panelRect.right > viewportRight - gutter) {
      shiftX -= panelRect.right - (viewportRight - gutter);
    }
    if (panelRect.left + shiftX < viewportLeft + gutter) {
      shiftX += viewportLeft + gutter - (panelRect.left + shiftX);
    }
    if (Math.abs(shiftX) > 0.5) {
      panel.style.setProperty("--menu-shift-x", `${Math.round(shiftX)}px`);
    }
  }

  function closeHistoryMenus(exceptMenu) {
    if (!historyList) {
      return;
    }
    historyList.querySelectorAll(".job-menu[open]").forEach((menu) => {
      if (exceptMenu && menu === exceptMenu) {
        return;
      }
      menu.removeAttribute("open");
    });
  }

  function scheduleHistoryMenuPlacement() {
    window.cancelAnimationFrame(historyMenuPlacementFrame);
    historyMenuPlacementFrame = window.requestAnimationFrame(() => {
      if (!historyList) {
        return;
      }
      historyList.querySelectorAll(".job-menu[open]").forEach((menu) => {
        positionHistoryMenu(menu);
      });
    });
  }

  function wireHistoryMenus(listEl) {
    if (!listEl) {
      return;
    }
    listEl.querySelectorAll(".job-menu").forEach((menu) => {
      menu.addEventListener("toggle", () => {
        if (!menu.open) {
          resetHistoryMenuPlacement(menu);
          return;
        }
        closeHistoryMenus(menu);
        scheduleHistoryMenuPlacement();
      });
    });
    scheduleHistoryMenuPlacement();
  }

  function initModals() {
    if (app.modals && app.modals.__initialized) {
      return;
    }

    if (confirmModal) {
      confirmModal.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        if (target.closest("[data-confirm-ok]")) {
          event.preventDefault();
          closeConfirmModal(true);
          return;
        }
        if (
          target.closest("[data-confirm-cancel]") ||
          target.closest("[data-confirm-close]")
        ) {
          event.preventDefault();
          closeConfirmModal(false);
        }
      });
    }

    if (previewModal) {
      previewModal.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const closer = target.closest("[data-preview-close]");
        if (!closer) {
          return;
        }
        event.preventDefault();
        closePreviewModal();
      });
    }

    if (previewModalCopy) {
      previewModalCopy.addEventListener("click", async () => {
        if (!previewModalCurrentText) {
          return;
        }
        const success = app.utils ? await app.utils.copyToClipboard(previewModalCurrentText) : false;
        if (success) {
          notifySystem("Clipboard", "Preview copied.", "success", {
            key: "clipboard:preview",
            cooldown: 1200,
            duration: 4500,
          });
        } else {
          notifySystem("Clipboard", "Couldn’t copy preview. Try again.", "error", {
            key: "clipboard:preview:error",
            cooldown: 1500,
          });
        }
      });
    }

    document.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const menu = target.closest(".job-menu");
      if (menu) {
        closeHistoryMenus(menu);
        return;
      }
      closeHistoryMenus(null);
    });

    window.addEventListener("resize", scheduleHistoryMenuPlacement, { passive: true });
    window.addEventListener("scroll", scheduleHistoryMenuPlacement, { passive: true });

    app.modals = {
      __initialized: true,
      openConfirmModal,
      openPreviewForHistoryRow,
      closePreviewModal,
      copyPreviewForJob,
      wireHistoryDetails,
      wireHistoryMenus,
      scheduleHistoryMenuPlacement,
      closeHistoryMenus,
    };
  }

  app.modals = app.modals || {};
  app.modals.init = initModals;
})();

