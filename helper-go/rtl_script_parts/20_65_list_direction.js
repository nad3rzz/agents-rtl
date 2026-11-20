  function readChatListItemOwnText(listItemElement, listElement) {
    const textWalker = document.createTreeWalker(listItemElement, NodeFilter.SHOW_TEXT);
    const textParts = [];
    let textNode = textWalker.nextNode();
    while (textNode !== null) {
      if (textNode.parentElement.closest("ul,ol") === listElement) {
        textParts.push(textNode.textContent);
      }
      textNode = textWalker.nextNode();
    }
    return textParts.join(" ");
  }

  function applyChatListElementDirection(element) {
    if (!element.matches("ul,ol,li,p,blockquote")) return false;
    const listElement = element.matches("ul,ol") ? element : element.closest("ul,ol");
    if (listElement === null) return false;
    const listDirection = containsArabicCharacters(listElement.textContent) ? "rtl" : "ltr";
    setManagedTextDirection(listElement, listDirection);
    if (element === listElement) return true;

    const ownText = element.matches("li")
      ? readChatListItemOwnText(element, listElement)
      : element.textContent;
    const textDirection = containsArabicCharacters(ownText) ? "rtl" : "ltr";
    if (element.matches("li")) {
      // The list item controls the native marker side. For English text in
      // an RTL list, plaintext independently lays out the text paragraph LTR
      // without moving React-owned nodes or replacing native list markers.
      // Arabic paragraphs retain isolate so embedded emphasis cannot reverse
      // emoji/label/sentence ordering by changing their paragraph base.
      const textIsolation = textDirection === listDirection ? "isolate" : "plaintext";
      setManagedTextDirection(element, listDirection, "start", textIsolation);
    } else {
      // Loose Markdown lists already have paragraph children: their text can
      // keep its own direction while sharing the parent list's alignment.
      setManagedTextDirection(element, textDirection, listDirection === "rtl" ? "right" : "left");
    }
    return true;
  }
