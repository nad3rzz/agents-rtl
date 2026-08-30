  const requestCodexConversationArchive = (conversation) => {
    const conversationsBeforeArchive = window[KEY]?.codexConversations || updateCodexConversations();
    const activeConversationId = findActiveCodexConversationId(conversationsBeforeArchive);
    const archivedConversationWasActive = activeConversationId === conversation.id;
    saveCodexArchiveRequest(conversation);
    closeCodexOverflowMenu();
    hideCodexFloatingConversationActions();
    if (archivedConversationWasActive) {
      const nextConversation = orderCodexConversations(window[KEY]?.codexConversations || [])
        .find((candidate) => candidate.id !== conversation.id);
      if (nextConversation) {
        navigateToCodexConversation(nextConversation);
      } else {
        navigateToCodexConversationList();
      }
      return;
    }
    renderCodexChatTabs();
  };
  const confirmCodexConversationArchive = (conversation, anchorElement) => {
    openCodexConversationConfirmation({
      anchorElement,
      title: "Archive Codex chat?",
      detail: "Chat: " + conversation.title,
      confirmLabel: "Archive",
      onConfirm: () => requestCodexConversationArchive(conversation),
    });
  };
