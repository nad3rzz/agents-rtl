  const applyAntigravityNativeTextDirection = () => {
    const antigravityRoot = getAntigravityConversation() || getAntigravityAgentPanel();
    if (!antigravityRoot) return;
    [...new Set([...antigravityRoot.querySelectorAll(ANTIGRAVITY_CHAT_TEXT_SELECTOR)])]
      .filter(shouldManageAntigravityTextElement)
      .forEach(applyTextDirection);
  };
  const applyGeminiTextDirection = () => {
    if (!isGeminiCodeAssistDocument()) return;
    [...new Set([...document.querySelectorAll(GEMINI_CHAT_TEXT_SELECTOR)])]
      .filter(shouldManageGeminiTextElement)
      .forEach(applyTextDirection);
  };
  const getComposerDirectionForText = (text) => {
    const normalizedText = String(text || "").trim();
    if (!normalizedText) return "ltr";
    return containsArabicCharacters(normalizedText) ? "rtl" : "ltr";
  };
  const composerDirectionCache = new WeakMap();
  const applyCachedComposerDirection = (composerElement, attributeName) => {
    const composerText = composerElement.textContent || "";
    const direction = getComposerDirectionForText(composerText);
    const cachedValue = composerDirectionCache.get(composerElement);
    if (
      composerElement.getAttribute(attributeName) === direction &&
      cachedValue?.text === composerText &&
      cachedValue?.direction === direction
    ) {
      return;
    }

    const textAlign = direction === "rtl" ? "right" : "left";
    setManagedTextDirection(composerElement, direction, textAlign, "plaintext");
    setAttributeIfChanged(composerElement, attributeName, direction);
    composerDirectionCache.set(composerElement, { text: composerText, direction });
  };
  const applyCodexWebviewComposerDirection = () => {
    if (isWorkbenchDocument()) return;
    document.querySelectorAll(".ProseMirror[data-codex-composer='true']").forEach((editorElement) => {
      applyCachedComposerDirection(editorElement, COMPOSER_EDITOR_ATTRIBUTE_NAME);
    });
  };
  const applyGeminiComposerDirection = () => {
    if (!isGeminiCodeAssistDocument()) return;
    document.querySelectorAll(".chat-submit-input[contenteditable]").forEach((composerElement) => {
      applyCachedComposerDirection(composerElement, GEMINI_COMPOSER_ATTRIBUTE_NAME);
    });
  };
  const getNativeComposerText = (composerRoot) =>
    [...composerRoot.querySelectorAll(".view-line")]
      .map((lineElement) => lineElement.innerText || lineElement.textContent || "")
      .join("\n")
      .trim();
  const applyNativeVscodeComposerDirection = () => {
    const nativeChatPanel = getNativeChatPanel();
    if (!nativeChatPanel) return;
    nativeChatPanel.querySelectorAll(".interactive-input-editor").forEach((composerRoot) => {
      const composerText = getNativeComposerText(composerRoot);
      const direction = getComposerDirectionForText(composerText);
      const textAlign = direction === "rtl" ? "right" : "left";
      setAttributeIfChanged(composerRoot, NATIVE_VSC_COMPOSER_ATTRIBUTE_NAME, direction);
      composerRoot.querySelectorAll(".view-lines,.view-line").forEach((lineElement) => {
        setManagedTextDirection(lineElement, direction, textAlign, "plaintext");
      });
    });
  };
  const restoreComposerDirectionAttributes = () => {
    document.querySelectorAll("[" + COMPOSER_EDITOR_ATTRIBUTE_NAME + "]").forEach((element) => {
      element.removeAttribute(COMPOSER_EDITOR_ATTRIBUTE_NAME);
    });
    document.querySelectorAll("[" + NATIVE_VSC_COMPOSER_ATTRIBUTE_NAME + "]").forEach((element) => {
      element.removeAttribute(NATIVE_VSC_COMPOSER_ATTRIBUTE_NAME);
    });
    document.querySelectorAll("[" + GEMINI_COMPOSER_ATTRIBUTE_NAME + "]").forEach((element) => {
      element.removeAttribute(GEMINI_COMPOSER_ATTRIBUTE_NAME);
    });
  };
