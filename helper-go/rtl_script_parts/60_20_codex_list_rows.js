  const codexConversationListRows = () =>
    [...new Set(
      [...document.querySelectorAll("button[aria-label='Archive chat']")]
        .map((archiveButton) => archiveButton.closest("[role='button']"))
        .filter(Boolean)
    )];
  const codexConversationListRowLocation = (row) =>
    row.closest("[role='menu'],[data-radix-popper-content-wrapper]") ? "menu" : "list";
  const syncCodexConversationListOverlayState = () => {
    const viewAllMenuIsOpen = codexConversationListRows().some((row) => codexConversationListRowLocation(row) === "menu");
    document.documentElement.dataset.agentsRtlCodexViewAllOpen = viewAllMenuIsOpen ? "1" : "0";
  };
