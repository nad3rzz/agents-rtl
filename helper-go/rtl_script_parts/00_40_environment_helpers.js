  const containsArabicCharacters = (text) => /[\u0600-\u06FF]/.test(text);
  const getNativeChatPanel = () => document.getElementById(NATIVE_CHAT_PANEL_ID);
  const getAntigravityConversation = () => document.getElementById(ANTIGRAVITY_CONVERSATION_ID);
  const getAntigravityInputBox = () => document.getElementById(ANTIGRAVITY_INPUT_BOX_ID);
  const getAntigravityAgentPanel = () => document.querySelector(ANTIGRAVITY_AGENT_PANEL_SELECTOR);
  const isWorkbenchDocument = () => location.href.includes("/workbench/workbench.html");
  const isAntigravityNativeDocument = () => Boolean(
    getAntigravityConversation() ||
    getAntigravityInputBox() ||
    getAntigravityAgentPanel()
  );
  const isGeminiCodeAssistDocument = () =>
    document.body?.classList?.contains("gm3") &&
    Boolean(document.querySelector("app-ai-chat,chat-history,chat-input,.chat-submit-input[contenteditable]"));
  const getZoneSymbolName = (eventName) =>
    window.Zone && typeof window.Zone.__symbol__ === "function"
      ? window.Zone.__symbol__(eventName)
      : "__zone_symbol__" + eventName;
  const getGeminiMessageData = (args) => {
    const candidates = [args?.[2]?.[0], args?.[0], args?.[1]];
    for (const candidate of candidates) {
      if (candidate && typeof candidate === "object" && candidate.data && typeof candidate.data === "object") {
        return candidate.data;
      }
    }
    return null;
  };
