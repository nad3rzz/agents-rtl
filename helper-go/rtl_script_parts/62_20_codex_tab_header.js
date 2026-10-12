  const codexTabsTextCache = new WeakMap();
  let codexBackButtonCache = null;
  let codexHeaderHostCache = null;
  const clearCodexHeaderElementCache = () => {
    codexBackButtonCache = null;
    codexHeaderHostCache = null;
  };
  const codexCachedTextSource = (element) =>
    element?.getAttribute?.("aria-label") || element?.textContent || "";
  const codexTabsText = (element) => {
    if (!element) return "";
    const textSource = codexCachedTextSource(element);
    const cachedValue = codexTabsTextCache.get(element);
    if (cachedValue?.source === textSource) return cachedValue.text;
    const text = compactText(textSource);
    codexTabsTextCache.set(element, { source: textSource, text });
    return text;
  };
  const isCodexUsableTitle = (title) => {
    if (!title || title.length > 90) return false;
    return !new Set(["CHAT", "CODEX", "Tasks", "View all", "New chat", "Back", "\u0631\u062C\u0648\u0639", "\u0639\u0648\u062F\u0629", "+", "...", "Settings"]).has(title);
  };
  const codexBackButtonIsUsable = (element) => {
    if (!element?.isConnected) return false;
    if (element.closest("#" + CODEX_CHAT_TABS_BAR_ID)) return false;
    if (element.closest("#" + CODEX_CHAT_ACTIVE_ACTIONS_ID)) return false;
    const label = compactText(element.getAttribute("aria-label") || "");
    const text = codexTabsText(element);
    return /^(Back|\u0631\u062C\u0648\u0639|\u0639\u0648\u062F\u0629)$/.test(label) ||
      /^(\u2190|\u2039|Back|\u0631\u062C\u0648\u0639|\u0639\u0648\u062F\u0629)$/.test(text);
  };
  const findCodexBackButton = () => {
    if (codexBackButtonIsUsable(codexBackButtonCache)) return codexBackButtonCache;
    codexBackButtonCache = [...document.querySelectorAll("button,[role='button']")].find((element) => {
      if (element.closest("#" + CODEX_CHAT_TABS_BAR_ID)) return false;
      if (element.closest("#" + CODEX_CHAT_ACTIVE_ACTIONS_ID)) return false;
      return codexBackButtonIsUsable(element);
    }) || null;
    return codexBackButtonCache;
  };
  const findCodexChatTabsHeaderHost = () => {
    if (codexHeaderHostCache?.isConnected && codexBackButtonCache?.isConnected && codexHeaderHostCache.contains(codexBackButtonCache)) {
      return codexHeaderHostCache;
    }
    const backButton = findCodexBackButton();
    if (!backButton) return null;
    codexHeaderHostCache = backButton.closest(".flex.min-w-0.items-center") ||
      backButton.closest(".flex.min-w-0") ||
      backButton.parentElement?.parentElement ||
      backButton.parentElement;
    return codexHeaderHostCache;
  };
  const findCodexCurrentTitleElement = () => {
    const headerHost = findCodexChatTabsHeaderHost();
    if (!headerHost) return null;
    const backButton = findCodexBackButton();
    return [...headerHost.querySelectorAll("button,[role='button']")].find((element) => {
      if (element === backButton) return false;
      if (element.closest("#" + CODEX_CHAT_TABS_BAR_ID)) return false;
      if (element.closest("#" + CODEX_CHAT_ACTIVE_ACTIONS_ID)) return false;
      return isCodexUsableTitle(codexTabsText(element));
    }) || null;
  };
  const findCodexCurrentConversationTitle = () => codexTabsText(findCodexCurrentTitleElement());
  const findActiveCodexConversationId = (conversations) => {
    const validConversationIds = new Set(conversations.map((conversation) => conversation.id));
    return findCurrentCodexConversationIdFromReact(validConversationIds);
  };
  const handleCodexTabsHeaderResize = (entries) => {
    const state = window[KEY];
    if (!state?.codexTabsHeaderObservedElement) return;
    let observedEntry = null;
    for (const entry of entries) {
      if (entry.target === state.codexTabsHeaderObservedElement) {
        observedEntry = entry;
        break;
      }
    }
    if (!observedEntry) throw new Error("Codex tabs ResizeObserver did not include its observed header.");
    const observedWidth = Math.round(observedEntry.contentRect.width);
    if (observedWidth <= 0 || observedWidth === state.codexTabsHeaderObservedWidth) return;
    state.codexTabsHeaderObservedWidth = observedWidth;
    renderCodexChatTabs();
  };
  const disconnectCodexTabsHeaderResizeObserver = () => {
    const state = window[KEY];
    if (!state) return;
    state.codexTabsHeaderResizeObserver?.disconnect();
    state.codexTabsHeaderResizeObserver = null;
    state.codexTabsHeaderObservedElement = null;
    state.codexTabsHeaderObservedWidth = 0;
  };
  const ensureCodexTabsHeaderResizeObserver = (headerHost) => {
    const state = window[KEY];
    if (!state) throw new Error("Agents RTL state is unavailable for Codex tab resize observation.");
    if (state.codexTabsHeaderObservedElement === headerHost && state.codexTabsHeaderResizeObserver) return;
    disconnectCodexTabsHeaderResizeObserver();
    state.codexTabsHeaderObservedElement = headerHost;
    state.codexTabsHeaderObservedWidth = Math.round(headerHost.getBoundingClientRect().width);
    state.codexTabsHeaderResizeObserver = new ResizeObserver(handleCodexTabsHeaderResize);
    state.codexTabsHeaderResizeObserver.observe(headerHost);
  };
