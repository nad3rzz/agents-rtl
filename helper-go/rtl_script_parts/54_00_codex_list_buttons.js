  const createCodexConversationListPathButton = (conversation) => {
    const pathButton = document.createElement("button");
    pathButton.type = "button";
    pathButton.className = CODEX_CHAT_LIST_PATH_BUTTON_CLASS_NAME;
    pathButton.dataset.conversationId = conversation.id;
    pathButton.textContent = "📋";
    pathButton.title = "Copy conversation path";
    pathButton.setAttribute("aria-label", "Copy Codex conversation path");
    pathButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      copyCodexTextWithButtonFeedback(pathButton, conversation.path, "Codex conversation path");
    }, { capture: true });
    return pathButton;
  };
  const createCodexConversationListDoctorButton = (conversation) =>
    createCodexConversationDoctorButton(conversation, CODEX_CHAT_LIST_DOCTOR_BUTTON_CLASS_NAME);
  const createCodexConversationListRenameButton = (conversation) => {
    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.className = CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME;
    renameButton.dataset.conversationId = conversation.id;
    renameButton.dataset.agentsRtlBindingVersion = CODEX_CHAT_LIST_RENAME_BINDING_VERSION;
    renameButton.textContent = "\u270E";
    renameButton.title = "Rename conversation";
    renameButton.setAttribute("aria-label", "Rename Codex conversation");
    renameButton.addEventListener("pointerdown", handleCodexConversationListRenamePointerDown, { capture: true });
    renameButton.addEventListener("click", handleCodexConversationListRenameClick, { capture: true });
    renameButton.addEventListener("keydown", handleCodexConversationListRenameKeydown, { capture: true });
    return renameButton;
  };
