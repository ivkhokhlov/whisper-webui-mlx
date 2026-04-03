(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const { toastStack, settingsBannerSuccess } = app.dom || {};

  const ICON_CHECK = `
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
      <path fill="currentColor" d="M9.2 16.6 4.9 12.3l1.4-1.4 2.9 2.9 8.6-8.6 1.4 1.4z"></path>
    </svg>
  `;
  const ICON_ERROR = `
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
      <path fill="currentColor" d="M12 2 1 21h22L12 2zm1 15h-2v-2h2v2zm0-4h-2V9h2v4z"></path>
    </svg>
  `;
  const ICON_X = `
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path fill="currentColor" d="M18.3 5.7 12 12l6.3 6.3-1.4 1.4L10.6 13.4 4.3 19.7 2.9 18.3 9.2 12 2.9 5.7 4.3 4.3l6.3 6.3 6.3-6.3z"></path>
    </svg>
  `;

  const PENDING_TOAST_STORAGE_KEY =
    (app.constants && app.constants.PENDING_TOAST_STORAGE_KEY) || "mlx-ui:pending-toast";

  const notifiedJobIds = new Set();
  let notificationsSeeded = false;
  const toastLedger = new Map();

  function normalizeToastKey(value) {
    return String(value || "")
      .trim()
      .replace(/[^a-z0-9:_-]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80);
  }

  function buildToast(job, resultsByJob, opts) {
    if (!toastStack) {
      return;
    }
    const options = opts || {};
    const isFailed = job.status === "failed";
    const duration = options.duration || (isFailed ? 12000 : 8000);

    const toastKey = options.key ? normalizeToastKey(options.key) : "";
    const cooldown = typeof options.cooldown === "number" ? Math.max(0, options.cooldown) : 1500;
    if (toastKey) {
      const now = Date.now();
      const lastShown = toastLedger.get(toastKey);
      if (typeof lastShown === "number" && now - lastShown < cooldown) {
        return;
      }
      toastLedger.set(toastKey, now);
      const existing = toastStack.querySelector(`.toast[data-toast-key="${toastKey}"]`);
      if (existing) {
        existing.remove();
      }
    }

    const toast = document.createElement("div");
    toast.className = `toast ${isFailed ? "is-failed" : "is-done"}`;
    toast.style.setProperty("--toast-duration", `${duration}ms`);
    if (toastKey) {
      toast.dataset.toastKey = toastKey;
    }
    toast.setAttribute("role", isFailed ? "alert" : "status");
    toast.setAttribute("aria-atomic", "true");
    if (options.clickable) {
      toast.classList.add("is-clickable");
      toast.setAttribute("tabindex", "0");
    }

    const icon = document.createElement("div");
    icon.className = "toast__icon";
    icon.innerHTML = isFailed ? ICON_ERROR : ICON_CHECK;

    const header = document.createElement("div");
    header.className = "toast__header";

    const title = document.createElement("div");
    title.className = "toast__title";
    title.textContent = options.title || (isFailed ? "Transcription failed" : "Transcription complete");

    const meta = document.createElement("div");
    meta.className = "toast__meta";
    if (job.completed_at && options.showTime !== false) {
      try {
        meta.textContent = new Date(job.completed_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        });
      } catch (error) {
        meta.textContent = "";
      }
    }

    header.appendChild(title);
    if (meta.textContent) {
      header.appendChild(meta);
    }

    const body = document.createElement("div");
    body.className = "toast__body";
    const bodyText = options.body || job.filename || "Unknown file";
    body.textContent = bodyText;
    body.title = bodyText;

    const dismiss = document.createElement("button");
    dismiss.className = "toast__dismiss";
    dismiss.type = "button";
    dismiss.setAttribute("aria-label", "Dismiss notification");
    dismiss.innerHTML = ICON_X;

    const progress = document.createElement("div");
    progress.className = "toast__progress";
    const bar = document.createElement("div");
    bar.className = "toast__progressBar";
    progress.appendChild(bar);

    const toastLimit = 4;
    while (toastStack.children.length >= toastLimit) {
      toastStack.removeChild(toastStack.firstElementChild);
    }

    toast.appendChild(icon);
    toast.appendChild(header);
    toast.appendChild(dismiss);
    toast.appendChild(body);
    toast.appendChild(progress);
    toastStack.appendChild(toast);
    requestAnimationFrame(() => {
      toast.classList.add("is-visible");
    });

    let timeoutId = null;
    let remaining = duration;
    let startedAt = performance.now();

    function cleanup() {
      window.removeEventListener("keydown", onKeyDown);
    }

    function dismissToast() {
      window.clearTimeout(timeoutId);
      timeoutId = null;
      toast.classList.remove("is-visible");
      cleanup();
      window.setTimeout(() => toast.remove(), 200);
    }

    function schedule(ms) {
      window.clearTimeout(timeoutId);
      startedAt = performance.now();
      timeoutId = window.setTimeout(dismissToast, ms);
    }

    function pause() {
      if (!timeoutId) {
        return;
      }
      const elapsed = performance.now() - startedAt;
      remaining = Math.max(0, remaining - elapsed);
      window.clearTimeout(timeoutId);
      timeoutId = null;
      toast.classList.add("is-paused");
    }

    function resume() {
      if (timeoutId) {
        return;
      }
      toast.classList.remove("is-paused");
      if (remaining <= 0) {
        dismissToast();
        return;
      }
      schedule(remaining);
    }

    function onKeyDown(event) {
      if (event.key === "Escape") {
        if (toastStack && toastStack.lastElementChild === toast) {
          dismissToast();
        }
      }
    }

    dismiss.addEventListener("click", (event) => {
      event.stopPropagation();
      dismissToast();
    });
    toast.addEventListener("mouseenter", pause);
    toast.addEventListener("mouseleave", resume);
    toast.addEventListener("focusin", pause);
    toast.addEventListener("focusout", resume);
    window.addEventListener("keydown", onKeyDown);

    toast.addEventListener("click", () => {
      if (!options.clickable) {
        return;
      }
      window.location.href = options.link || "/?tab=history";
    });

    toast.addEventListener("keydown", (event) => {
      if (!options.clickable) {
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        window.location.href = options.link || "/?tab=history";
      }
    });

    schedule(remaining);
  }

  function handleNotifications(history, resultsByJob) {
    const completed = (history || []).filter((job) => job.status === "done" || job.status === "failed");
    if (!notificationsSeeded) {
      completed.forEach((job) => notifiedJobIds.add(job.id));
      notificationsSeeded = true;
      return;
    }
    completed.forEach((job) => {
      if (!notifiedJobIds.has(job.id)) {
        notifiedJobIds.add(job.id);
        buildToast(job, resultsByJob, {
          clickable: true,
          key: `job:${job.id}:${job.status}`,
        });
      }
    });
  }

  function showToast(payload) {
    const toastPayload = payload || {};
    const kind = toastPayload.kind === "error" ? "error" : "success";
    const isError = kind === "error";
    const messageText = toastPayload.message ? String(toastPayload.message) : "";
    const titleText = toastPayload.title ? String(toastPayload.title) : isError ? "Error" : "Done";
    const duration =
      typeof toastPayload.duration === "number"
        ? toastPayload.duration
        : isError
          ? 10000
          : 6000;
    const key = toastPayload.key || "";
    const cooldown = typeof toastPayload.cooldown === "number" ? toastPayload.cooldown : 1500;
    const link = toastPayload.link || "";
    const clickable = Boolean(toastPayload.clickable);

    buildToast(
      {
        id: `system-${Date.now()}`,
        status: isError ? "failed" : "done",
        filename: messageText,
        completed_at: new Date().toISOString(),
      },
      {},
      {
        title: titleText,
        body: messageText,
        duration,
        showTime: false,
        clickable,
        link,
        key,
        cooldown,
      }
    );
  }

  function notifySystem(titleText, bodyText, kind, options) {
    const opts = options || {};
    showToast({
      title: titleText,
      message: bodyText,
      kind: kind === "error" ? "error" : "success",
      duration: opts.duration,
      key: opts.key,
      cooldown: opts.cooldown,
      clickable: opts.clickable,
      link: opts.link,
    });
  }

  function storePendingToast(payload) {
    if (!payload) {
      return;
    }
    try {
      localStorage.setItem(PENDING_TOAST_STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
      // localStorage may be disabled; ignore.
    }
  }

  function consumePendingToast() {
    try {
      const raw = localStorage.getItem(PENDING_TOAST_STORAGE_KEY);
      if (!raw) {
        return;
      }
      localStorage.removeItem(PENDING_TOAST_STORAGE_KEY);
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") {
        return;
      }
      if (parsed.title && parsed.message) {
        showToast(parsed);
      }
    } catch (error) {
      // Ignore parsing/storage errors.
    }
  }

  function initToasts() {
    if (app.toasts && app.toasts.__initialized) {
      return;
    }
    consumePendingToast();
    if (settingsBannerSuccess && !settingsBannerSuccess.hidden) {
      notifySystem("Settings", "Saved.", "success", {
        key: "settings:saved",
        cooldown: 0,
        duration: 4200,
      });
    }
    app.toasts = {
      __initialized: true,
      handleNotifications,
      notifySystem,
      storePendingToast,
    };
  }

  app.toasts = app.toasts || {};
  app.toasts.init = initToasts;
})();

