  const findNativeChatScrollContainer = () => {
    const nativeChatPanel = getNativeChatPanel();
    if (!nativeChatPanel) return null;
    const nativeChatList = nativeChatPanel.querySelector(NATIVE_CHAT_LIST_SELECTOR);
    const nativeChatListScrollContainer = [...(nativeChatList?.children || [])]
      .find((element) => element.classList?.contains("monaco-scrollable-element"));
    if (nativeChatListScrollContainer) return nativeChatListScrollContainer;
    const inputPartRect = nativeChatPanel.querySelector(".interactive-input-part")?.getBoundingClientRect();
    return [...nativeChatPanel.querySelectorAll(".monaco-scrollable-element")]
      .filter((element) => !element.classList.contains("editor-scrollable"))
      .filter((element) => !element.closest(".chat-confirmation-widget-container,.chat-tool-invocation-part,.chat-used-context,.chat-thinking-box,.interactive-input-part"))
      .filter((element) => {
        const hasScrollableContent = element.scrollHeight > element.clientHeight + SCROLL_HEIGHT_TOLERANCE_PX;
        const containsSessionsPane = (element.innerText || "").includes("SESSIONS");
        if (!hasScrollableContent || containsSessionsPane) return false;
        if (!inputPartRect) return true;
        const rect = element.getBoundingClientRect();
        return rect.right > inputPartRect.left && rect.left < inputPartRect.right;
      })
      .sort((leftElement, rightElement) =>
        (rightElement.scrollHeight - rightElement.clientHeight) - (leftElement.scrollHeight - leftElement.clientHeight)
      )[0] || null;
  };
