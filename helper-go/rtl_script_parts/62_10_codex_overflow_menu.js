  const closeCodexOverflowMenu = () => {
    document.getElementById(CODEX_CHAT_OVERFLOW_MENU_ID)?.remove();
  };
  const eventPointIsInsideElement = (event, element) => {
    if (typeof event?.clientX !== "number" || typeof event?.clientY !== "number") return false;
    const rect = element.getBoundingClientRect();
    return event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom;
  };
  const positionCodexOverflowMenu = (menuElement, anchorElement) => {
    const anchorRect = anchorElement.getBoundingClientRect();
    const menuWidth = menuElement.getBoundingClientRect().width || 180;
    const left = Math.min(Math.max(8, anchorRect.left), Math.max(8, window.innerWidth - menuWidth - 8));
    const top = Math.min(anchorRect.bottom + 5, Math.max(8, window.innerHeight - menuElement.getBoundingClientRect().height - 8));
    menuElement.style.left = Math.round(left) + "px";
    menuElement.style.top = Math.round(top) + "px";
  };
  const openCodexOverflowMenu = (anchorElement, overflowConversations, orderedConversations, unreadConversationIds) => {
    closeCodexOverflowMenu();
    const menuElement = document.createElement("div");
    menuElement.id = CODEX_CHAT_OVERFLOW_MENU_ID;
    const latestPendingApprovalTitles = updateCodexPendingApprovalTitles();
    updateCodexPendingApprovalRefreshTimer();
    const pendingApprovalTitleSet = new Set(latestPendingApprovalTitles.map(compactText));
    const pendingArchiveConversationIds = pendingCodexArchiveConversationIdSet();
    const sortedOverflowConversations = [...overflowConversations].sort((leftConversation, rightConversation) =>
      Number(codexConversationNeedsApproval(rightConversation, pendingApprovalTitleSet)) -
        Number(codexConversationNeedsApproval(leftConversation, pendingApprovalTitleSet)) ||
      Number(unreadConversationIds.has(rightConversation.id)) -
        Number(unreadConversationIds.has(leftConversation.id))
    );
    sortedOverflowConversations.forEach((conversation) => {
      const itemRow = document.createElement("div");
      itemRow.className = CODEX_CHAT_OVERFLOW_ITEM_CLASS_NAME;
      const itemButton = document.createElement("button");
      const displayTitle = conversation.title;
      itemButton.type = "button";
      itemButton.title = displayTitle === conversation.title ? displayTitle : displayTitle + " (" + conversation.title + ")";
      itemButton.textContent = displayTitle;
      setCodexButtonPendingApproval(itemButton, codexConversationNeedsApproval(conversation, pendingApprovalTitleSet));
      setCodexButtonUnread(itemButton, unreadConversationIds.has(conversation.id));
      setCodexButtonPendingArchive(itemButton, pendingArchiveConversationIds.has(conversation.id));
      itemButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const selectedConversation = orderedConversations.find((candidate) => candidate.id === conversation.id);
        closeCodexOverflowMenu();
        hideCodexFloatingConversationActions();
        if (selectedConversation) navigateToCodexConversation(selectedConversation);
      });
      itemRow.append(itemButton, createCodexConversationPathButton(conversation), createCodexConversationRenameButton(conversation), createCodexConversationArchiveButton(conversation));
      menuElement.append(itemRow);
    });
    document.body.append(menuElement);
    positionCodexOverflowMenu(menuElement, anchorElement);
  };
