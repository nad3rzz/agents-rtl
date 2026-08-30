  const positionCodexConversationRenameEditor = (editor, anchorElement) => {
    const anchorRect = anchorElement.getBoundingClientRect();
    const editorRect = editor.getBoundingClientRect();
    const maxLeft = window.innerWidth - editorRect.width - CODEX_CHAT_RENAME_EDITOR_VIEWPORT_MARGIN_PX;
    const left = Math.min(
      Math.max(CODEX_CHAT_RENAME_EDITOR_VIEWPORT_MARGIN_PX, anchorRect.left),
      Math.max(CODEX_CHAT_RENAME_EDITOR_VIEWPORT_MARGIN_PX, maxLeft)
    );
    const topBelow = anchorRect.bottom + CODEX_CHAT_RENAME_EDITOR_OFFSET_PX;
    const topAbove = anchorRect.top - editorRect.height - CODEX_CHAT_RENAME_EDITOR_OFFSET_PX;
    const maxTop = window.innerHeight - editorRect.height - CODEX_CHAT_RENAME_EDITOR_VIEWPORT_MARGIN_PX;
    const top = topBelow <= maxTop
      ? topBelow
      : Math.max(CODEX_CHAT_RENAME_EDITOR_VIEWPORT_MARGIN_PX, topAbove);
    editor.style.left = Math.round(left) + "px";
    editor.style.top = Math.round(top) + "px";
  };
  const openCodexConversationRenameEditor = (conversation, anchorElement) => {
    closeCodexConversationRenameEditor();
    const editor = document.createElement("form");
    editor.id = CODEX_CHAT_RENAME_EDITOR_ID;
    editor.dataset.agentsRtlSource = codexTransientSourceFromAnchor(anchorElement);
    const input = document.createElement("input");
    input.type = "text";
    input.value = conversation.title;
    input.setAttribute("aria-label", "Codex chat name");
    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.textContent = "\u2713";
    saveButton.title = "Save";
    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = "\u00D7";
    cancelButton.title = "Cancel";
    cancelButton.addEventListener("click", (event) => {
      event.preventDefault();
      closeCodexConversationRenameEditor();
    });
    let lastRenameSaveEventAtMs = 0;
    const submitCodexConversationRenameEditor = (event) => {
      event.preventDefault();
      event.stopPropagation();
      const now = performance.now();
      if (now - lastRenameSaveEventAtMs < 120) return;
      lastRenameSaveEventAtMs = now;
      saveCodexConversationRename(conversation, input.value, saveButton, closeCodexConversationRenameEditor);
    };
    saveButton.addEventListener("pointerdown", submitCodexConversationRenameEditor, { capture: true });
    saveButton.addEventListener("click", submitCodexConversationRenameEditor, { capture: true });
    editor.addEventListener("submit", submitCodexConversationRenameEditor);
    editor.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeCodexConversationRenameEditor();
    });
    editor.append(input, saveButton, cancelButton);
    codexConversationRenameEditorHost(anchorElement).append(editor);
    positionCodexConversationRenameEditor(editor, anchorElement);
    input.focus();
    input.select();
  };
