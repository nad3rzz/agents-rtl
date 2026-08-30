  const codexPendingApprovalConversationsFromReactQueryCache = () => {
    const conversations = codexConversationListFromReactQueryCache();
    if (!Array.isArray(conversations)) return null;
    const pendingConversationsById = new Map();
    conversations
      .filter((conversation) =>
        Array.isArray(conversation?.threadRuntimeStatus?.activeFlags) &&
        conversation.threadRuntimeStatus.activeFlags.includes(CODEX_WAITING_ON_APPROVAL_FLAG)
      )
      .forEach((conversation) => {
        const conversationId = compactText(conversation?.id);
        const title = compactText(conversation?.title);
        if (!conversationId || !title || pendingConversationsById.has(conversationId)) return;
        pendingConversationsById.set(conversationId, { id: conversationId, title });
      });
    return [...pendingConversationsById.values()];
  };
  const codexHasActiveTaskInReactQueryCache = () => {
    const conversations = codexConversationListFromReactQueryCache();
    if (!Array.isArray(conversations)) return false;
    return conversations.some((conversation) =>
      conversation?.threadRuntimeStatus?.type === "active" ||
      (Array.isArray(conversation?.requests) && conversation.requests.length > 0)
    );
  };
  const codexActiveTaskCountFromTaskHistoryButton = () => {
    const taskHistoryButton = [...document.querySelectorAll("button,[role='button']")]
      .find((element) => /tasks in progress|in progress/i.test(
        compactText(element.getAttribute("aria-label") || element.innerText || element.textContent || "")
      ));
    const taskHistoryText = compactText(
      taskHistoryButton?.getAttribute("aria-label") ||
      taskHistoryButton?.innerText ||
      taskHistoryButton?.textContent ||
      ""
    );
    const match = taskHistoryText.match(/(\d+)\s+tasks?\s+in\s+progress/i);
    return match ? Number(match[1]) : 0;
  };
  const codexTaskRows = () =>
    [...document.querySelectorAll("[role='button']")]
      .filter((element) => String(element.className || "").includes("h-token-nav-row"));
  const codexTasksListIsVisible = () => codexTaskRows().length > 0 && !findCodexBackButton();
  const extractCodexPendingApprovalTitleFromTaskRow = (row) => {
    const rowText = compactText(row?.innerText || row?.textContent || "");
    if (!rowText.includes(CODEX_AWAITING_APPROVAL_TEXT)) return "";
    return compactText(rowText.split(CODEX_AWAITING_APPROVAL_TEXT)[0]);
  };
  const codexApprovalPromptIsVisible = () =>
    [...document.querySelectorAll("[role='radiogroup']")].some((radioGroup) => {
      const promptCard = radioGroup.closest("[class*='rounded']") || radioGroup.parentElement;
      const promptText = compactText(promptCard?.innerText || promptCard?.textContent || "");
      return /\bYes\b/.test(promptText) && /\bSubmit\b/.test(promptText);
    });
