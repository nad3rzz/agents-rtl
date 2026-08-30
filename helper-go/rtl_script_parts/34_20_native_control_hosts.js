  const findNativeControlHost = () => {
    const nativeChatPanel = getNativeChatPanel();
    if (!nativeChatPanel) return null;
    const host =
      nativeChatPanel.querySelector(".chat-input-toolbar .monaco-action-bar ul.actions-container") ||
      nativeChatPanel.querySelector(".chat-input-toolbar .monaco-action-bar") ||
      nativeChatPanel.querySelector(".chat-input-toolbars");
    if (!host) return null;
    return { host, wrapInActionItem: host.tagName === "UL", context: "native" };
  };
  const findAntigravityToolbarRow = () => {
    const inputBox = [...document.querySelectorAll("[id='" + ANTIGRAVITY_INPUT_BOX_ID + "']")]
      .filter(isVisibleViewportElement)
      .sort((leftElement, rightElement) => rightElement.getBoundingClientRect().bottom - leftElement.getBoundingClientRect().bottom)[0] ||
      getAntigravityInputBox();
    if (!isVisibleViewportElement(inputBox)) return null;
    const inputBoxRect = inputBox.getBoundingClientRect();
    return [...inputBox.querySelectorAll("div")]
      .filter(isVisibleViewportElement)
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return rect.top >= inputBoxRect.top &&
          rect.bottom <= inputBoxRect.bottom + 1 &&
          style.display === "flex" &&
          style.flexDirection === "row" &&
          rect.height >= 24 &&
          rect.height <= 40 &&
          (
            element.querySelector("[aria-label='Add context']") ||
            element.textContent.includes("Gemini") ||
            element.textContent.includes("Send")
          );
      })
      .sort((leftElement, rightElement) => rightElement.getBoundingClientRect().width - leftElement.getBoundingClientRect().width)[0] || null;
  };
  const findAntigravityControlHost = () => {
    const toolbarRow = findAntigravityToolbarRow();
    const host = toolbarRow?.firstElementChild instanceof Element ? toolbarRow.firstElementChild : toolbarRow;
    if (!host) return null;
    setStyleValueIfChanged(host, "display", "flex");
    setStyleValueIfChanged(host, "alignItems", "center");
    setStyleValueIfChanged(host, "gap", "5px");
    setStyleValueIfChanged(host, "overflow", "visible");
    return { host, wrapInActionItem: false, context: "antigravity" };
  };
  const findControlHost = () => {
    if (!isWorkbenchDocument()) return findGeminiControlHost() || findWebviewControlHost();
    return findNativeControlHost() || findAntigravityControlHost();
  };
