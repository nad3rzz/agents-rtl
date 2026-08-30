  const navigateToCodexConversation = (conversation) => {
    hideCodexFloatingConversationActions();
    clearCodexHeaderElementCache();
    rememberCodexRecentConversation(conversation.id, window[KEY]?.codexConversations || [conversation]);
    markCodexConversationActivitySeen(conversation);
    renderCodexChatTabs();
    window.dispatchEvent(new MessageEvent("message", {
      data: {
        type: "navigate-to-route",
        path: "/local/" + encodeURIComponent(conversation.id),
        state: {},
      },
      origin: window.location.origin,
      source: window,
    }));
    [80, 250, 700, 1400].forEach((delay) => setTimeout(renderCodexChatTabs, delay));
  };
  const navigateToCodexConversationList = () => {
    hideCodexFloatingConversationActions();
    closeCodexOverflowMenu();
    clearCodexHeaderElementCache();
    const backButton = findCodexBackButton();
    if (backButton) {
      backButton.click();
    } else {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          type: "navigate-to-route",
          path: "/local",
          state: {},
        },
        origin: window.location.origin,
        source: window,
      }));
    }
    [80, 250, 700, 1400].forEach((delay) => setTimeout(renderCodexChatTabs, delay));
  };
  const removeCodexChatTabs = () => {
    clearCodexHeaderElementCache();
    document.getElementById(CODEX_CHAT_TABS_BAR_ID)?.remove();
    document.getElementById(CODEX_CHAT_ACTIVE_ACTIONS_ID)?.remove();
    closeCodexConversationRenameEditorUnlessOpenedFromList();
    closeCodexConversationConfirmationUnlessOpenedFromList();
    closeCodexOverflowMenu();
  };
