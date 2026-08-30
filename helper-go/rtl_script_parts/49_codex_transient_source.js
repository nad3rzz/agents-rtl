  const CODEX_TRANSIENT_SOURCE_LIST = "list";
  const CODEX_TRANSIENT_SOURCE_TABS = "tabs";
  const codexTransientSourceFromAnchor = (anchorElement) => {
    const renameEditor = anchorElement?.closest?.("#" + CODEX_CHAT_RENAME_EDITOR_ID);
    if (renameEditor?.dataset.agentsRtlSource) return renameEditor.dataset.agentsRtlSource;
    return anchorElement?.classList?.contains(CODEX_CHAT_LIST_RENAME_BUTTON_CLASS_NAME)
      ? CODEX_TRANSIENT_SOURCE_LIST
      : CODEX_TRANSIENT_SOURCE_TABS;
  };
  const codexTransientElementWasOpenedFromList = (element) =>
    element?.dataset.agentsRtlSource === CODEX_TRANSIENT_SOURCE_LIST;
