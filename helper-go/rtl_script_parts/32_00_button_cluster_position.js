  const buttonClusterPositionStorageKey = () =>
    BUTTON_CLUSTER_POSITION_STORAGE_KEY_PREFIX + (isWorkbenchDocument() ? "workbench" : "webview");
  const clampNumber = (value, minimumValue, maximumValue) =>
    Math.min(Math.max(value, minimumValue), maximumValue);
  const storedButtonClusterPosition = () => {
    const storedValue = localStorage.getItem(buttonClusterPositionStorageKey());
    if (storedValue === null) return null;
    const parsedValue = JSON.parse(storedValue);
    if (!Number.isFinite(parsedValue?.left) || !Number.isFinite(parsedValue?.top)) return null;
    return parsedValue;
  };
  const saveButtonClusterPosition = (buttonCluster) => {
    const rect = buttonCluster.getBoundingClientRect();
    localStorage.setItem(buttonClusterPositionStorageKey(), JSON.stringify({
      left: Math.round(rect.left),
      top: Math.round(rect.top),
    }));
  };
  const maxButtonClusterLeft = (buttonCluster) =>
    Math.max(BUTTON_CLUSTER_VIEWPORT_MARGIN_PX, window.innerWidth - buttonCluster.getBoundingClientRect().width - BUTTON_CLUSTER_VIEWPORT_MARGIN_PX);
  const maxButtonClusterTop = (buttonCluster) =>
    Math.max(BUTTON_CLUSTER_VIEWPORT_MARGIN_PX, window.innerHeight - buttonCluster.getBoundingClientRect().height - BUTTON_CLUSTER_VIEWPORT_MARGIN_PX);
  const moveButtonClusterTo = (buttonCluster, left, top) => {
    buttonCluster.style.left = clampNumber(left, BUTTON_CLUSTER_VIEWPORT_MARGIN_PX, maxButtonClusterLeft(buttonCluster)) + "px";
    buttonCluster.style.top = clampNumber(top, BUTTON_CLUSTER_VIEWPORT_MARGIN_PX, maxButtonClusterTop(buttonCluster)) + "px";
    buttonCluster.style.right = "auto";
    buttonCluster.style.bottom = "auto";
  };
  const restoreButtonClusterPosition = (buttonCluster) => {
    const storedPosition = storedButtonClusterPosition();
    if (storedPosition) {
      moveButtonClusterTo(buttonCluster, storedPosition.left, storedPosition.top);
      return;
    }
    buttonCluster.style.left = "auto";
    buttonCluster.style.top = "auto";
    buttonCluster.style.right = BUTTON_CLUSTER_DEFAULT_RIGHT_PX + "px";
    buttonCluster.style.bottom = BUTTON_CLUSTER_DEFAULT_BOTTOM_PX + "px";
  };
  const keepButtonClusterInViewport = (buttonCluster) => {
    const rect = buttonCluster.getBoundingClientRect();
    const nextLeft = clampNumber(rect.left, BUTTON_CLUSTER_VIEWPORT_MARGIN_PX, maxButtonClusterLeft(buttonCluster));
    const nextTop = clampNumber(rect.top, BUTTON_CLUSTER_VIEWPORT_MARGIN_PX, maxButtonClusterTop(buttonCluster));
    if (Math.round(nextLeft) === Math.round(rect.left) && Math.round(nextTop) === Math.round(rect.top)) return;
    moveButtonClusterTo(buttonCluster, nextLeft, nextTop);
    saveButtonClusterPosition(buttonCluster);
  };
