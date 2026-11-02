  const TABLE_INLINE_TEXT_SELECTOR = "a,strong,em,b,i,del,s";
  const shouldManageChatTable = (tableElement) =>
    !tableElement.closest("[data-thread-find-composer='true']," + CODE_LIKE_SELECTOR);
  const belongsToTable = (element, tableElement) => element.closest("table") === tableElement;
  const findFirstRealTableHeader = (tableElement) =>
    [...tableElement.querySelectorAll("th")]
      .find(
        (headerElement) =>
          belongsToTable(headerElement, tableElement) && headerElement.textContent.trim(),
      );
  const applyTableInlineTextDirection = (tableElement) => {
    [...tableElement.querySelectorAll(TABLE_INLINE_TEXT_SELECTOR)]
      .filter((inlineElement) => belongsToTable(inlineElement, tableElement))
      .forEach((inlineElement) => {
        if (!inlineElement.textContent.trim()) return;
        storeOriginalPresentationState(inlineElement);
        setAttributeIfChanged(inlineElement, MANAGED_ATTRIBUTE_NAME, "1");
        setAttributeIfChanged(
          inlineElement,
          "dir",
          containsArabicCharacters(inlineElement.textContent) ? "rtl" : "ltr",
        );
        setStyleValueIfChanged(inlineElement, "unicodeBidi", "isolate");
      });
  };
  const applyChatTableDirection = (rootElement) => {
    if (!rootElement) return;
    [...rootElement.querySelectorAll("table")]
      .filter(shouldManageChatTable)
      .forEach((tableElement) => {
        const firstRealHeaderElement = findFirstRealTableHeader(tableElement);
        if (!firstRealHeaderElement) return;
        const tableDirection = containsArabicCharacters(firstRealHeaderElement.textContent) ? "rtl" : "ltr";
        const tableContainerElement = tableElement.parentElement;
        if (!tableContainerElement) {
          throw new Error("Agents RTL table direction requires a table container");
        }
        setManagedTextDirection(tableContainerElement, tableDirection);
        setAttributeIfChanged(tableContainerElement, TABLE_WRAPPER_ATTRIBUTE_NAME, "1");
        setAttributeIfChanged(tableElement, TABLE_ATTRIBUTE_NAME, "1");
        applyTableInlineTextDirection(tableElement);
      });
  };
