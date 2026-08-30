  const codexConversationNeedsApproval = (conversation, pendingApprovalTitleSet) =>
    new Set(window[KEY]?.codexPendingApprovalConversationIds || []).has(compactText(conversation?.id)) ||
    pendingApprovalTitleSet.has(compactText(conversation?.title));
  const setCodexButtonPendingApproval = (button, pendingApproval) => {
    setAttributeIfChanged(button, "data-agents-rtl-pending-approval", pendingApproval ? "1" : "0");
    const existingBadge = button.querySelector(":scope > ." + CODEX_CHAT_APPROVAL_BADGE_CLASS_NAME);
    if (!pendingApproval) {
      existingBadge?.remove();
      return;
    }
    if (existingBadge) return;
    const badge = document.createElement("span");
    badge.className = CODEX_CHAT_APPROVAL_BADGE_CLASS_NAME;
    badge.textContent = "!";
    badge.title = CODEX_AWAITING_APPROVAL_TEXT;
    button.append(badge);
  };
  const setCodexButtonUnread = (button, unread) => {
    setAttributeIfChanged(button, "data-agents-rtl-unread", unread ? "1" : "0");
    const existingBadge = button.querySelector(":scope > ." + CODEX_CHAT_UNREAD_BADGE_CLASS_NAME);
    if (!unread) {
      existingBadge?.remove();
      return;
    }
    if (existingBadge) return;
    const badge = document.createElement("span");
    badge.className = CODEX_CHAT_UNREAD_BADGE_CLASS_NAME;
    badge.textContent = "\u25CF";
    badge.title = "New agent reply";
    button.append(badge);
  };
  const setCodexButtonPendingArchive = (button, pendingArchive) => {
    setAttributeIfChanged(button, "data-agents-rtl-pending-archive", pendingArchive ? "1" : "0");
    if (!pendingArchive || button.title.includes("Archive pending")) return;
    setAttributeIfChanged(button, "title", (button.title ? button.title + " - " : "") + "Archive pending");
  };
