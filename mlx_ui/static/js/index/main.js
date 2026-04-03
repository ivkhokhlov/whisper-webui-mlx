(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const tabs = Array.isArray(app.dom?.tabs) ? app.dom.tabs : [];
  if (!tabs.length) {
    return;
  }

  if (app.tabs && typeof app.tabs.init === "function") {
    app.tabs.init();
  }
  if (app.toasts && typeof app.toasts.init === "function") {
    app.toasts.init();
  }
  if (app.modals && typeof app.modals.init === "function") {
    app.modals.init();
  }
  if (app.historyView && typeof app.historyView.init === "function") {
    app.historyView.init();
  }
  if (app.state && typeof app.state.init === "function") {
    app.state.init();
  }
  if (app.uploads && typeof app.uploads.init === "function") {
    app.uploads.init();
  }
  if (app.settings && typeof app.settings.init === "function") {
    app.settings.init();
  }
  if (app.queueActions && typeof app.queueActions.init === "function") {
    app.queueActions.init();
  }
  if (app.historyActions && typeof app.historyActions.init === "function") {
    app.historyActions.init();
  }
  if (app.storageActions && typeof app.storageActions.init === "function") {
    app.storageActions.init();
  }

  const { queueEmptyCta, historyEmptyCta } = app.dom || {};
  if (queueEmptyCta) {
    queueEmptyCta.addEventListener("click", (event) => {
      event.preventDefault();
      if (app.tabs) {
        app.tabs.activate("queue", { updateHistory: true });
      }
      if (app.uploads) {
        app.uploads.guideToUpload({ openPicker: true });
      }
    });
  }

  if (historyEmptyCta) {
    historyEmptyCta.addEventListener("click", (event) => {
      event.preventDefault();
      if (app.tabs) {
        app.tabs.activate("queue", { updateHistory: true });
      }
      if (app.uploads) {
        app.uploads.guideToUpload();
      }
    });
  }

  if (app.time) {
    app.time.hydrateTimestamps(document);
    app.time.hydrateElapsed(document);
    app.time.hydrateTimeMeta(document);
  }
  if (app.modals) {
    app.modals.wireHistoryDetails(app.dom.historyList);
    app.modals.wireHistoryMenus(app.dom.historyList);
  }

  if (app.workerCard) {
    app.workerCard.updateElapsed();
  }
  if (app.dom && app.dom.queueList && app.time) {
    app.time.hydrateElapsed(app.dom.queueList);
  }
  setInterval(() => {
    if (app.workerCard) {
      app.workerCard.updateElapsed();
    }
    if (app.dom && app.dom.queueList && app.time) {
      app.time.hydrateElapsed(app.dom.queueList);
    }
  }, 1000);

  if (app.state) {
    setInterval(app.state.refreshState, 2500);
    app.state.refreshState();
  }
})();

