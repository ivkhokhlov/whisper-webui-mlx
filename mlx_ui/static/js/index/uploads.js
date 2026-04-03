(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const {
    uploadForm,
    fileInput,
    folderInput,
    dropzone,
    fileList,
    selectionValid,
    selectionSkipped,
    selectionState,
    fileListToggle,
    uploadSubmit,
    clearSelectionButton,
    pickFilesButton,
    pickFolderButton,
  } = app.dom || {};

  const pendingItems = [];
  let skippedCount = 0;
  let showAllFiles = false;
  let scanningFolder = false;
  let scanToken = 0;
  let syncingInput = false;
  let dragDepth = 0;
  let uploadInFlight = false;
  let guideTimeout = null;

  const MAX_VISIBLE_FILES = 50;
  const MEDIA_EXTENSIONS = new Set([
    "mp3",
    "wav",
    "m4a",
    "flac",
    "ogg",
    "opus",
    "aac",
    "wma",
    "alac",
    "aiff",
    "amr",
    "mp4",
    "mov",
    "mkv",
    "webm",
    "m4v",
    "avi",
    "mpg",
    "mpeg",
    "3gp",
  ]);
  const SKIP_PATH_PARTS = new Set(["__MACOSX"]);

  function guideToUpload(options = {}) {
    if (!uploadForm) {
      return;
    }
    const { openPicker = false } = options;
    try {
      uploadForm.scrollIntoView({
        behavior: app.utils && app.utils.prefersReducedMotion() ? "auto" : "smooth",
        block: "start",
      });
    } catch (error) {
      uploadForm.scrollIntoView();
    }
    uploadForm.classList.add("is-guided");
    const guideTarget = pickFilesButton || dropzone;
    if (guideTarget) {
      guideTarget.classList.add("is-guided");
      try {
        guideTarget.focus({ preventScroll: true });
      } catch (error) {
        guideTarget.focus();
      }
    }
    if (guideTimeout) {
      window.clearTimeout(guideTimeout);
    }
    guideTimeout = window.setTimeout(() => {
      uploadForm.classList.remove("is-guided");
      if (guideTarget) {
        guideTarget.classList.remove("is-guided");
      }
    }, 1600);
    if (openPicker && fileInput) {
      fileInput.click();
    }
  }

  function normalizeDisplayPath(value) {
    return String(value || "").replace(/\\/g, "/");
  }

  function getExtension(value) {
    const normalized = String(value || "");
    const lastDot = normalized.lastIndexOf(".");
    if (lastDot <= 0 || lastDot === normalized.length - 1) {
      return "";
    }
    return normalized.slice(lastDot + 1).toLowerCase();
  }

  function isHiddenPath(displayPath) {
    const normalized = normalizeDisplayPath(displayPath);
    return normalized.split("/").some((part) => {
      if (!part) {
        return true;
      }
      if (SKIP_PATH_PARTS.has(part)) {
        return true;
      }
      return part.startsWith(".");
    });
  }

  function isAcceptedMedia(file, displayPath) {
    if (isHiddenPath(displayPath)) {
      return false;
    }
    const type = String(file.type || "").toLowerCase();
    if (type.startsWith("audio/") || type.startsWith("video/")) {
      return true;
    }
    const ext = getExtension(displayPath);
    return MEDIA_EXTENSIONS.has(ext);
  }

  function buildItemKey(item) {
    return `${item.displayPath}::${item.file.size}::${item.file.lastModified}`;
  }

  function prepareItems(rawItems) {
    const items = [];
    let skipped = 0;
    rawItems.forEach(({ file, displayPath }) => {
      const normalized =
        normalizeDisplayPath(displayPath) ||
        normalizeDisplayPath(file.webkitRelativePath) ||
        normalizeDisplayPath(file.name);
      if (!normalized || !isAcceptedMedia(file, normalized)) {
        skipped += 1;
        return;
      }
      items.push({ file, displayPath: normalized });
    });
    return { items, skipped };
  }

  function syncInputFiles(items) {
    if (!fileInput) {
      return;
    }
    if (typeof DataTransfer === "undefined") {
      return;
    }
    const transfer = new DataTransfer();
    items.forEach((item) => transfer.items.add(item.file));
    syncingInput = true;
    fileInput.files = transfer.files;
    syncingInput = false;
  }

  function renderFileItems() {
    if (!fileList) {
      return;
    }
    fileList.innerHTML = "";
    if (pendingItems.length === 0) {
      if (fileListToggle) {
        fileListToggle.style.display = "none";
      }
      return;
    }
    const visibleCount = showAllFiles
      ? pendingItems.length
      : Math.min(MAX_VISIBLE_FILES, pendingItems.length);
    const fragment = document.createDocumentFragment();
    pendingItems.slice(0, visibleCount).forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "file-item";

      const meta = document.createElement("div");
      meta.className = "file-meta";

      const name = document.createElement("div");
      name.className = "file-name";
      name.textContent = item.displayPath || "Untitled file";

      const size = document.createElement("div");
      size.className = "file-size";
      size.textContent = app.utils ? app.utils.formatBytes(item.file.size || 0) : "0 B";

      meta.appendChild(name);
      meta.appendChild(size);

      const remove = document.createElement("button");
      remove.className = "file-remove";
      remove.type = "button";
      remove.dataset.removeIndex = String(index);
      remove.setAttribute("aria-label", `Remove ${item.displayPath || "file"}`);
      remove.textContent = "Remove";

      row.appendChild(meta);
      row.appendChild(remove);
      fragment.appendChild(row);
    });
    fileList.appendChild(fragment);
    if (fileListToggle) {
      if (pendingItems.length > MAX_VISIBLE_FILES) {
        fileListToggle.style.display = "inline-flex";
        fileListToggle.textContent = showAllFiles ? "Show first 50" : "Show all";
      } else {
        fileListToggle.style.display = "none";
      }
    }
  }

  function renderFileList() {
    if (
      !fileList ||
      !uploadSubmit ||
      !dropzone ||
      !selectionValid ||
      !selectionSkipped ||
      !selectionState ||
      !clearSelectionButton
    ) {
      return;
    }

    const validCount = pendingItems.length;
    const fileLabel = validCount === 1 ? "file" : "files";

    selectionValid.textContent = `${validCount} ${fileLabel} selected`;
    selectionSkipped.textContent = `Skipped ${skippedCount}`;
    selectionSkipped.hidden = skippedCount <= 0;
    if (skippedCount > 0) {
      selectionSkipped.classList.add("is-skipped");
    } else {
      selectionSkipped.classList.remove("is-skipped");
    }

    selectionState.hidden = !scanningFolder;
    if (dropzone) {
      dropzone.classList.toggle("is-scanning", scanningFolder);
      dropzone.setAttribute("aria-busy", scanningFolder ? "true" : "false");
    }
    if (uploadForm) {
      uploadForm.classList.toggle("is-scanning", scanningFolder);
    }
    if (pickFilesButton) {
      pickFilesButton.disabled = scanningFolder;
    }
    if (pickFolderButton) {
      pickFolderButton.disabled = scanningFolder;
    }

    const canClear = scanningFolder || validCount > 0 || skippedCount > 0;
    clearSelectionButton.disabled = !canClear;

    const isReadyToQueue = !scanningFolder && validCount > 0;
    uploadSubmit.disabled = !isReadyToQueue;
    if (scanningFolder) {
      uploadSubmit.textContent = "Please wait…";
    } else if (validCount === 0) {
      uploadSubmit.textContent = "Queue uploads";
    } else {
      uploadSubmit.textContent = `Queue ${validCount} ${fileLabel}`;
    }

    if (validCount === 0) {
      dropzone.classList.remove("has-files");
    } else {
      dropzone.classList.add("has-files");
    }

    renderFileItems();
  }

  function setPendingItems(nextItems, nextSkipped = 0) {
    pendingItems.splice(0, pendingItems.length, ...nextItems);
    skippedCount = nextSkipped;
    showAllFiles = false;
    syncInputFiles(pendingItems);
    renderFileList();
  }

  function clearSelection() {
    scanToken += 1;
    scanningFolder = false;
    dragDepth = 0;
    if (dropzone) {
      dropzone.classList.remove("is-active");
    }
    if (fileInput) {
      fileInput.value = "";
    }
    if (folderInput) {
      folderInput.value = "";
    }
    setPendingItems([], 0);
  }

  function mergeItems(existing, incoming) {
    const merged = [...existing];
    const seen = new Set(existing.map(buildItemKey));
    incoming.forEach((item) => {
      const key = buildItemKey(item);
      if (!seen.has(key)) {
        merged.push(item);
        seen.add(key);
      }
    });
    return merged;
  }

  function readDirectoryEntries(directoryEntry) {
    const reader = directoryEntry.createReader();
    return new Promise((resolve) => {
      const entries = [];
      const readBatch = () => {
        reader.readEntries(
          (batch) => {
            if (!batch.length) {
              resolve(entries);
              return;
            }
            entries.push(...batch);
            readBatch();
          },
          () => resolve(entries)
        );
      };
      readBatch();
    });
  }

  async function traverseEntry(entry, pathPrefix) {
    if (!entry) {
      return [];
    }
    if (entry.isFile) {
      return new Promise((resolve) => {
        entry.file(
          (file) => resolve([{ file, displayPath: `${pathPrefix}${file.name}` }]),
          () => resolve([])
        );
      });
    }
    if (entry.isDirectory) {
      const nextPrefix = `${pathPrefix}${entry.name}/`;
      const children = await readDirectoryEntries(entry);
      const nested = await Promise.all(children.map((child) => traverseEntry(child, nextPrefix)));
      return nested.flat();
    }
    return [];
  }

  async function collectDroppedItems(dataTransfer) {
    if (!dataTransfer) {
      return { items: [], skipped: 0, usedEntries: false };
    }
    const dataItems = Array.from(dataTransfer.items || []);
    const entries = dataItems
      .map((item) =>
        typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null
      )
      .filter(Boolean);
    if (entries.length > 0) {
      const collected = await Promise.all(entries.map((entry) => traverseEntry(entry, "")));
      const rawItems = collected.flat();
      const prepared = prepareItems(rawItems);
      return { ...prepared, usedEntries: true };
    }
    const files = Array.from(dataTransfer.files || []);
    const rawItems = files.map((file) => ({ file, displayPath: file.name }));
    const prepared = prepareItems(rawItems);
    return { ...prepared, usedEntries: false };
  }

  function isFileDrag(event) {
    if (!event.dataTransfer) {
      return false;
    }
    const types = Array.from(event.dataTransfer.types || []);
    if (types.includes("Files") || types.includes("public.file-url")) {
      return true;
    }
    if (event.dataTransfer.files && event.dataTransfer.files.length > 0) {
      return true;
    }
    if (event.dataTransfer.items && event.dataTransfer.items.length > 0) {
      return true;
    }
    return false;
  }

  function initUploads() {
    if (app.uploads && app.uploads.__initialized) {
      return;
    }

    if (
      uploadForm &&
      fileInput &&
      dropzone &&
      fileList &&
      selectionValid &&
      selectionSkipped &&
      selectionState &&
      uploadSubmit &&
      clearSelectionButton
    ) {
      renderFileList();

      if (pickFilesButton) {
        pickFilesButton.addEventListener("click", () => fileInput.click());
      }

      if (pickFolderButton && folderInput) {
        pickFolderButton.addEventListener("click", () => folderInput.click());
      }

      clearSelectionButton.addEventListener("click", () => {
        clearSelection();
      });

      fileInput.addEventListener("change", () => {
        if (syncingInput) {
          return;
        }
        scanToken += 1;
        scanningFolder = false;
        const rawItems = Array.from(fileInput.files || []).map((file) => ({
          file,
          displayPath: file.webkitRelativePath || file.name,
        }));
        const prepared = prepareItems(rawItems);
        setPendingItems(prepared.items, prepared.skipped);
      });

      if (folderInput) {
        folderInput.addEventListener("change", () => {
          scanToken += 1;
          scanningFolder = false;
          const rawItems = Array.from(folderInput.files || []).map((file) => ({
            file,
            displayPath: file.webkitRelativePath || file.name,
          }));
          const prepared = prepareItems(rawItems);
          setPendingItems(prepared.items, prepared.skipped);
        });
      }

      if (fileListToggle) {
        fileListToggle.addEventListener("click", () => {
          showAllFiles = !showAllFiles;
          renderFileList();
        });
      }

      dropzone.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          fileInput.click();
        }
      });

      dropzone.addEventListener("dragenter", (event) => {
        if (!isFileDrag(event)) {
          return;
        }
        event.preventDefault();
        dragDepth += 1;
        dropzone.classList.add("is-active");
      });

      dropzone.addEventListener("dragover", (event) => {
        if (!isFileDrag(event)) {
          return;
        }
        event.preventDefault();
      });

      dropzone.addEventListener("dragleave", (event) => {
        if (!isFileDrag(event)) {
          return;
        }
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) {
          dropzone.classList.remove("is-active");
        }
      });

      dropzone.addEventListener("drop", async (event) => {
        if (!isFileDrag(event)) {
          return;
        }
        event.preventDefault();
        dragDepth = 0;
        dropzone.classList.remove("is-active");
        if (!event.dataTransfer) {
          return;
        }
        const dropToken = (scanToken += 1);
        const shouldScan = Array.from(event.dataTransfer.items || []).some((item) => {
          if (typeof item.webkitGetAsEntry !== "function") {
            return false;
          }
          const entry = item.webkitGetAsEntry();
          return entry && entry.isDirectory;
        });
        scanningFolder = shouldScan;
        if (shouldScan) {
          renderFileList();
        }
        let prepared;
        try {
          prepared = await collectDroppedItems(event.dataTransfer);
        } finally {
          if (dropToken === scanToken) {
            scanningFolder = false;
          }
        }
        if (dropToken !== scanToken) {
          renderFileList();
          return;
        }
        if (!prepared) {
          renderFileList();
          return;
        }
        const nextSkipped = skippedCount + prepared.skipped;
        if (prepared.items.length === 0) {
          skippedCount = nextSkipped;
          renderFileList();
          return;
        }
        const merged = mergeItems(pendingItems, prepared.items);
        setPendingItems(merged, nextSkipped);
      });

      fileList.addEventListener("click", (event) => {
        const target = event.target.closest("[data-remove-index]");
        if (!target) {
          return;
        }
        const index = Number(target.dataset.removeIndex);
        if (Number.isNaN(index)) {
          return;
        }
        const nextItems = pendingItems.slice();
        nextItems.splice(index, 1);
        setPendingItems(nextItems, skippedCount);
      });

      uploadForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (uploadInFlight || scanningFolder || pendingItems.length === 0) {
          return;
        }
        uploadInFlight = true;
        uploadSubmit.disabled = true;
        uploadSubmit.textContent = "Queuing…";
        try {
          const formData = new FormData();
          pendingItems.forEach((item) => {
            formData.append("files", item.file, item.displayPath || item.file.name);
          });
          const response = await fetch("/upload", {
            method: "POST",
            body: formData,
          });
          if (response.ok) {
            const count = pendingItems.length;
            const label = count === 1 ? "file" : "files";
            if (app.toasts) {
              app.toasts.storePendingToast({
                title: "Queue",
                message: `Queued ${count} ${label}.`,
                kind: "success",
                key: "queue:queued",
                cooldown: 0,
                duration: 5200,
              });
            }
            window.location = "/?tab=queue";
            return;
          }
          const message = await response.text();
          console.error("Upload failed", response.status, message);
          if (app.toasts) {
            app.toasts.notifySystem("Queue", "Couldn’t queue uploads. Try again.", "error", {
              key: "queue:queued:error",
              cooldown: 1500,
            });
          }
        } catch (error) {
          console.error("Upload failed", error);
          if (app.toasts) {
            app.toasts.notifySystem("Queue", "Couldn’t queue uploads. Try again.", "error", {
              key: "queue:queued:error",
              cooldown: 1500,
            });
          }
        } finally {
          uploadInFlight = false;
          renderFileList();
        }
      });
    }

    app.uploads = {
      __initialized: true,
      guideToUpload,
    };
  }

  app.uploads = app.uploads || {};
  app.uploads.init = initUploads;
})();
