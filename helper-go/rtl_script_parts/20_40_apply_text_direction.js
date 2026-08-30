  const isCodeLikeElement = (element) => element.closest(CODE_LIKE_SELECTOR);
  const shouldSkipElement = (element) => {
    if (!element.textContent.trim()) return true;
    if (element.matches(PLAIN_TEXT_CODE_BLOCK_SELECTOR)) {
      return !isPlainTextCodeBlock(element);
    }
    return Boolean(isCodeLikeElement(element));
  };
  const storeOriginalPresentationState = (element) => {
    if (element.hasAttribute(MANAGED_ATTRIBUTE_NAME)) return;
    const currentDir = element.getAttribute("dir");
    if (currentDir !== null) setAttributeIfChanged(element, PREVIOUS_DIR_ATTRIBUTE_NAME, currentDir);
    if (element.style.textAlign) setAttributeIfChanged(element, PREVIOUS_TEXT_ALIGN_ATTRIBUTE_NAME, element.style.textAlign);
    if (element.style.unicodeBidi) setAttributeIfChanged(element, PREVIOUS_UNICODE_BIDI_ATTRIBUTE_NAME, element.style.unicodeBidi);
    if (element.style.width) setAttributeIfChanged(element, PREVIOUS_WIDTH_ATTRIBUTE_NAME, element.style.width);
    if (element.style.flex) setAttributeIfChanged(element, PREVIOUS_FLEX_ATTRIBUTE_NAME, element.style.flex);
  };
  const findWebviewMessageBubble = (element) => {
    let currentElement = element;
    for (let depth = 0; depth < 8 && currentElement && currentElement !== document.body; depth += 1) {
      const className = String(currentElement.className || "");
      if (className.includes("bg-token-foreground") && className.includes("rounded-2xl")) return currentElement;
      currentElement = currentElement.parentElement;
    }
    return null;
  };
  const markWebviewMessageBubble = (element) => {
    const messageBubble = findWebviewMessageBubble(element);
    if (messageBubble) setAttributeIfChanged(messageBubble, MESSAGE_BUBBLE_ATTRIBUTE_NAME, "1");
  };
  const applyTextDirection = (element) => {
    if (shouldSkipElement(element)) return;
    storeOriginalPresentationState(element);
    setAttributeIfChanged(element, MANAGED_ATTRIBUTE_NAME, "1");
    markWebviewMessageBubble(element);
    if (isPlainTextCodeBlock(element)) {
      setAttributeIfChanged(element, PLAIN_TEXT_CODE_BLOCK_ATTRIBUTE_NAME, "1");
      setAttributeIfChanged(element, "dir", "rtl");
      setStyleValueIfChanged(element, "unicodeBidi", "plaintext");
      setStyleValueIfChanged(element, "textAlign", "right");
      return;
    }
    setAttributeIfChanged(element, "dir", containsArabicCharacters(element.textContent) ? "rtl" : "ltr");
    setStyleValueIfChanged(element, "unicodeBidi", "isolate");
    setStyleValueIfChanged(element, "textAlign", "start");
    if (isPermissionPromptTextElement(element)) {
      expandPermissionPromptTextContainer(element);
      if (containsArabicCharacters(element.textContent)) {
        setStyleValueIfChanged(element, "unicodeBidi", "plaintext");
        setStyleValueIfChanged(element, "textAlign", "right");
      }
    }
  };
  const applyCodexResponseAnnotationTextDirection = () => {
    document.querySelectorAll(CODEX_RESPONSE_ANNOTATION_TEXT_SELECTOR).forEach((element) => {
      if (!element.textContent.trim()) return;
      applyTextDirection(element);
      setAttributeIfChanged(element, CODEX_RESPONSE_ANNOTATION_TEXT_ATTRIBUTE_NAME, "1");
    });
    document.querySelectorAll(CODEX_TRANSIENT_ANNOTATION_CONTENT_SELECTOR).forEach((contentElement) => {
      contentElement.querySelectorAll(".text-xs.font-medium").forEach((labelElement) => {
        const normalizedLabel = labelElement.textContent.trim().toLowerCase();
        if (!CODEX_TRANSIENT_ANNOTATION_LABELS.has(normalizedLabel)) return;
        const textElement = labelElement.nextElementSibling;
        if (!textElement?.matches(".break-words.whitespace-pre-wrap")) return;
        applyTextDirection(textElement);
        setAttributeIfChanged(textElement, CODEX_RESPONSE_ANNOTATION_TEXT_ATTRIBUTE_NAME, "1");
        const annotationSectionElement = labelElement.parentElement;
        if (!annotationSectionElement) return;
        const annotationKind = normalizedLabel === "selected text:" ? "selected-text" : "user-comment";
        setAttributeIfChanged(annotationSectionElement, CODEX_RESPONSE_ANNOTATION_KIND_ATTRIBUTE_NAME, annotationKind);
      });
    });
  };
