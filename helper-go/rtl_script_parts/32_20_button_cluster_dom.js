  const createDragHandle = () => {
    const dragHandle = document.createElement("div");
    dragHandle.setAttribute(DRAG_HANDLE_ATTRIBUTE_NAME, "1");
    dragHandle.textContent = "::";
    dragHandle.title = "Drag Agents RTL buttons";
    return dragHandle;
  };
  const getOrCreateButtonCluster = () => {
    if (!document.body) return null;
    let buttonCluster = document.getElementById(BUTTON_CLUSTER_ID);
    if (!buttonCluster) {
      buttonCluster = document.createElement("div");
      buttonCluster.id = BUTTON_CLUSTER_ID;
      buttonCluster.append(createDragHandle());
      document.body.append(buttonCluster);
      restoreButtonClusterPosition(buttonCluster);
    }
    let dragHandle = buttonCluster.querySelector("[" + DRAG_HANDLE_ATTRIBUTE_NAME + "]");
    if (!dragHandle) {
      dragHandle = createDragHandle();
      buttonCluster.prepend(dragHandle);
    }
    installButtonClusterDrag(buttonCluster, dragHandle);
    keepButtonClusterInViewport(buttonCluster);
    return buttonCluster;
  };
  const removeButtonCluster = () => {
    stopContinuousScroll();
    document.getElementById(BUTTON_CLUSTER_ID)?.remove();
    document.getElementById(CONTROL_BAR_ID)?.remove();
    document.getElementById(SCROLL_UP_BUTTON_ID)?.remove();
    document.getElementById(SCROLL_DOWN_BUTTON_ID)?.remove();
  };
