  const codexConversationForListRenameButton = (button) => {
    const conversationId = compactText(button?.dataset?.conversationId);
    const conversation = (window[KEY]?.codexConversations || []).find((candidate) => candidate.id === conversationId);
    if (!conversation) throw new Error("Codex conversation rename button is missing a matching conversation id: " + conversationId);
    return conversation;
  };
  const codexConversationListRenameButtonFromPointerEvent = (event) => {
    const targetElement = event.target instanceof Element ? event.target : event.target?.parentElement;
    if (
      targetElement?.closest?.("#" + CODEX_CHAT_RENAME_EDITOR_ID) ||
      targetElement?.closest?.("#" + CODEX_CHAT_CONFIRMATION_ID)
    ) {
      return null;
    }
    const directButton = targetElement?.closest?.("." + CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME);
    if (directButton) return directButton;
    if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) return null;
    return [...document.querySelectorAll("." + CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME)].find((button) => {
      const buttonRect = button.getBoundingClientRect();
      return (
        event.clientX >= buttonRect.left &&
        event.clientX <= buttonRect.right &&
        event.clientY >= buttonRect.top &&
        event.clientY <= buttonRect.bottom
      );
    }) || null;
  };
  const consumeCodexConversationListRenameEvent = (event) => {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
  };
  const handleCodexConversationListRenamePointerDown = (event) => {
    if (typeof event.button === "number" && event.button !== 0) return;
    const button = event.currentTarget;
    consumeCodexConversationListRenameEvent(event);
    button.dataset.agentsRtlRenamePending = "1";
  };
  const openCodexConversationListRenameEditorForButton = (button) => {
    if (!(button instanceof Element)) throw new Error("Codex list rename requires a button element");
    delete button.dataset.agentsRtlRenamePending;
    openCodexConversationRenameEditor(codexConversationForListRenameButton(button), button);
  };
  const handleCodexConversationListRenameDocumentEvent = (event) => {
    if (typeof event.button === "number" && event.button !== 0) return;
    const button = codexConversationListRenameButtonFromPointerEvent(event);
    if (!button) return;
    consumeCodexConversationListRenameEvent(event);
    if (event.type !== "click") {
      button.dataset.agentsRtlRenamePending = "1";
      return;
    }
    openCodexConversationListRenameEditorForButton(button);
  };
  const removeCodexConversationListRenameListeners = () => {
    const state = window[KEY];
    if (!state?.codexConversationListRenameDocumentListener) return;
    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((eventName) => {
      document.removeEventListener(eventName, state.codexConversationListRenameDocumentListener, true);
    });
    state.codexConversationListRenameDocumentListener = null;
  };
  const installCodexConversationListRenameListeners = () => {
    removeCodexConversationListRenameListeners();
    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((eventName) => {
      document.addEventListener(eventName, handleCodexConversationListRenameDocumentEvent, true);
    });
    if (window[KEY]) {
      window[KEY].codexConversationListRenameDocumentListener = handleCodexConversationListRenameDocumentEvent;
    }
  };
  const handleCodexConversationListRenameClick = (event) => {
    if (typeof event.button === "number" && event.button !== 0) return;
    const button = event.currentTarget;
    consumeCodexConversationListRenameEvent(event);
    openCodexConversationListRenameEditorForButton(button);
  };
  const handleCodexConversationListRenameKeydown = (event) => {
    if (!CODEX_CHAT_LIST_RENAME_KEYBOARD_KEYS.has(event.key)) return;
    const button = event.currentTarget;
    consumeCodexConversationListRenameEvent(event);
    openCodexConversationListRenameEditorForButton(button);
  };
