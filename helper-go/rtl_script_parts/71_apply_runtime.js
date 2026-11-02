  const apply = () => {
    installGeminiHistoryTrim();
    if (!window[KEY]?.stopped) {
      if (isGeminiCodeAssistDocument()) {
        applyGeminiTextDirection();
        applyGeminiComposerDirection();
      } else {
        const webviewChatScope =
          document.querySelector('[class*="react-scroll-to-bottom"]') ||
          document.querySelector(".thread-scroll-container");
        if (webviewChatScope) {
          applyChatTableDirection(webviewChatScope);
          [...webviewChatScope.querySelectorAll(WEBVIEW_CHAT_TEXT_SELECTOR)].forEach(applyTextDirection);
        } else if (!getNativeChatPanel() && !isWorkbenchDocument()) {
          applyChatTableDirection(document.body);
          [...document.body.querySelectorAll(WEBVIEW_CHAT_TEXT_SELECTOR)].forEach(applyTextDirection);
        }
        [...document.body.querySelectorAll(PERMISSION_PROMPT_TEXT_SELECTOR)].forEach(applyTextDirection);
        applyCodexResponseAnnotationTextDirection();
        applyCodexAddToChatButtonHighlight();
      }
      const nativeChatPanel = getNativeChatPanel();
      if (nativeChatPanel) {
        applyChatTableDirection(nativeChatPanel);
        [...nativeChatPanel.querySelectorAll(NATIVE_CHAT_TEXT_SELECTOR)].forEach(applyTextDirection);
        applyNativeVscodeComposerDirection();
      }
      if (isAntigravityNativeDocument()) {
        applyAntigravityNativeTextDirection();
      }
      applyCodexWebviewComposerDirection();
    }
    renderCodexChatTabs();
    installControlButtons();
    syncScrollButtons();
  };
