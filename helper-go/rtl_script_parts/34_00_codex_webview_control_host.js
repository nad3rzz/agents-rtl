  const isCodexWebviewComposerEditor = (element) =>
    element?.matches?.(".ProseMirror[data-codex-composer='true']");
  const findBottomMostCodexComposerEditor = () => {
    let selectedEditor = null;
    let selectedRect = null;
    document.querySelectorAll(".ProseMirror[data-codex-composer='true']").forEach((editorElement) => {
      if (!isCodexWebviewComposerEditor(editorElement)) return;
      const rect = getVisibleViewportRect(editorElement);
      if (!rect || rect.width <= 180) return;
      if (!selectedRect || rect.bottom > selectedRect.bottom) {
        selectedEditor = editorElement;
        selectedRect = rect;
      }
    });
    return selectedEditor ? { editor: selectedEditor, rect: selectedRect } : null;
  };
  const findBestCodexFooterForComposer = (rootElement, editorRect) => {
    let selectedFooter = null;
    let selectedRect = null;
    (rootElement || document).querySelectorAll(WEBVIEW_CONTROL_FOOTER_SELECTOR).forEach((footerElement) => {
      const rect = getVisibleViewportRect(footerElement);
      if (!rect) return;
      const isResponsiveComposerFooter = footerElement.matches("[data-composer-footer-responsive]");
      if (isResponsiveComposerFooter) {
        if (
          rect.top > editorRect.bottom + 90 ||
          rect.bottom < editorRect.top - 4 ||
          rect.width <= 180 ||
          rect.height < 18 ||
          rect.height > 140 ||
          footerElement.children.length < 2
        ) {
          return;
        }
        if (!selectedRect || rect.top < selectedRect.top) {
          selectedFooter = footerElement;
          selectedRect = rect;
        }
        return;
      }
      if (
        rect.top < editorRect.bottom - 10 ||
        rect.top > editorRect.bottom + 90 ||
        rect.top < editorRect.top - 4 ||
        rect.width <= 180 ||
        rect.height < 18 ||
        rect.height > 48 ||
        footerElement.children.length < 2
      ) {
        return;
      }
      if (!selectedRect || rect.top < selectedRect.top) {
        selectedFooter = footerElement;
        selectedRect = rect;
      }
    });
    return selectedFooter;
  };
  const findResponsiveCodexFooterControlHost = (footer) => {
    if (!footer.matches("[data-composer-footer-responsive]")) return null;
    const rightCell =
      footer.querySelector(".col-start-3.row-start-2") ||
      [...footer.children].find((child) => String(child.className || "").includes("col-start-3")) ||
      footer.children[footer.children.length - 1];
    const host =
      rightCell?.querySelector(".flex.min-w-0.items-center") ||
      rightCell?.firstElementChild ||
      rightCell;
    return host instanceof Element ? host : null;
  };
  const findWebviewControlHost = () => {
    const editorMatch = findBottomMostCodexComposerEditor();
    if (!editorMatch) return null;
    const { editor, rect: editorRect } = editorMatch;
    let root = editor;
    for (let depth = 0; depth < 12 && root; depth += 1) {
      const rect = root.getBoundingClientRect();
      if (root.querySelector?.(WEBVIEW_CONTROL_FOOTER_SELECTOR) && rect.height < 360 && rect.width > 240) break;
      root = root.parentElement;
    }
    const footer = findBestCodexFooterForComposer(root, editorRect);
    if (!footer) return null;
    const responsiveFooterHost = findResponsiveCodexFooterControlHost(footer);
    if (responsiveFooterHost) {
      setStyleValueIfChanged(responsiveFooterHost, "display", "flex");
      setStyleValueIfChanged(responsiveFooterHost, "alignItems", "center");
      setStyleValueIfChanged(responsiveFooterHost, "justifyContent", "flex-end");
      setStyleValueIfChanged(responsiveFooterHost, "gap", "5px");
      setStyleValueIfChanged(responsiveFooterHost, "overflow", "visible");
      return {
        host: responsiveFooterHost,
        wrapInActionItem: false,
        context: "webview",
        insertBeforeFirstChild: true,
      };
    }
    const footerChildren = [...footer.children].filter((child) => child.id !== CONTROL_HOST_ID && child.id !== CONTROL_BAR_ID);
    const middleCell = footerChildren[1];
    if (!middleCell) return null;
    setStyleValueIfChanged(middleCell, "display", "flex");
    setStyleValueIfChanged(middleCell, "alignItems", "center");
    setStyleValueIfChanged(middleCell, "justifyContent", "center");
    setStyleValueIfChanged(middleCell, "minWidth", "100px");
    setStyleValueIfChanged(middleCell, "overflow", "visible");
    return { host: middleCell, wrapInActionItem: false, context: "webview" };
  };
