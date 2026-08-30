  const cancelCodexFloatingConversationActionsHide = () => {
    const state = window[KEY];
    if (!state?.codexFloatingActionsHideTimer) return;
    clearTimeout(state.codexFloatingActionsHideTimer);
    state.codexFloatingActionsHideTimer = null;
  };
  const hideCodexFloatingConversationActions = () => {
    cancelCodexFloatingConversationActionsHide();
    const actionsBar = document.getElementById(CODEX_CHAT_ACTIVE_ACTIONS_ID);
    if (!actionsBar) return;
    actionsBar.dataset.visible = "0";
    actionsBar.style.setProperty("left", "-9999px", "important");
    actionsBar.style.setProperty("top", "-9999px", "important");
  };
  const scheduleCodexFloatingConversationActionsHide = () => {
    cancelCodexFloatingConversationActionsHide();
    if (window[KEY]) {
      window[KEY].codexFloatingActionsHideTimer = setTimeout(hideCodexFloatingConversationActions, 180);
    }
  };
  const ensureCodexFloatingConversationActionsBar = () => {
    let actionsBar = document.getElementById(CODEX_CHAT_ACTIVE_ACTIONS_ID);
    if (actionsBar) return actionsBar;
    actionsBar = document.createElement("span");
    actionsBar.id = CODEX_CHAT_ACTIVE_ACTIONS_ID;
    actionsBar.addEventListener("pointerenter", cancelCodexFloatingConversationActionsHide);
    actionsBar.addEventListener("pointerleave", scheduleCodexFloatingConversationActionsHide);
    actionsBar.addEventListener("focusin", cancelCodexFloatingConversationActionsHide);
    actionsBar.addEventListener("focusout", scheduleCodexFloatingConversationActionsHide);
    document.body.append(actionsBar);
    return actionsBar;
  };
  const positionCodexFloatingConversationActions = (actionsBar, anchorElement) => {
    const anchorRect = anchorElement.getBoundingClientRect();
    actionsBar.dataset.visible = "1";
    actionsBar.style.visibility = "hidden";
    actionsBar.style.setProperty("left", "0px", "important");
    actionsBar.style.setProperty("top", "0px", "important");
    const actionsRect = actionsBar.getBoundingClientRect();
    const viewportMargin = 4;
    const left = Math.min(
      Math.max(viewportMargin, anchorRect.left),
      Math.max(viewportMargin, window.innerWidth - actionsRect.width - viewportMargin)
    );
    const top = Math.min(
      Math.max(viewportMargin, anchorRect.bottom + 3),
      Math.max(viewportMargin, window.innerHeight - actionsRect.height - viewportMargin)
    );
    actionsBar.style.setProperty("left", Math.round(left) + "px", "important");
    actionsBar.style.setProperty("top", Math.round(top) + "px", "important");
    actionsBar.style.visibility = "";
  };
  const showCodexFloatingConversationActions = (conversation, anchorElement) => {
    cancelCodexFloatingConversationActionsHide();
    const actionsBar = ensureCodexFloatingConversationActionsBar();
    const displayTitle = conversation.title;
    const renderKey = conversation.id + ":" + conversation.title + ":" + displayTitle;
    if (actionsBar.dataset.renderKey !== renderKey) {
      actionsBar.textContent = "";
      actionsBar.dataset.renderKey = renderKey;
      actionsBar.dataset.conversationId = conversation.id;
      actionsBar.title = displayTitle === conversation.title ? displayTitle : displayTitle + " (" + conversation.title + ")";
      actionsBar.append(
        createCodexConversationPathButton(conversation),
        createCodexConversationRenameButton(conversation),
        createCodexConversationArchiveButton(conversation)
      );
    }
    positionCodexFloatingConversationActions(actionsBar, anchorElement);
  };
  const bindCodexTabFloatingConversationActions = (tabItem, conversation) => {
    tabItem.addEventListener("pointerenter", () => showCodexFloatingConversationActions(conversation, tabItem));
    tabItem.addEventListener("pointerleave", scheduleCodexFloatingConversationActionsHide);
    tabItem.addEventListener("focusin", () => showCodexFloatingConversationActions(conversation, tabItem));
    tabItem.addEventListener("focusout", scheduleCodexFloatingConversationActionsHide);
  };
