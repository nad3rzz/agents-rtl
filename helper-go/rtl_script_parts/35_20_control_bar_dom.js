  const removeControlButtons = () => {
    stopContinuousScroll();
    document.getElementById(CONTROL_HOST_ID)?.remove();
    document.getElementById(GEMINI_CONTROL_SLOT_ID)?.remove();
    document.getElementById(CONTROL_BAR_ID)?.remove();
    document.getElementById(BUTTON_CLUSTER_ID)?.remove();
    removeCodexChatTabs();
  };
  const createControlBar = () => {
    const controlBar = document.createElement("span");
    controlBar.id = CONTROL_BAR_ID;
    const rtlButton = document.createElement("button");
    rtlButton.id = RTL_BUTTON_ID;
    rtlButton.type = "button";
    createControlToggleContent(rtlButton, "RTL");
    rtlButton.setAttribute("aria-label", "Toggle Agents RTL");
    rtlButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      window[KEY]?.toggle?.();
    });
    const scrollButtonsToggle = document.createElement("button");
    scrollButtonsToggle.id = SCROLL_BUTTONS_TOGGLE_ID;
    scrollButtonsToggle.type = "button";
    createControlToggleContent(scrollButtonsToggle, "\u25B2\u25BC");
    scrollButtonsToggle.setAttribute("aria-label", "Show or hide Agents RTL scroll arrows");
    scrollButtonsToggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      window[KEY]?.toggleScrollButtons?.();
    });
    controlBar.append(rtlButton, scrollButtonsToggle);
    if (codexResourceMonitorIsSupported()) {
      controlBar.append(createCodexResourceMonitorControl());
    }
    return controlBar;
  };
