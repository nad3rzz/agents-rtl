  const findCodexConversationListRowArchiveButton = (row) =>
    row.querySelector("button[aria-label='Archive chat']");
  const findCodexConversationListRowActionHost = (row) =>
    findCodexConversationListRowArchiveButton(row)?.parentElement || null;
  const removeCodexConversationListRowRenameControl = (row) => {
    row.querySelectorAll("." + CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME).forEach((button) => button.remove());
    row.removeAttribute(CODEX_CHAT_LIST_RENAME_ROW_ATTRIBUTE_NAME);
    row.removeAttribute(CODEX_CHAT_LIST_RENAME_ROW_LOCATION_ATTRIBUTE_NAME);
  };
