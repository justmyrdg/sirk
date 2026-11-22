(() => {
  "use strict";

  // Ask before submitting forms marked with data-confirm (delete buttons).
  document.addEventListener("submit", event => {
    const message = event.target.dataset && event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  // ---- Face camera flows -------------------------------------------------
  // Pages mark one element with data-flow: a <form> (setup, register) whose
  // fields are sent with the photo, or a <button> (login, reenroll).
  const endpoints = {
    setup: "/api/setup-admin",
    register: "/api/register-admin",
    login: "/api/login/face",
    reenroll: "/api/admin/face",
    verify: "/api/admin/verify-face"
  };
  const CONFIRM_FIRST = "Confirm it's you first.";
  const trigger = document.querySelector("[data-flow]");
  if (!trigger) return;

  // "Confirm it's you" with a password (accounts whose saved face can't be checked).
  if (trigger.dataset.flow === "verify-password") {
    const errorBox = document.querySelector("[data-camera-error]");
    trigger.addEventListener("submit", async event => {
      event.preventDefault();
      errorBox.hidden = true;
      const token = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
      try {
        const response = await fetch("/api/admin/verify-password", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
          body: JSON.stringify({ password: new FormData(trigger).get("password") })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || "The request could not be completed.");
        window.location.assign(trigger.dataset.next || "/");
      } catch (error) {
        errorBox.textContent = error.message;
        errorBox.hidden = false;
      }
    });
    return;
  }

  const panel = document.getElementById("face-capture");
  const video = document.getElementById("face-video");
  const errorBox = document.querySelector("[data-camera-error]");
  const csrfToken = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  let stream = null;
  let account = null;

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.hidden = true;
  }

  function stopCamera() {
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    video.srcObject = null;
    panel.hidden = true;
  }

  async function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("The camera is unavailable. Open the site over HTTPS or localhost and allow camera access.");
    }
    panel.hidden = false;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false
      });
      video.srcObject = stream;
      await video.play();
    } catch (error) {
      stopCamera();
      if (error.name === "NotAllowedError") throw new Error("Camera permission was denied. Allow camera access in your browser settings and try again.");
      if (error.name === "NotFoundError") throw new Error("No camera was found on this device.");
      throw new Error(`Could not open the camera: ${error.message}`);
    }
  }

  async function capturePhoto() {
    if (!video.videoWidth || !video.videoHeight) throw new Error("The camera is not ready yet. Please try again.");
    const scale = Math.min(1, 720 / Math.max(video.videoWidth, video.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.82));
    if (!blob) throw new Error("Could not capture the camera image. Please try again.");
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("Could not read the camera image."));
      reader.readAsDataURL(blob);
    });
    return dataUrl.split(",", 2)[1];
  }

  async function send(faceImage) {
    let response;
    try {
      response = await fetch(endpoints[trigger.dataset.flow], {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
        body: JSON.stringify({ ...(account || {}), faceImage })
      });
    } catch (error) {
      throw new Error("Could not reach the server. Check your connection and try again.");
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || "The request could not be completed.");
  }

  async function begin() {
    clearError();
    if (trigger.tagName === "FORM") {
      const fields = Object.fromEntries(new FormData(trigger).entries());
      if (fields.password !== fields.confirm) {
        showError("The passwords do not match.");
        return;
      }
      account = { email: fields.email.trim().toLowerCase(), password: fields.password };
    }
    try {
      await startCamera();
    } catch (error) {
      showError(error.message);
    }
  }

  if (trigger.tagName === "FORM") {
    trigger.addEventListener("submit", event => {
      event.preventDefault();
      begin();
    });
  } else {
    trigger.addEventListener("click", begin);
  }

  panel.addEventListener("click", async event => {
    const action = event.target.closest("[data-camera]");
    if (!action) return;
    if (action.dataset.camera === "cancel") {
      stopCamera();
      return;
    }
    action.disabled = true;
    try {
      const faceImage = await capturePhoto();
      stopCamera();
      await send(faceImage);
      window.location.assign(trigger.dataset.next || "/");
    } catch (error) {
      stopCamera();
      showError(error.message);
      // The 5-minute confirmation ran out: go back to step 1.
      if (error.message === CONFIRM_FIRST) setTimeout(() => window.location.reload(), 2000);
    } finally {
      action.disabled = false;
    }
  });
})();
