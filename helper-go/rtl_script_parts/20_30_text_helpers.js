  const getCodeBlockLanguageLabel = (element) => {
    const headerElement = element.previousElementSibling;
    if (!headerElement) return null;
    const languageElement =
      headerElement.querySelector(".min-w-0.truncate") ||
      headerElement.firstElementChild ||
      headerElement;
    return languageElement.textContent.trim().toLowerCase() || null;
  };
  const isPlainTextCodeBlock = (element) => {
    if (!element.matches(PLAIN_TEXT_CODE_BLOCK_SELECTOR)) return false;
    const label = getCodeBlockLanguageLabel(element);
    return Boolean(label && PLAIN_TEXT_CODE_BLOCK_LANGUAGE_LABELS.has(label));
  };
  const isPermissionPromptTextElement = (element) => element.matches(PERMISSION_PROMPT_TEXT_SELECTOR);
  const setAttributeIfChanged = (element, attributeName, value) => {
    const nextValue = String(value);
    if (element.getAttribute(attributeName) === nextValue) return false;
    element.setAttribute(attributeName, nextValue);
    return true;
  };
  const removeAttributeIfPresent = (element, attributeName) => {
    if (!element.hasAttribute(attributeName)) return false;
    element.removeAttribute(attributeName);
    return true;
  };
  const setStyleValueIfChanged = (element, propertyName, value) => {
    if (element.style[propertyName] === value) return false;
    element.style[propertyName] = value;
    return true;
  };
  const expandPermissionPromptTextContainer = (element) => {
    if (!isPermissionPromptTextElement(element)) return;
    const textContainer = element.parentElement;
    const headerRow = textContainer?.parentElement;
    [textContainer, headerRow].filter(Boolean).forEach((containerElement) => {
      setStyleValueIfChanged(containerElement, "width", "100%");
      setStyleValueIfChanged(containerElement, "maxWidth", "100%");
      setStyleValueIfChanged(containerElement, "flex", "1 1 auto");
      setStyleValueIfChanged(containerElement, "minWidth", "0");
    });
    setStyleValueIfChanged(element, "width", "100%");
    setStyleValueIfChanged(element, "maxWidth", "100%");
    setStyleValueIfChanged(element, "display", "block");
  };
