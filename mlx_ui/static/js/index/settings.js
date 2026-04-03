(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }

  const {
    settingsForm,
    settingsSaveButton,
    settingsSaveState,
    settingsBannerSuccess,
    settingsBannerError,
    whisperModelError,
    cohereStatusLabel,
    cohereKeyMask,
    cohereKeyMaskValue,
    telegramStatusLabel,
    telegramTokenMask,
    telegramChatMask,
    telegramTokenMaskValue,
    telegramChatMaskValue,
    telegramTokenHint,
    telegramChatHint,
  } = app.dom || {};
  const cohereKeyHint = document.querySelector("[data-cohere-key-hint]");
  const cohereSetupTitle = document.querySelector("[data-cohere-setup-title]");
  const cohereSetupDesc = document.querySelector("[data-cohere-setup-desc]");
  const telegramSetupTitle = document.querySelector("[data-telegram-setup-title]");
  const telegramSetupDesc = document.querySelector("[data-telegram-setup-desc]");

  function getCohereSetupCopy(configured) {
    const locked = Boolean(document.getElementById("cohere-api-key")?.disabled);
    if (locked) {
      return {
        title: "View setup",
        desc: "Review the masked key and provider defaults.",
      };
    }
    if (configured) {
      return {
        title: "Edit setup",
        desc: "Saved credentials stay masked until you need to update them.",
      };
    }
    return {
      title: "Set up",
      desc: "Add a key only if you plan to use Cohere.",
    };
  }

  function getTelegramSetupCopy(configured) {
    const locked = Boolean(document.getElementById("telegram-token")?.disabled);
    if (locked) {
      return {
        title: "View setup",
        desc: "Review the masked delivery credentials.",
      };
    }
    if (configured) {
      return {
        title: "Edit setup",
        desc: "Saved credentials stay masked until you need to update them.",
      };
    }
    return {
      title: "Set up",
      desc: "Add a bot token and chat ID only if you want delivery in Telegram.",
    };
  }

  function normalizeSettingsText(value) {
    return String(value || "").trim();
  }

  function captureSettingsState(form) {
    const state = {};
    if (!form) {
      return state;
    }
    Array.from(form.elements).forEach((element) => {
      if (
        !(element instanceof HTMLInputElement) &&
        !(element instanceof HTMLSelectElement) &&
        !(element instanceof HTMLTextAreaElement)
      ) {
        return;
      }
      if (!element.name || element.disabled) {
        return;
      }
      if (element instanceof HTMLInputElement) {
        const type = element.type;
        if (type === "hidden" || type === "submit" || type === "button") {
          return;
        }
        if (type === "checkbox") {
          state[element.name] = element.checked;
          return;
        }
        if (type === "radio") {
          if (element.checked) {
            state[element.name] = normalizeSettingsText(element.value);
          }
          return;
        }
        state[element.name] = normalizeSettingsText(element.value);
        return;
      }
      if (element instanceof HTMLSelectElement) {
        state[element.name] = element.value;
        return;
      }
      state[element.name] = normalizeSettingsText(element.value);
    });
    return state;
  }

  function isSettingsDirty(current, baseline) {
    const keys = new Set([...Object.keys(current || {}), ...Object.keys(baseline || {})]);
    for (const key of keys) {
      if (current[key] !== baseline[key]) {
        return true;
      }
    }
    return false;
  }

  function updateSettingsSourcePills(snapshot) {
    if (!snapshot || !snapshot.sources) {
      return;
    }
    const sources = snapshot.sources || {};
    const allowed = new Set(["env", "file", "default", "missing"]);
    document.querySelectorAll("[data-settings-source-pill]").forEach((pill) => {
      const key = pill.getAttribute("data-settings-source-pill") || "";
      if (!key) {
        return;
      }
      const source = sources[key];
      if (!source) {
        return;
      }
      const normalized = allowed.has(source) ? source : "missing";
      pill.textContent = normalized;
      pill.setAttribute("title", `Value source: ${normalized}`);
      pill.classList.remove("is-env", "is-file", "is-default", "is-missing");
      pill.classList.add(`is-${normalized}`);
    });
  }

  function updateTelegramSnapshot(snapshot) {
    if (!snapshot) {
      return;
    }
    const configured = Boolean(snapshot.configured);
    const setupCopy = getTelegramSetupCopy(configured);

    if (telegramStatusLabel) {
      telegramStatusLabel.textContent = configured ? "Configured" : "Not configured";
    }
    if (telegramSetupTitle) {
      telegramSetupTitle.textContent = setupCopy.title;
    }
    if (telegramSetupDesc) {
      telegramSetupDesc.textContent = setupCopy.desc;
    }
    if (telegramTokenHint) {
      telegramTokenHint.textContent = configured
        ? "Leave blank to keep the saved token."
        : "Add your bot token.";
    }
    if (telegramChatHint) {
      telegramChatHint.textContent = configured
        ? "Leave blank to keep the saved chat ID."
        : "Use the numeric chat ID for your target chat.";
    }
    if (telegramTokenMask) {
      const masked = snapshot.token_masked ? String(snapshot.token_masked) : "";
      if (telegramTokenMaskValue) {
        telegramTokenMaskValue.textContent = masked || "••••";
      } else {
        telegramTokenMask.textContent = masked ? `Current: ${masked}` : "Current: ••••";
      }
      telegramTokenMask.hidden = !configured;
    }
    if (telegramChatMask) {
      const masked = snapshot.chat_id_masked ? String(snapshot.chat_id_masked) : "";
      if (telegramChatMaskValue) {
        telegramChatMaskValue.textContent = masked || "••••";
      } else {
        telegramChatMask.textContent = masked ? `Current: ${masked}` : "Current: ••••";
      }
      telegramChatMask.hidden = !configured;
    }
  }

  function updateCohereSnapshot(snapshot) {
    if (!snapshot) {
      return;
    }
    const configured = Boolean(snapshot.configured);
    const setupCopy = getCohereSetupCopy(configured);

    if (cohereStatusLabel) {
      cohereStatusLabel.textContent = configured ? "Configured" : "Not configured";
    }
    if (cohereSetupTitle) {
      cohereSetupTitle.textContent = setupCopy.title;
    }
    if (cohereSetupDesc) {
      cohereSetupDesc.textContent = setupCopy.desc;
    }
    if (cohereKeyHint) {
      cohereKeyHint.textContent = configured
        ? "Leave blank to keep the saved key."
        : "Add a key only if you plan to use Cohere.";
    }
    if (cohereKeyMask) {
      const masked = snapshot.api_key_masked ? String(snapshot.api_key_masked) : "";
      if (cohereKeyMaskValue) {
        cohereKeyMaskValue.textContent = masked || "••••";
      } else {
        cohereKeyMask.textContent = masked ? `Current: ${masked}` : "Current: ••••";
      }
      cohereKeyMask.hidden = !masked;
    }
  }

  function setSettingsBanner(element, message) {
    if (!element) {
      return;
    }
    element.textContent = message;
    element.hidden = !message;
  }

  function setSettingsSaveState(kind, message) {
    if (!settingsSaveState) {
      return;
    }
    settingsSaveState.classList.remove("is-dirty", "is-success", "is-error");
    if (kind) {
      settingsSaveState.classList.add(kind);
    }
    settingsSaveState.textContent = message || "";
  }

  function initSettings() {
    if (app.settings && app.settings.__initialized) {
      return;
    }

    if (settingsForm && settingsSaveButton && settingsSaveState) {
      let baselineState = captureSettingsState(settingsForm);
      let savingSettings = false;
      let hasSavedOnce = settingsBannerSuccess ? !settingsBannerSuccess.hidden : false;
      const saveLabel = settingsSaveButton.textContent;
      const cohereKeyInput = settingsForm.querySelector("#cohere-api-key");
      const cohereModelInput = settingsForm.querySelector("#cohere-model");
      const clearCohereKey = settingsForm.querySelector("input[name='clear_cohere_api_key']");
      const whisperModelInput = settingsForm.querySelector("#whisper-model");
      const telegramTokenInput = settingsForm.querySelector("#telegram-token");
      const telegramChatInput = settingsForm.querySelector("#telegram-chat-id");
      const clearTelegramToken = settingsForm.querySelector("input[name='clear_telegram_token']");
      const clearTelegramChat = settingsForm.querySelector("input[name='clear_telegram_chat_id']");

      function notifySystem(titleText, bodyText, kind, options) {
        if (app.toasts) {
          app.toasts.notifySystem(titleText, bodyText, kind, options);
        }
      }

      function clearSettingsErrors() {
        if (settingsBannerError) {
          settingsBannerError.hidden = true;
          settingsBannerError.textContent = "";
        }
        if (whisperModelInput) {
          whisperModelInput.classList.remove("is-invalid");
        }
        if (whisperModelError) {
          whisperModelError.hidden = true;
          whisperModelError.textContent = "";
        }
      }

      function validateSettingsForUi(current) {
        if (!whisperModelInput || whisperModelInput.disabled) {
          return { valid: true };
        }
        const value = current.whisper_model || "";
        const baseline = baselineState.whisper_model || "";
        if (!value && baseline) {
          whisperModelInput.classList.add("is-invalid");
          if (whisperModelError) {
            whisperModelError.textContent = "Whisper model can’t be blank.";
            whisperModelError.hidden = false;
          }
          return { valid: false };
        }
        whisperModelInput.classList.remove("is-invalid");
        if (whisperModelError) {
          whisperModelError.hidden = true;
          whisperModelError.textContent = "";
        }
        return { valid: true };
      }

      function updateSettingsSaveUi() {
        const current = captureSettingsState(settingsForm);
        const dirty = isSettingsDirty(current, baselineState);
        const validation = validateSettingsForUi(current);
        const canSave = dirty && validation.valid && !savingSettings;

        settingsSaveButton.disabled = !canSave;
        if (!savingSettings) {
          settingsSaveButton.textContent = saveLabel;
        }

        if (dirty && settingsBannerSuccess) {
          settingsBannerSuccess.hidden = true;
        }
        if (dirty && settingsBannerError) {
          settingsBannerError.hidden = true;
          settingsBannerError.textContent = "";
        }

        if (savingSettings) {
          setSettingsSaveState("", "Saving…");
          return;
        }
        if (!dirty) {
          setSettingsSaveState(hasSavedOnce ? "is-success" : "", hasSavedOnce ? "Saved" : "No changes");
          return;
        }
        if (!validation.valid) {
          setSettingsSaveState("is-error", "Fix highlighted fields");
          return;
        }
        setSettingsSaveState("is-dirty", "Unsaved changes");
      }

      function buildSettingsUpdatePayload(current) {
        const updates = {};

        if ("engine" in current && current.engine !== baselineState.engine) {
          updates.engine = current.engine;
        }
        if ("wtm_quick" in current && current.wtm_quick !== baselineState.wtm_quick) {
          updates.wtm_quick = current.wtm_quick;
        }
        if ("default_language" in current && current.default_language !== baselineState.default_language) {
          updates.default_language = current.default_language;
        }
        if ("cohere_model" in current && current.cohere_model !== baselineState.cohere_model) {
          updates.cohere_model = current.cohere_model;
        }
        if (
          "update_check_enabled" in current &&
          current.update_check_enabled !== baselineState.update_check_enabled
        ) {
          updates.update_check_enabled = current.update_check_enabled;
        }
        if ("log_level" in current && current.log_level !== baselineState.log_level) {
          updates.log_level = current.log_level;
        }
        if ("whisper_model" in current && current.whisper_model !== baselineState.whisper_model) {
          updates.whisper_model = current.whisper_model;
        }

        if (current.clear_cohere_api_key) {
          updates.cohere_api_key = "";
        } else if (current.cohere_api_key && current.cohere_api_key !== baselineState.cohere_api_key) {
          updates.cohere_api_key = current.cohere_api_key;
        }

        if (current.clear_telegram_token) {
          updates.telegram_token = "";
        } else if (current.telegram_token && current.telegram_token !== baselineState.telegram_token) {
          updates.telegram_token = current.telegram_token;
        }

        if (current.clear_telegram_chat_id) {
          updates.telegram_chat_id = "";
        } else if (
          current.telegram_chat_id &&
          current.telegram_chat_id !== baselineState.telegram_chat_id
        ) {
          updates.telegram_chat_id = current.telegram_chat_id;
        }

        return updates;
      }

      settingsForm.addEventListener("input", () => {
        if (savingSettings) {
          return;
        }
        if (settingsBannerError) {
          settingsBannerError.hidden = true;
          settingsBannerError.textContent = "";
        }
        updateSettingsSaveUi();
      });
      settingsForm.addEventListener("change", () => {
        if (savingSettings) {
          return;
        }
        if (settingsBannerError) {
          settingsBannerError.hidden = true;
          settingsBannerError.textContent = "";
        }
        updateSettingsSaveUi();
      });

      settingsForm.addEventListener("submit", async (event) => {
        if (event.defaultPrevented) {
          return;
        }
        if (!window.fetch) {
          return;
        }
        event.preventDefault();
        if (savingSettings) {
          return;
        }

        clearSettingsErrors();
        const current = captureSettingsState(settingsForm);
        const dirty = isSettingsDirty(current, baselineState);
        const validation = validateSettingsForUi(current);
        if (!dirty) {
          updateSettingsSaveUi();
          return;
        }
        if (!validation.valid) {
          updateSettingsSaveUi();
          if (whisperModelInput) {
            whisperModelInput.focus();
          }
          return;
        }

        const updates = buildSettingsUpdatePayload(current);
        if (Object.keys(updates).length === 0) {
          updateSettingsSaveUi();
          return;
        }

        savingSettings = true;
        settingsSaveButton.disabled = true;
        settingsSaveButton.textContent = "Saving…";
        setSettingsBanner(settingsBannerError, "");
        setSettingsBanner(settingsBannerSuccess, "");
        setSettingsSaveState("", "Saving…");

        try {
          const response = await fetch("/api/settings", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(updates),
          });

          let payload = null;
          try {
            payload = await response.json();
          } catch (error) {
            payload = null;
          }

          if (!response.ok) {
            let message = "Unable to save settings. Please try again.";
            if (payload && payload.detail) {
              if (Array.isArray(payload.detail)) {
                message = payload.detail.join(" ");
              } else if (typeof payload.detail === "string") {
                message = payload.detail;
              }
            }
            setSettingsBanner(settingsBannerError, message);
            hasSavedOnce = false;
            setSettingsSaveState("is-error", "Save failed");
            return;
          }

          hasSavedOnce = true;
          updateSettingsSourcePills(payload);
          if (payload && payload.cohere_snapshot) {
            updateCohereSnapshot(payload.cohere_snapshot);
          }
          if (payload && payload.telegram_snapshot) {
            updateTelegramSnapshot(payload.telegram_snapshot);
          }

          if (cohereKeyInput) {
            cohereKeyInput.value = "";
          }
          if (clearCohereKey instanceof HTMLInputElement) {
            clearCohereKey.checked = false;
          }
          if (cohereModelInput && payload && payload.settings) {
            cohereModelInput.value = payload.settings.cohere_model || "";
          }
          if (telegramTokenInput) {
            telegramTokenInput.value = "";
          }
          if (telegramChatInput) {
            telegramChatInput.value = "";
          }
          if (clearTelegramToken instanceof HTMLInputElement) {
            clearTelegramToken.checked = false;
          }
          if (clearTelegramChat instanceof HTMLInputElement) {
            clearTelegramChat.checked = false;
          }

          baselineState = captureSettingsState(settingsForm);
          setSettingsBanner(settingsBannerSuccess, "Settings saved.");
          setSettingsSaveState("is-success", "Saved");
          notifySystem("Settings", "Saved.", "success", {
            key: "settings:saved",
            cooldown: 1200,
            duration: 4200,
          });
        } catch (error) {
          console.warn("Failed to save settings", error);
          setSettingsBanner(
            settingsBannerError,
            "Unable to save settings. Please try again (your changes are still here)."
          );
          setSettingsSaveState("is-error", "Save failed");
        } finally {
          savingSettings = false;
          settingsSaveButton.textContent = saveLabel;
          updateSettingsSaveUi();
        }
      });

      updateSettingsSaveUi();
    }

    app.settings = {
      __initialized: true,
    };
  }

  app.settings = app.settings || {};
  app.settings.init = initSettings;
})();
