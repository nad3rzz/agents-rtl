  const closeCodexConversationRenameEditor = () => {
    document.getElementById(CODEX_CHAT_RENAME_EDITOR_ID)?.remove();
  };
  const closeCodexConversationRenameEditorUnlessOpenedFromList = () => {
    const editor = document.getElementById(CODEX_CHAT_RENAME_EDITOR_ID);
    if (!editor || codexTransientElementWasOpenedFromList(editor)) return;
    editor.remove();
  };
  const codexConversationRenameEditorHost = () => document.body;
  const applyCodexConversationRename = async (conversation, compactNextTitle) => {
    await renameCodexConversationNatively(conversation, compactNextTitle);
    updateCodexConversations();
    renderCodexChatTabs();
    applyCodexConversationListRenameControls(window[KEY]?.codexConversations || updateCodexConversations());
  };
  const saveCodexConversationRename = (conversation, nextTitle, anchorElement, onSaved) => {
    const compactNextTitle = compactText(nextTitle);
    const nextDisplayTitle = !compactNextTitle || compactNextTitle === conversation.title
      ? conversation.title
      : compactNextTitle;
    if (nextDisplayTitle === conversation.title) {
      onSaved?.();
      return;
    }
    openCodexConversationConfirmation({
      anchorElement,
      title: "Rename Codex chat?",
      detail: "From: " + conversation.title + "\nTo: " + nextDisplayTitle,
      confirmLabel: "Rename",
      closeOnConfirmStart: true,
      onConfirm: async () => {
        onSaved?.();
        await applyCodexConversationRename(conversation, nextDisplayTitle);
      },
    });
  };
