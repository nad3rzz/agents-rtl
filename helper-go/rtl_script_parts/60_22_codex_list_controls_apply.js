  const applyCodexConversationListRenameControls = (conversations = window[KEY]?.codexConversations || []) => {
    if (isWorkbenchDocument()) return;
    const conversationsById = new Map(conversations.map((conversation) => [conversation.id, conversation]));
    codexConversationListRows().forEach((row) => {
      const conversationId = codexConversationIdFromListRow(row);
      if (!conversationId) return;
      const conversation = conversationsById.get(conversationId);
      if (!conversation) {
        removeCodexConversationListRowRenameControl(row);
        return;
      }
      row.setAttribute(CODEX_CHAT_LIST_RENAME_ROW_ATTRIBUTE_NAME, conversation.id);
      row.setAttribute(CODEX_CHAT_LIST_RENAME_ROW_LOCATION_ATTRIBUTE_NAME, codexConversationListRowLocation(row));
      const actionHost = findCodexConversationListRowActionHost(row);
      if (!actionHost) {
        removeCodexConversationListRowRenameControl(row);
        return;
      }
      const existingButton = row.querySelector("." + CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME);
      const existingPathButton = row.querySelector("." + CODEX_CHAT_LIST_PATH_BUTTON_CLASS_NAME);
      const existingRenameButtonHasCurrentBinding =
        existingButton?.dataset.conversationId === conversation.id &&
        existingButton.dataset.agentsRtlBindingVersion === CODEX_CHAT_LIST_RENAME_BINDING_VERSION &&
        existingButton.parentElement === actionHost;
      if (existingRenameButtonHasCurrentBinding && existingPathButton) return;
      existingButton?.remove();
      existingPathButton?.remove();
      const renameButton = createCodexConversationListRenameButton(conversation);
      const pathButton = createCodexConversationListPathButton(conversation);
      actionHost.insertBefore(renameButton, findCodexConversationListRowArchiveButton(row));
      actionHost.insertBefore(pathButton, renameButton);
    });
    syncCodexConversationListOverlayState();
  };
  const removeCodexConversationListRenameControls = () => {
    document.querySelectorAll("." + CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME).forEach((button) => button.remove());
    document.querySelectorAll("." + CODEX_CHAT_LIST_PATH_BUTTON_CLASS_NAME).forEach((button) => button.remove());
    document.querySelectorAll("[" + CODEX_CHAT_LIST_RENAME_ROW_ATTRIBUTE_NAME + "]").forEach(removeCodexConversationListRowRenameControl);
    delete document.documentElement.dataset.agentsRtlCodexViewAllOpen;
  };
