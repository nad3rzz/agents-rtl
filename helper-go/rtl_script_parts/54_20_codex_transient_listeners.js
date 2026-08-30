  const eventTargetIsCodexTransientControl = (event) => {
    const targetElement = event.target instanceof Element ? event.target : event.target?.parentElement;
    if (!targetElement) return false;
    return Boolean(
      targetElement.closest("#" + CODEX_CHAT_RENAME_EDITOR_ID) ||
      targetElement.closest("#" + CODEX_CHAT_CONFIRMATION_ID) ||
      targetElement.closest("." + CODEX_CHAT_RENAME_BUTTON_CLASS_NAME) ||
      targetElement.closest("." + CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME) ||
      targetElement.closest("." + CODEX_CHAT_ARCHIVE_BUTTON_CLASS_NAME) ||
      codexConversationListRenameButtonFromPointerEvent(event)
    );
  };
  const handleCodexTransientPointerDown = (event) => {
    if (eventTargetIsCodexTransientControl(event)) return;
    closeCodexConversationRenameEditor();
    closeCodexConversationConfirmation();
  };
  const handleCodexTransientKeydown = (event) => {
    if (event.key !== "Escape") return;
    closeCodexConversationRenameEditor();
    closeCodexConversationConfirmation();
  };
  const removeCodexTransientListeners = () => {
    const state = window[KEY];
    if (!state) return;
    if (state.codexTransientPointerdownListener) {
      document.removeEventListener("pointerdown", state.codexTransientPointerdownListener, true);
    }
    if (state.codexTransientKeydownListener) {
      document.removeEventListener("keydown", state.codexTransientKeydownListener, true);
    }
    state.codexTransientPointerdownListener = null;
    state.codexTransientKeydownListener = null;
  };
  const installCodexTransientListeners = () => {
    removeCodexTransientListeners();
    document.addEventListener("pointerdown", handleCodexTransientPointerDown, true);
    document.addEventListener("keydown", handleCodexTransientKeydown, true);
    if (window[KEY]) {
      window[KEY].codexTransientPointerdownListener = handleCodexTransientPointerDown;
      window[KEY].codexTransientKeydownListener = handleCodexTransientKeydown;
    }
  };
