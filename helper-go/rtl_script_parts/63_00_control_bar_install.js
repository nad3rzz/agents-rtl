  const installControlButtons = () => {
    if (!shouldInstallControls()) {
      removeControlButtons();
      return;
    }
    document.getElementById(BUTTON_CLUSTER_ID)?.remove();
    const controlHost = findControlHost();
    if (!controlHost) {
      updateControlButtons();
      return;
    }
    let controlBar = document.getElementById(CONTROL_BAR_ID);
    if (!controlBar) controlBar = createControlBar();
    setAttributeIfChanged(controlBar, "data-agents-rtl-context", controlHost.context || "default");
    if (controlHost.wrapInActionItem) {
      let actionItem = document.getElementById(CONTROL_HOST_ID);
      if (!actionItem) {
        actionItem = document.createElement("li");
        actionItem.id = CONTROL_HOST_ID;
        actionItem.className = "action-item";
      }
      if (!actionItem.contains(controlBar)) actionItem.append(controlBar);
      if (actionItem.parentElement !== controlHost.host) controlHost.host.append(actionItem);
    } else {
      document.getElementById(CONTROL_HOST_ID)?.remove();
      if (controlHost.insertBeforeFirstChild) {
        if (controlBar.parentElement !== controlHost.host || controlBar !== controlHost.host.firstElementChild) {
          controlHost.host.insertBefore(controlBar, controlHost.host.firstElementChild || null);
        }
      } else if (controlBar.parentElement !== controlHost.host) {
        controlHost.host.append(controlBar);
      }
    }
    updateControlButtons();
  };
