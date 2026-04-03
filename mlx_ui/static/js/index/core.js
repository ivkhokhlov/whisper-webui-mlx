(function () {
  const app = (window.mlxUiIndex = window.mlxUiIndex || {});
  if (app.__coreInitialized) {
    return;
  }
  app.__coreInitialized = true;

  app.constants = {
    TAB_STORAGE_KEY: "mlx-ui:last-tab",
    PENDING_TOAST_STORAGE_KEY: "mlx-ui:pending-toast",
    HISTORY_VIEW_STORAGE_KEY: "mlx-ui:history-view",
    HISTORY_SORT_VALUES: new Set(["newest", "oldest", "name"]),
    HISTORY_STATUS_VALUES: new Set(["all", "done", "failed"]),
  };

  app.dom = {
    tabs: Array.from(document.querySelectorAll("[data-tab]")),
    panels: document.querySelectorAll("[data-panel]"),
    queueList: document.getElementById("queue-list"),
    queuePlaceholder: document.getElementById("queue-placeholder"),
    historyList: document.getElementById("history-list"),
    historyPlaceholder: document.getElementById("history-placeholder"),
    historyClearButton: document.querySelector("[data-history-clear]"),
    historySearch: document.getElementById("history-search"),
    historyStatus: document.getElementById("history-status"),
    historySort: document.getElementById("history-sort"),
    historyViewSummary: document.getElementById("history-view-summary"),
    historyFilterEmpty: document.getElementById("history-filter-empty"),
    historyClearFilters: document.getElementById("history-clear-filters"),
    settingsForm: document.querySelector(".settings-form"),
    settingsBannerSuccess: document.getElementById("settings-banner-success"),
    settingsBannerError: document.getElementById("settings-banner-error"),
    whisperModelError: document.getElementById("settings-error-whisper-model"),
    cohereStatusLabel: document.querySelector("[data-cohere-status]"),
    cohereSourcePill: document.querySelector("[data-cohere-source-pill]"),
    cohereKeyMask: document.querySelector("[data-cohere-key-mask]"),
    cohereKeyMaskValue: document.querySelector("[data-cohere-key-mask-value]"),
    telegramStatusLabel: document.querySelector("[data-telegram-status]"),
    telegramSourcePill: document.querySelector("[data-telegram-source-pill]"),
    telegramTokenMask: document.querySelector("[data-telegram-token-mask]"),
    telegramChatMask: document.querySelector("[data-telegram-chat-mask]"),
    telegramTokenMaskValue: document.querySelector("[data-telegram-token-mask-value]"),
    telegramChatMaskValue: document.querySelector("[data-telegram-chat-mask-value]"),
    telegramTokenHint: document.querySelector("[data-telegram-token-hint]"),
    telegramChatHint: document.querySelector("[data-telegram-chat-hint]"),
    workerCard: document.getElementById("worker-card"),
    workerStatus: document.getElementById("worker-status"),
    workerCurrent: document.getElementById("worker-current"),
    workerFilename: document.getElementById("worker-filename"),
    workerMeta: document.getElementById("worker-meta"),
    workerQueued: document.getElementById("worker-queued"),
    workerElapsed: document.getElementById("worker-elapsed"),
    workerContext: document.getElementById("worker-context"),
    queueCountEls: document.querySelectorAll("[data-queue-count]"),
    toastStack: document.getElementById("toast-stack"),
    previewModal: document.getElementById("preview-modal"),
    previewModalTitle: document.getElementById("preview-modal-title"),
    previewModalMeta: document.getElementById("preview-modal-meta"),
    previewModalText: document.getElementById("preview-modal-text"),
    previewModalCopy: document.getElementById("preview-modal-copy"),
    previewModalOpenLink: document.getElementById("preview-modal-open"),
    previewModalDownloadLink: document.getElementById("preview-modal-download"),
    confirmModal: document.getElementById("confirm-modal"),
    confirmModalTitle: document.getElementById("confirm-modal-title"),
    confirmModalMessage: document.getElementById("confirm-modal-message"),
    uploadForm: document.querySelector(".upload-card"),
    fileInput: document.getElementById("file-input"),
    folderInput: document.getElementById("folder-input"),
    dropzone: document.getElementById("dropzone"),
    fileList: document.getElementById("file-list"),
    selectionValid: document.getElementById("selection-valid"),
    selectionSkipped: document.getElementById("selection-skipped"),
    selectionState: document.getElementById("selection-state"),
    fileListToggle: document.getElementById("file-list-toggle"),
    uploadSubmit: document.getElementById("upload-submit"),
    clearSelectionButton: document.getElementById("clear-selection"),
    pickFilesButton: document.querySelector("[data-upload-pick='files']"),
    pickFolderButton: document.querySelector("[data-upload-pick='folder']"),
    queueEmptyCta: document.querySelector("[data-queue-empty-cta]"),
    historyEmptyCta: document.querySelector("[data-history-empty-cta]"),
  };

  app.dom.confirmModalOk = app.dom.confirmModal
    ? app.dom.confirmModal.querySelector("[data-confirm-ok]")
    : null;
  app.dom.confirmModalCancel = app.dom.confirmModal
    ? app.dom.confirmModal.querySelector("[data-confirm-cancel]")
    : null;
  app.dom.settingsSaveButton = app.dom.settingsForm
    ? app.dom.settingsForm.querySelector("[data-settings-save]")
    : null;
  app.dom.settingsSaveState = app.dom.settingsForm
    ? app.dom.settingsForm.querySelector("[data-settings-save-state]")
    : null;
})();
