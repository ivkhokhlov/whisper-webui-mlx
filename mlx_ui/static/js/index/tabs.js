(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  function initTabs() {
    if (app.tabs && app.tabs.__initialized) {
      return;
    }

    const tabs = Array.isArray(app.dom?.tabs) ? app.dom.tabs : [];
    const panels = app.dom?.panels;
    if (!tabs.length || !panels) {
      app.tabs = {
        __initialized: true,
        activate: () => {},
      };
      return;
    }

    const tabNames = new Set(tabs.map((tab) => tab.dataset.tab));
    const TAB_STORAGE_KEY =
      (app.constants && app.constants.TAB_STORAGE_KEY) || "mlx-ui:last-tab";

    function updateUrl(tabName, replace) {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", tabName);
      if (!replace && url.toString() === window.location.href) {
        return;
      }
      const state = { tab: tabName };
      if (replace) {
        history.replaceState(state, "", url);
      } else {
        history.pushState(state, "", url);
      }
    }

    function activate(tabName, options = {}) {
      const { updateHistory = false, replaceHistory = false } = options;
      if (!tabNames.has(tabName)) {
        return;
      }
      tabs.forEach((tab) => {
        const isActive = tab.dataset.tab === tabName;
        tab.classList.toggle("is-active", isActive);
        if (isActive) {
          tab.setAttribute("aria-current", "page");
        } else {
          tab.removeAttribute("aria-current");
        }
      });

      panels.forEach((panel) => {
        const isActive = panel.dataset.panel === tabName;
        panel.classList.toggle("is-active", isActive);
        panel.hidden = !isActive;
      });

      try {
        localStorage.setItem(TAB_STORAGE_KEY, tabName);
      } catch (error) {
        // localStorage may be disabled; UI should still work.
      }

      if (updateHistory) {
        updateUrl(tabName, replaceHistory);
      }
    }

    function tabFromUrl() {
      const initialTab = new URLSearchParams(window.location.search).get("tab");
      return tabNames.has(initialTab) ? initialTab : null;
    }

    let storedTab = null;
    try {
      const candidate = localStorage.getItem(TAB_STORAGE_KEY);
      storedTab = tabNames.has(candidate) ? candidate : null;
    } catch (error) {
      storedTab = null;
    }

    const initialFromUrl = tabFromUrl();
    const initialTab = initialFromUrl || storedTab || "queue";
    activate(initialTab, {
      updateHistory: !initialFromUrl,
      replaceHistory: true,
    });

    tabs.forEach((tab) => {
      tab.addEventListener("click", (event) => {
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }
        event.preventDefault();
        activate(tab.dataset.tab, { updateHistory: true });
      });
    });

    window.addEventListener("popstate", () => {
      const tabName = tabFromUrl() || "queue";
      activate(tabName);
    });

    app.tabs = {
      __initialized: true,
      activate,
    };
  }

  app.tabs = app.tabs || {};
  app.tabs.init = initTabs;
})();

