  const renderCodexChatTabs = () => {
    if (isWorkbenchDocument()) {
      removeCodexChatTabs();
      return;
    }
    const conversations = updateCodexConversations();
    if (conversations.length === 0) {
      removeCodexChatTabs();
      return;
    }
    applyCodexConversationListRenameControls(conversations);
    const pendingApprovalTitles = updateCodexPendingApprovalTitles();
    updateCodexPendingApprovalRefreshTimer();
    const pendingApprovalTitleSet = new Set(pendingApprovalTitles.map(compactText));
    const headerHost = findCodexChatTabsHeaderHost();
    const titleElement = findCodexCurrentTitleElement();
    if (!headerHost) {
      removeCodexChatTabs();
      return;
    }
    let tabsBar = document.getElementById(CODEX_CHAT_TABS_BAR_ID);
    if (!tabsBar) {
      tabsBar = document.createElement("span");
      tabsBar.id = CODEX_CHAT_TABS_BAR_ID;
    }
    if (titleElement?.parentElement === headerHost) {
      if (titleElement.nextSibling !== tabsBar) titleElement.after(tabsBar);
    } else if (tabsBar.parentElement !== headerHost) {
      headerHost.append(tabsBar);
    }
    const orderedConversations = orderCodexConversations(conversations);
    const activeConversationId = findActiveCodexConversationId(orderedConversations);
    if (activeConversationId) rememberCodexRecentConversation(activeConversationId, orderedConversations);
    const unreadConversationIds = updateCodexUnreadConversationIds(orderedConversations, activeConversationId);
    const { visibleConversations, overflowConversations } = splitVisibleCodexConversations(orderedConversations, activeConversationId);
    const pendingArchiveConversationIds = pendingCodexArchiveConversationIdSet();
    const renderKey = orderedConversations
      .map((conversation) =>
        conversation.id + ":" +
        conversation.title + ":" +
        (conversation.id === activeConversationId ? "1" : "0") + ":" +
        (codexConversationNeedsApproval(conversation, pendingApprovalTitleSet) ? "A" : "0") + ":" +
        (unreadConversationIds.has(conversation.id) ? "U" : "0") + ":" +
        (pendingArchiveConversationIds.has(conversation.id) ? "P" : "0")
      )
      .join("|");
    if (tabsBar.dataset.renderKey === renderKey) return;
    tabsBar.dataset.renderKey = renderKey;
    closeCodexOverflowMenu();
    hideCodexFloatingConversationActions();
    tabsBar.textContent = "";
    visibleConversations.forEach((conversation) => {
      const tabItem = document.createElement("span");
      tabItem.className = CODEX_CHAT_TAB_ITEM_CLASS_NAME;
      bindCodexTabFloatingConversationActions(tabItem, conversation);
      const button = document.createElement("button");
      const displayTitle = conversation.title;
      button.type = "button";
      button.dataset.conversationId = conversation.id;
      button.dataset.active = conversation.id === activeConversationId ? "1" : "0";
      button.title = displayTitle;
      button.textContent = displayTitle;
      setCodexButtonPendingApproval(button, codexConversationNeedsApproval(conversation, pendingApprovalTitleSet));
      setCodexButtonUnread(button, unreadConversationIds.has(conversation.id));
      setCodexButtonPendingArchive(button, pendingArchiveConversationIds.has(conversation.id));
      button.setAttribute("aria-current", conversation.id === activeConversationId ? "page" : "false");
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        navigateToCodexConversation(conversation);
      }, { capture: true });
      tabItem.append(button);
      tabsBar.append(tabItem);
    });
    if (overflowConversations.length > 0) {
      const overflowButton = document.createElement("button");
      overflowButton.type = "button";
      overflowButton.className = CODEX_CHAT_OVERFLOW_BUTTON_CLASS_NAME;
      overflowButton.textContent = "+" + overflowConversations.length;
      overflowButton.title = "More Codex chats";
      setCodexButtonPendingApproval(
        overflowButton,
        overflowConversations.some((conversation) => codexConversationNeedsApproval(conversation, pendingApprovalTitleSet))
      );
      setCodexButtonUnread(
        overflowButton,
        overflowConversations.some((conversation) => unreadConversationIds.has(conversation.id))
      );
      setCodexButtonPendingArchive(
        overflowButton,
        overflowConversations.some((conversation) => pendingArchiveConversationIds.has(conversation.id))
      );
      overflowButton.setAttribute("aria-haspopup", "menu");
      overflowButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (document.getElementById(CODEX_CHAT_OVERFLOW_MENU_ID)) {
          closeCodexOverflowMenu();
          return;
        }
        hideCodexFloatingConversationActions();
        openCodexOverflowMenu(overflowButton, overflowConversations, orderedConversations, unreadConversationIds);
      }, { capture: true });
      tabsBar.append(overflowButton);
    }
  };
