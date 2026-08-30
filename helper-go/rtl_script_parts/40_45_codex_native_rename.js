  let codexNativeAppServerRequestPromise = null;
  const requireExactlyOneCodexValue = (values, label) => {
    const uniqueValues = [...new Set(values)];
    if (uniqueValues.length !== 1) {
      throw new Error("Expected exactly one " + label + ", found " + uniqueValues.length);
    }
    return uniqueValues[0];
  };
  const fetchCodexModuleSource = async (moduleUrl, label) => {
    const response = await fetch(moduleUrl);
    if (!response.ok) throw new Error("Failed to read " + label + ": HTTP " + response.status);
    return response.text();
  };
  const loadCodexNativeAppServerRequest = async () => {
    if (codexNativeAppServerRequestPromise) return codexNativeAppServerRequestPromise;
    codexNativeAppServerRequestPromise = (async () => {
      const entryScriptUrl = requireExactlyOneCodexValue(
        [...document.scripts]
          .map((scriptElement) => scriptElement.src)
          .filter((scriptUrl) => /\/index-[^/]+\.js(?:\?|$)/.test(scriptUrl)),
        "Codex entry script"
      );
      const entryScriptSource = await fetchCodexModuleSource(entryScriptUrl, "Codex entry script");
      const bridgeModuleFileName = requireExactlyOneCodexValue(
        [...entryScriptSource.matchAll(/["']\.\/(thread-context-inputs-[^"']+\.js)["']/g)]
          .map((match) => match[1]),
        "thread-context-inputs import"
      );
      const bridgeModuleUrl = new URL("./" + bridgeModuleFileName, entryScriptUrl).href;
      const bridgeModuleSource = await fetchCodexModuleSource(bridgeModuleUrl, "thread-context-inputs module");
      const appServerBridgeMatches = [...bridgeModuleSource.matchAll(
        /function ([A-Za-z_$][\w$]*)\(([A-Za-z_$][\w$]*),([A-Za-z_$][\w$]*)\)\{return ([A-Za-z_$][\w$]*)\.sendRequest\(\2,\3\)\}/g
      )].filter((match) => {
        const functionStart = match.index || 0;
        return bridgeModuleSource
          .slice(Math.max(0, functionStart - 1200), functionStart)
          .includes("Missing AppServer request message handler");
      });
      if (appServerBridgeMatches.length !== 1) {
        throw new Error("Expected exactly one Codex AppServer bridge function, found " + appServerBridgeMatches.length);
      }
      const localFunctionName = appServerBridgeMatches[0][1];
      const escapedLocalFunctionName = localFunctionName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const exportBlockStart = bridgeModuleSource.lastIndexOf("export{");
      if (exportBlockStart < 0) throw new Error("thread-context-inputs module has no export block");
      const exportNames = [...bridgeModuleSource.slice(exportBlockStart).matchAll(
        new RegExp("\\b" + escapedLocalFunctionName + " as ([A-Za-z_$][\\w$]*)\\b", "g")
      )].map((match) => match[1]);
      const exportName = requireExactlyOneCodexValue(exportNames, "Codex AppServer bridge export");
      const moduleNamespace = await import(bridgeModuleUrl);
      const requestFunction = moduleNamespace[exportName];
      if (typeof requestFunction !== "function") {
        throw new Error("Codex AppServer bridge export is not a function: " + exportName);
      }
      return requestFunction;
    })();
    return codexNativeAppServerRequestPromise;
  };
  const codexNativeConversationQueryLists = () => {
    const queryClient = findCodexReactQueryClient();
    if (!queryClient?.getQueryCache) throw new Error("Codex React Query client is unavailable");
    const queryLists = queryClient.getQueryCache().getAll()
      .map((query) => query.state?.data)
      .filter((data) =>
        Array.isArray(data) &&
        data.some((item) => item && typeof item.title === "string" && Array.isArray(item.turns))
      );
    if (queryLists.length === 0) throw new Error("No Codex conversation queries were found");
    return queryLists;
  };
  const codexNativeConversationTitles = (conversationId) =>
    [...new Set(
      codexNativeConversationQueryLists()
        .flatMap((queryList) => queryList)
        .filter((conversation) => compactCodexConversationId(conversation.id) === conversationId)
        .map((conversation) => compactText(conversation.title))
        .filter(Boolean)
    )];
  const waitForCodexNativeConversationTitle = async (conversationId, expectedTitle) => {
    let observedTitles = [];
    for (let attempt = 0; attempt < CODEX_NATIVE_RENAME_CACHE_MAX_ATTEMPTS; attempt += 1) {
      observedTitles = codexNativeConversationTitles(conversationId);
      if (observedTitles.length === 1 && observedTitles[0] === expectedTitle) return;
      await new Promise((resolve) => setTimeout(resolve, CODEX_NATIVE_RENAME_CACHE_POLL_INTERVAL_MS));
    }
    throw new Error(
      "Codex native rename did not converge for " + conversationId +
      "; expected " + JSON.stringify(expectedTitle) +
      ", observed " + JSON.stringify(observedTitles)
    );
  };
  const renameCodexConversationNatively = async (conversation, nextTitle) => {
    const conversationId = compactCodexConversationId(conversation?.id);
    const hostId = compactText(conversation?.hostId);
    const compactNextTitle = compactText(nextTitle);
    if (!conversationId) throw new Error("Native Codex rename requires a conversation id");
    if (!hostId) throw new Error("Native Codex rename requires a host id for " + conversationId);
    if (!compactNextTitle) throw new Error("Native Codex rename requires a non-empty title");
    const requestFunction = await loadCodexNativeAppServerRequest();
    await requestFunction("set-thread-title", {
      conversationId,
      hostId,
      title: compactNextTitle,
    });
    await waitForCodexNativeConversationTitle(conversationId, compactNextTitle);
  };
