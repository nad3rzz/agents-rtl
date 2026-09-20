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
      const existingDoctorButton = row.querySelector("." + CODEX_CHAT_LIST_DOCTOR_BUTTON_CLASS_NAME);
      const existingRenameButtonHasCurrentBinding =
        existingButton?.dataset.conversationId === conversation.id &&
        existingButton.dataset.agentsRtlBindingVersion === CODEX_CHAT_LIST_RENAME_BINDING_VERSION &&
        existingButton.parentElement === actionHost;
      const existingPathButtonHasCurrentBinding =
        existingPathButton?.dataset.conversationId === conversation.id &&
        existingPathButton.parentElement === actionHost;
      const existingDoctorButtonHasCurrentBinding =
        existingDoctorButton?.dataset.conversationId === conversation.id &&
        existingDoctorButton.parentElement === actionHost;
      const doctorButtonStateIsCurrent = personalSessionDoctorIsEnabled()
        ? existingDoctorButtonHasCurrentBinding
        : !existingDoctorButton;
      if (existingRenameButtonHasCurrentBinding && existingPathButtonHasCurrentBinding && doctorButtonStateIsCurrent) return;
      existingButton?.remove();
      existingPathButton?.remove();
      existingDoctorButton?.remove();
      const renameButton = createCodexConversationListRenameButton(conversation);
      const pathButton = createCodexConversationListPathButton(conversation);
      const archiveButton = findCodexConversationListRowArchiveButton(row);
      actionHost.insertBefore(pathButton, archiveButton);
      actionHost.insertBefore(renameButton, archiveButton);
      if (personalSessionDoctorIsEnabled()) {
        actionHost.insertBefore(createCodexConversationListDoctorButton(conversation), archiveButton);
      }
    });
    syncCodexConversationListOverlayState();
  };
  const removeCodexConversationListRenameControls = () => {
    document.querySelectorAll("." + CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME).forEach((button) => button.remove());
    document.querySelectorAll("." + CODEX_CHAT_LIST_PATH_BUTTON_CLASS_NAME).forEach((button) => button.remove());
    document.querySelectorAll("." + CODEX_CHAT_LIST_DOCTOR_BUTTON_CLASS_NAME).forEach((button) => button.remove());
    document.querySelectorAll("[" + CODEX_CHAT_LIST_RENAME_ROW_ATTRIBUTE_NAME + "]").forEach(removeCodexConversationListRowRenameControl);
    delete document.documentElement.dataset.agentsRtlCodexViewAllOpen;
  };
