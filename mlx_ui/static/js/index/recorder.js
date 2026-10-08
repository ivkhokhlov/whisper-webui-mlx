(function () {
  const app = window.mlxUiIndex;
  if (!app) {
    return;
  }
  if (app.recorder && app.recorder.__initialized) {
    return;
  }

  const MIME_CANDIDATES = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];

  const EXTENSION_TOKENS = [
    ["webm", "webm"],
    ["ogg", "ogg"],
    ["mp4", "m4a"],
    ["mpeg", "mp3"],
    ["wav", "wav"],
  ];

  function pickMimeType() {
    if (!window.MediaRecorder || typeof MediaRecorder.isTypeSupported !== "function") {
      return "";
    }
    return MIME_CANDIDATES.find((candidate) => MediaRecorder.isTypeSupported(candidate)) || "";
  }

  function extensionForType(type) {
    const normalized = (type || "").toLowerCase();
    const match = EXTENSION_TOKENS.find(([token]) => normalized.includes(token));
    return match ? match[1] : "webm";
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function formatTimestamp(date) {
    return (
      `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}` +
      `-${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`
    );
  }

  function formatClock(totalSeconds) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${pad2(minutes)}:${pad2(seconds)}`;
  }

  function initRecorder() {
    const dom = app.dom || {};
    const card = dom.recordCard;
    const startButton = dom.recordStart;
    const stopButton = dom.recordStop;
    const statusEl = dom.recordStatus;
    const preview = dom.recordPreview;
    const playback = dom.recordPlayback;
    const nameEl = dom.recordName;
    const addButton = dom.recordAdd;
    const discardButton = dom.recordDiscard;
    if (!card || !startButton || !stopButton || !preview || !playback || !addButton || !discardButton) {
      return;
    }

    const supported = Boolean(
      navigator.mediaDevices &&
        typeof navigator.mediaDevices.getUserMedia === "function" &&
        window.MediaRecorder
    );
    if (!supported) {
      card.hidden = true;
      return;
    }

    let stream = null;
    let recorder = null;
    let chunks = [];
    let blob = null;
    let blobUrl = null;
    let filename = "";
    let timerId = null;
    let startedAt = 0;
    let uploadInFlight = false;

    function notifyError(message) {
      if (app.toasts) {
        app.toasts.notifySystem("Record audio", message, "error", {
          key: "record:error",
          cooldown: 1500,
        });
      }
    }

    function setStatus(text, isRecording) {
      if (!statusEl) {
        return;
      }
      statusEl.textContent = text;
      statusEl.classList.toggle("is-recording", Boolean(isRecording));
    }

    function updateTimer() {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      setStatus(`Recording ${formatClock(elapsed)}`, true);
    }

    function releaseStream() {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
      }
    }

    function resetToIdle() {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
        blobUrl = null;
      }
      blob = null;
      chunks = [];
      filename = "";
      playback.removeAttribute("src");
      playback.load();
      preview.hidden = true;
      stopButton.hidden = true;
      startButton.hidden = false;
      startButton.disabled = false;
      setStatus("", false);
    }

    function finalizeRecording() {
      if (timerId) {
        clearInterval(timerId);
        timerId = null;
      }
      releaseStream();
      const type = (recorder && recorder.mimeType) || (chunks[0] && chunks[0].type) || "";
      recorder = null;
      const recorded = new Blob(chunks, { type });
      if (recorded.size === 0) {
        resetToIdle();
        notifyError("Recording is empty. Try again.");
        return;
      }
      blob = recorded;
      filename = `recording-${formatTimestamp(new Date())}.${extensionForType(type)}`;
      blobUrl = URL.createObjectURL(blob);
      playback.src = blobUrl;
      if (nameEl) {
        const size = app.utils ? app.utils.formatBytes(blob.size) : `${blob.size} B`;
        nameEl.textContent = `${filename} · ${size}`;
      }
      preview.hidden = false;
      stopButton.hidden = true;
      startButton.hidden = false;
      setStatus("", false);
    }

    async function startRecording() {
      if (recorder || uploadInFlight) {
        return;
      }
      resetToIdle();
      startButton.disabled = true;
      setStatus("Requesting microphone…", false);
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (error) {
        console.error("Microphone access failed", error);
        startButton.disabled = false;
        setStatus("Microphone unavailable.", false);
        notifyError("Microphone access was denied or no microphone was found.");
        return;
      }
      chunks = [];
      const mimeType = pickMimeType();
      try {
        recorder = mimeType
          ? new MediaRecorder(stream, { mimeType })
          : new MediaRecorder(stream);
      } catch (error) {
        console.error("MediaRecorder init failed", error);
        recorder = null;
        releaseStream();
        startButton.disabled = false;
        setStatus("Recording is not supported here.", false);
        notifyError("Audio recording is not supported in this browser.");
        return;
      }
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) {
          chunks.push(event.data);
        }
      });
      recorder.addEventListener("stop", finalizeRecording);
      recorder.start();
      startedAt = Date.now();
      timerId = setInterval(updateTimer, 500);
      updateTimer();
      startButton.hidden = true;
      startButton.disabled = false;
      stopButton.hidden = false;
    }

    function stopRecording() {
      if (recorder && recorder.state !== "inactive") {
        setStatus("Finishing…", false);
        recorder.stop();
      }
    }

    async function addToQueue() {
      if (!blob || uploadInFlight) {
        return;
      }
      uploadInFlight = true;
      addButton.disabled = true;
      discardButton.disabled = true;
      addButton.textContent = "Queuing…";
      try {
        const formData = new FormData();
        formData.append("files", blob, filename);
        const response = await fetch("/upload", {
          method: "POST",
          body: formData,
        });
        if (response.ok) {
          if (app.toasts) {
            app.toasts.storePendingToast({
              title: "Queue",
              message: "Added recording to queue.",
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
        console.error("Recording upload failed", response.status, message);
        notifyError("Can’t add the recording to queue. Try again.");
      } catch (error) {
        console.error("Recording upload failed", error);
        notifyError("Can’t add the recording to queue. Try again.");
      } finally {
        uploadInFlight = false;
        addButton.disabled = false;
        discardButton.disabled = false;
        addButton.textContent = "Add to queue";
      }
    }

    startButton.addEventListener("click", startRecording);
    stopButton.addEventListener("click", stopRecording);
    discardButton.addEventListener("click", resetToIdle);
    addButton.addEventListener("click", addToQueue);

    app.recorder.__initialized = true;
  }

  app.recorder = app.recorder || {};
  app.recorder.init = initRecorder;
})();
