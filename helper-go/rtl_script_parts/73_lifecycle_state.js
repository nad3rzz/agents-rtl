  const initialRtlEnabled = storedBoolean(RTL_ENABLED_STORAGE_KEY, true);
  const initialScrollButtonsEnabled = storedBoolean(SCROLL_BUTTONS_ENABLED_STORAGE_KEY, true);
  const initialCodexResourceMonitorVisible = codexResourceMonitorIsSupported() &&
    storedBoolean(CODEX_RESOURCE_MONITOR_VISIBLE_STORAGE_KEY, true);
  const initialCodexResourceMonitorResetRequestId =
    localStorage.getItem(CODEX_RESOURCE_MONITOR_RESET_REQUEST_ID_STORAGE_KEY) || "";
  let applyAnimationFrameId = null;
  const cancelScheduledApply = () => {
    if (applyAnimationFrameId === null) return;
    cancelAnimationFrame(applyAnimationFrameId);
    applyAnimationFrameId = null;
  };
  const scheduleApply = () => {
    if (applyAnimationFrameId !== null) return;
    applyAnimationFrameId = requestAnimationFrame(() => {
      applyAnimationFrameId = null;
      apply();
    });
  };
  const observer = new MutationObserver(() => scheduleApply());
  let observerIsActive = false;
  const ensureObserver = () => {
    if (observerIsActive || !document.body) return;
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    observerIsActive = true;
    if (window[KEY]) window[KEY].applyMutationObserver = observer;
  };
  const disconnectApplyObserver = () => {
    cancelScheduledApply();
    observer.disconnect();
    observerIsActive = false;
    if (window[KEY]?.applyMutationObserver === observer) {
      window[KEY].applyMutationObserver = null;
    }
  };
  const start = () => {
    clearHorizontalScrollSoon();
    window[KEY].stopped = false;
    saveBoolean(RTL_ENABLED_STORAGE_KEY, true);
    document.documentElement.dataset.agentsRtlActive = "1";
    installStyle();
    installControlButtons();
    syncScrollButtons();
    ensureObserver();
    apply();
    updateControlButtons();
    clearHorizontalScrollSoon();
  };
  const stop = () => {
    clearHorizontalScrollSoon();
    window[KEY].stopped = true;
    saveBoolean(RTL_ENABLED_STORAGE_KEY, false);
    document.documentElement.dataset.agentsRtlActive = "0";
    document.querySelectorAll("[" + MANAGED_ATTRIBUTE_NAME + "]").forEach(restoreManagedElement);
    restoreComposerDirectionAttributes();
    document.querySelectorAll("[" + TABLE_WRAPPER_ATTRIBUTE_NAME + "],[" + MESSAGE_BUBBLE_ATTRIBUTE_NAME + "]").forEach((element) => {
      element.removeAttribute(TABLE_WRAPPER_ATTRIBUTE_NAME);
      element.removeAttribute(MESSAGE_BUBBLE_ATTRIBUTE_NAME);
    });
    document.querySelectorAll("[" + CODEX_RESPONSE_ANNOTATION_KIND_ATTRIBUTE_NAME + "]").forEach((element) => {
      element.removeAttribute(CODEX_RESPONSE_ANNOTATION_KIND_ATTRIBUTE_NAME);
    });
    installStyle();
    installControlButtons();
    syncScrollButtons();
    renderCodexChatTabs();
    ensureObserver();
    updateControlButtons();
    clearHorizontalScrollSoon();
  };
  const toggle = () => {
    clearHorizontalScrollSoon();
    if (window[KEY].stopped) {
      start();
      return;
    }
    stop();
    clearHorizontalScrollSoon();
  };
  const toggleScrollButtons = () => {
    window[KEY].scrollButtonsEnabled = !window[KEY].scrollButtonsEnabled;
    saveBoolean(SCROLL_BUTTONS_ENABLED_STORAGE_KEY, window[KEY].scrollButtonsEnabled);
    syncScrollButtons();
    updateControlButtons();
  };
