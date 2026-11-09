  const TABLE_INLINE_TEXT_SELECTOR = "a,strong,em,b,i,del,s";
  const shouldManageChatTable = (tableElement) =>
    !tableElement.closest("[data-thread-find-composer='true']," + CODE_LIKE_SELECTOR);
  const belongsToTable = (element, tableElement) => element.closest("table") === tableElement;
  const findTableCells = (tableElement) =>
    [...tableElement.querySelectorAll("th,td")]
      .filter((cellElement) => belongsToTable(cellElement, tableElement));
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
        const tableCellElements = findTableCells(tableElement);
        const hasRealTableCell = tableCellElements.some(
          (cellElement) => cellElement.textContent.trim(),
        );
        if (!hasRealTableCell) return;
        const tableHeaderElements = [...tableElement.querySelectorAll("th")]
          .filter((headerElement) => belongsToTable(headerElement, tableElement));
        const tableDirectionSourceElements =
          tableHeaderElements.length > 0 ? tableHeaderElements : tableCellElements;
        const tableDirectionSourceText = tableDirectionSourceElements
          .map((directionSourceElement) => directionSourceElement.textContent)
          .join(" ");
        const tableDirection = containsArabicCharacters(tableDirectionSourceText)
          ? "rtl"
          : "ltr";
        const tableContainerElement = tableElement.parentElement;
        if (!tableContainerElement) {
          throw new Error("Agents RTL table direction requires a table container");
        }
        setAttributeIfChanged(tableContainerElement, TABLE_WRAPPER_ATTRIBUTE_NAME, "1");
        setManagedTextDirection(tableElement, tableDirection);
        setAttributeIfChanged(tableElement, TABLE_ATTRIBUTE_NAME, "1");
        tableCellElements.forEach((cellElement) => {
          setManagedTextDirection(cellElement, tableDirection);
        });
        applyTableInlineTextDirection(tableElement);
      });
  };
