  const installButtonClusterDrag = (buttonCluster, dragHandle) => {
    if (dragHandle.dataset.agentsRtlDragBound === "1") return;
    dragHandle.dataset.agentsRtlDragBound = "1";
    let dragState = null;
    dragHandle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const rect = buttonCluster.getBoundingClientRect();
      dragState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startLeft: rect.left,
        startTop: rect.top,
      };
      moveButtonClusterTo(buttonCluster, rect.left, rect.top);
      dragHandle.setPointerCapture?.(event.pointerId);
    });
    dragHandle.addEventListener("pointermove", (event) => {
      if (!dragState) return;
      moveButtonClusterTo(
        buttonCluster,
        dragState.startLeft + event.clientX - dragState.startX,
        dragState.startTop + event.clientY - dragState.startY
      );
    });
    const finishDrag = () => {
      if (!dragState) return;
      saveButtonClusterPosition(buttonCluster);
      dragState = null;
    };
    dragHandle.addEventListener("pointerup", finishDrag);
    dragHandle.addEventListener("pointercancel", finishDrag);
  };
