  const bindScrollButton = (button, direction) => {
    let holdTimerId = null;
    let continuousScrollStarted = false;
    const clearHoldTimer = () => {
      if (holdTimerId === null) return;
      clearTimeout(holdTimerId);
      holdTimerId = null;
    };
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      continuousScrollStarted = false;
      button.setPointerCapture?.(event.pointerId);
      holdTimerId = setTimeout(() => {
        continuousScrollStarted = true;
        startContinuousScroll(direction);
      }, HOLD_START_DELAY_MS);
    });
    button.addEventListener("pointerup", () => {
      clearHoldTimer();
      if (continuousScrollStarted) {
        stopContinuousScroll();
        continuousScrollStarted = false;
        return;
      }
      scrollChatStep(direction);
    });
    button.addEventListener("pointercancel", () => {
      clearHoldTimer();
      if (!continuousScrollStarted) return;
      stopContinuousScroll();
      continuousScrollStarted = false;
    });
    button.addEventListener("pointerleave", () => {
      clearHoldTimer();
      if (!continuousScrollStarted) return;
      stopContinuousScroll();
      continuousScrollStarted = false;
    });
  };
  const createFloatingButton = (id, label, title, direction) => {
    const button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.className = FLOATING_BUTTON_CLASS_NAME;
    button.textContent = label;
    button.title = title;
    button.setAttribute("aria-label", title);
    bindScrollButton(button, direction);
    return button;
  };
  const installFloatingButtons = () => {
    if (!shouldInstallControls()) {
      removeFloatingButtons();
      return;
    }
    if (!document.body || !window[KEY]?.scrollButtonsEnabled) return;
    if (!document.getElementById(SCROLL_UP_BUTTON_ID)) {
      document.body.append(createFloatingButton(SCROLL_UP_BUTTON_ID, "\u25B2", "Agents RTL scroll older messages", -1));
    }
    if (!document.getElementById(SCROLL_DOWN_BUTTON_ID)) {
      document.body.append(createFloatingButton(SCROLL_DOWN_BUTTON_ID, "\u25BC", "Agents RTL scroll newer messages", 1));
    }
    updateEdgeButtonPositions();
  };
  const removeFloatingButtons = () => {
    stopContinuousScroll();
    document.getElementById(SCROLL_UP_BUTTON_ID)?.remove();
    document.getElementById(SCROLL_DOWN_BUTTON_ID)?.remove();
  };
  const syncScrollButtons = () => {
    if (isGeminiCodeAssistDocument()) {
      removeFloatingButtons();
      updateGeminiNativeScrollButtons();
      return;
    }
    if (window[KEY]?.scrollButtonsEnabled) {
      installFloatingButtons();
    } else {
      removeFloatingButtons();
    }
  };
