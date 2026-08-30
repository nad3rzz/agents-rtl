  const shouldManageWebviewTable = (tableElement) =>
    !tableElement.closest("[data-thread-find-composer='true']," + CODE_LIKE_SELECTOR);
  const applyWebviewTableDirection = (rootElement) => {
    if (!rootElement) return;
    [...rootElement.querySelectorAll("table")]
      .filter(shouldManageWebviewTable)
      .forEach((tableElement) => {
        setManagedTextDirection(tableElement, "ltr");
        setAttributeIfChanged(tableElement, TABLE_ATTRIBUTE_NAME, "1");
        if (tableElement.parentElement) setAttributeIfChanged(tableElement.parentElement, TABLE_WRAPPER_ATTRIBUTE_NAME, "1");
        tableElement.querySelectorAll("thead,tbody,tr").forEach((sectionElement) => {
          setManagedTextDirection(sectionElement, "ltr");
        });
        tableElement.querySelectorAll("th,td").forEach((cellElement) => {
          const direction = containsArabicCharacters(cellElement.textContent || "") ? "rtl" : "ltr";
          const textAlign = cellElement.tagName === "TH" ? "center" : direction === "rtl" ? "right" : "left";
          setManagedTextDirection(cellElement, direction, textAlign, "plaintext");
        });
      });
  };
