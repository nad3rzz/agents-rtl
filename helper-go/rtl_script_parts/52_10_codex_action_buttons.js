  const createCodexConversationRenameButton = (conversation) => {
    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.className = CODEX_CHAT_RENAME_BUTTON_CLASS_NAME;
    renameButton.textContent = "\u270E";
    renameButton.title = "Rename tab";
    renameButton.setAttribute("aria-label", "Rename Codex chat tab");
    renameButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openCodexConversationRenameEditor(conversation, renameButton);
    }, { capture: true });
    return renameButton;
  };
  const createCodexConversationPathButton = (conversation) => {
    const pathButton = document.createElement("button");
    pathButton.type = "button";
    pathButton.className = CODEX_CHAT_PATH_BUTTON_CLASS_NAME;
    pathButton.textContent = "📋";
    pathButton.title = "Copy conversation path";
    pathButton.setAttribute("aria-label", "Copy Codex conversation path");
    pathButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      const path = conversation.path;
      if (!path) {
        const originalText = pathButton.textContent;
        pathButton.textContent = "❌";
        setTimeout(() => { pathButton.textContent = originalText; }, 1200);
        return;
      }
      navigator.clipboard.writeText(path).catch(() => {});
      const originalText = pathButton.textContent;
      pathButton.textContent = "✔️";
      setTimeout(() => { pathButton.textContent = originalText; }, 1200);
    }, { capture: true });
    return pathButton;
  };
  const createCodexConversationArchiveButton = (conversation) => {
    const archiveButton = document.createElement("button");
    const archiveIsPending = pendingCodexArchiveConversationIdSet().has(conversation.id);
    archiveButton.type = "button";
    archiveButton.className = CODEX_CHAT_ARCHIVE_BUTTON_CLASS_NAME;
    archiveButton.textContent = archiveIsPending ? "\u2026" : "\u00D7";
    archiveButton.title = archiveIsPending ? "Archive pending" : "Archive tab";
    archiveButton.disabled = archiveIsPending;
    archiveButton.setAttribute("aria-label", "Archive Codex chat tab");
    archiveButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      if (archiveIsPending) return;
      cancelCodexFloatingConversationActionsHide();
      confirmCodexConversationArchive(conversation, archiveButton);
    }, { capture: true });
    return archiveButton;
  };
