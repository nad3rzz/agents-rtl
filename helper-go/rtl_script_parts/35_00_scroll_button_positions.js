  const updateEdgeButtonPositions = () => {
    const upButton = document.getElementById(SCROLL_UP_BUTTON_ID);
    const downButton = document.getElementById(SCROLL_DOWN_BUTTON_ID);
    if (!upButton || !downButton) return;
    const scrollButtonsAreActive = Boolean(window[KEY]?.scrollButtonsEnabled);
    [upButton, downButton].forEach((button) => {
      button.hidden = !scrollButtonsAreActive;
      setStyleValueIfChanged(button, "display", scrollButtonsAreActive ? "block" : "none");
    });
    if (!scrollButtonsAreActive) return;
    const scrollContainer =
      findNativeChatScrollContainer() ||
      (isAntigravityNativeDocument() ? findAntigravityScrollAnchor() : null) ||
      findScrollContainer();
    if (!scrollContainer?.getBoundingClientRect) return;
    const rect = scrollContainer.getBoundingClientRect();
    const antigravityInputRect = isAntigravityNativeDocument()
      ? getAntigravityInputBox()?.getBoundingClientRect()
      : null;
    const visibleBottom = antigravityInputRect
      ? Math.min(rect.bottom, antigravityInputRect.top - 8)
      : rect.bottom;
    const right = Math.max(6, window.innerWidth - rect.right + 8);
    upButton.style.setProperty("right", right + "px", "important");
    downButton.style.setProperty("right", right + "px", "important");
    upButton.style.setProperty("top", Math.max(44, rect.top + 8) + "px", "important");
    downButton.style.setProperty("top", Math.max(44, visibleBottom - 34) + "px", "important");
  };
  const updateGeminiNativeScrollButtons = () => {
    if (!isGeminiCodeAssistDocument()) return false;
    const scrollButtonsAreActive = Boolean(window[KEY]?.scrollButtonsEnabled);
    document.querySelectorAll(".scroll-to-previous,.scroll-to-next").forEach((button) => {
      button.hidden = !scrollButtonsAreActive;
      if (scrollButtonsAreActive) {
        button.style.removeProperty("display");
        button.style.removeProperty("visibility");
      } else {
        button.style.setProperty("display", "none", "important");
        button.style.setProperty("visibility", "hidden", "important");
      }
    });
    return true;
  };
