  const updateControlButtons = () => {
    const rtlButton = document.getElementById(RTL_BUTTON_ID);
    const scrollButtonsToggle = document.getElementById(SCROLL_BUTTONS_TOGGLE_ID);
    const resourceMonitorToggle = document.getElementById(CODEX_RESOURCE_MONITOR_TOGGLE_ID);
    const rtlIsActive = !window[KEY]?.stopped;
    const scrollButtonsAreActive = Boolean(window[KEY]?.scrollButtonsEnabled);
    setControlToggleState(rtlButton, rtlIsActive, rtlIsActive ? "Disable Agents RTL" : "Enable Agents RTL");
    setControlToggleState(
      scrollButtonsToggle,
      scrollButtonsAreActive,
      scrollButtonsAreActive ? "Hide scroll arrows" : "Show scroll arrows"
    );
    const resourceMonitorIsVisible = Boolean(window[KEY]?.codexResourceMonitorVisible);
    setControlToggleState(
      resourceMonitorToggle,
      resourceMonitorIsVisible,
      resourceMonitorIsVisible ? "Hide Codex resource monitor" : "Show Codex resource monitor"
    );
    updateCodexResourceMonitor();
    if (!updateGeminiNativeScrollButtons()) updateEdgeButtonPositions();
  };
