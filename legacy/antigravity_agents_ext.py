import json
import time
from typing import Any
import requests
import websocket

DEBUGGER_BASE_URL = "http://127.0.0.1:9223"
CHATGPT_WEBVIEW_URL_MARKER = "extensionId=openai.chatgpt"
ANTIGRAVITY_AGENT_PAGE_URL_MARKER = "workbench-jetski-agent.html"
SCROLL_DELTA = 120
POLL_INTERVAL_SECONDS = 0.08
TARGET_RESCAN_INTERVAL_SECONDS = 2.0

ANTIGRAVITY_FIXES_JS = r"""
(() => {
  const KEY = "__agFixesInstalledTaggedUiV3";
  const TOOLS_STATE_KEY = "__agTools";
  const CHATGPT_WEBVIEW_URL_MARKER = "extensionId=openai.chatgpt";
  const isChatgptContext = location.href.includes(CHATGPT_WEBVIEW_URL_MARKER);
  const contextLabel = isChatgptContext ? "ChatGPT" : "Agent";
  const contextAccentColor = isChatgptContext ? "#007acc" : "#ff8c42";
  const contextRightOffset = 2;
  const controlBarRightOffset = 60;

  if (typeof window.__agCleanup === "function") {
      window.__agCleanup();
  }
  if (window[KEY]) return;
  window[KEY] = true;
  window[TOOLS_STATE_KEY] = {
      triggerExit: false,
      activeScrollDirection: 0,
      scrollStepDirection: 0
  };

  // 1. Fix: Select All (Ctrl+A)
  const keydownListener = (e) => {
    // Check if Ctrl or Cmd is pressed along with 'a' or 'A' or the arabic equivalent 'ش'
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'a' || e.code === 'KeyA')) {
      const active = document.activeElement;
      if (active && (
        active.tagName === 'TEXTAREA' ||
        active.tagName === 'INPUT' ||
        active.isContentEditable ||
        active.closest('[contenteditable], textarea')
      )) {
        // Stop VS Code from stealing the event
        e.stopPropagation();
      }
    }
  };
  window.addEventListener('keydown', keydownListener, true); // true = Capture Phase

  const stopContinuousScroll = () => {
      const tools = window[TOOLS_STATE_KEY];
      if (!tools) {
          return;
      }

      tools.activeScrollDirection = 0;
      tools.scrollStepDirection = 0;
  };

  // 2. Scroll Buttons with hold/step behavior matching vsc_agents_ext.py
  const bindScrollButton = (button, direction) => {
      let holdTimerId = null;
      let isContinuousScrollStarted = false;

      const clearHoldTimer = () => {
          if (holdTimerId !== null) {
              clearTimeout(holdTimerId);
              holdTimerId = null;
          }
      };

      button.onpointerdown = (event) => {
          event.preventDefault();
          isContinuousScrollStarted = false;
          button.setPointerCapture?.(event.pointerId);
          holdTimerId = window.setTimeout(() => {
              isContinuousScrollStarted = true;
              if (window[TOOLS_STATE_KEY]) {
                  window[TOOLS_STATE_KEY].activeScrollDirection = direction;
              }
          }, 180);
      };

      button.onpointerup = () => {
          clearHoldTimer();
          if (isContinuousScrollStarted) {
              stopContinuousScroll();
              isContinuousScrollStarted = false;
              return;
          }

          if (window[TOOLS_STATE_KEY]) {
              window[TOOLS_STATE_KEY].scrollStepDirection = direction;
          }
      };

      button.onpointercancel = () => {
          clearHoldTimer();
          if (isContinuousScrollStarted) {
              stopContinuousScroll();
              isContinuousScrollStarted = false;
          }
      };
  };

  const createScrollBtn = (id, text, topPos, bottomPos, dir) => {
      const btn = document.createElement("button");
      btn.id = id;
      btn.textContent = text;
      Object.assign(btn.style, {
          position: "fixed", zIndex: 1000001,
          background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.92)",
          border: "1px solid rgba(255,255,255,0.16)", padding: "6px 10px",
          borderRadius: "999px", cursor: "pointer", fontWeight: "bold",
          fontSize: "12px", lineHeight: "1.2", backdropFilter: "blur(8px)",
          boxShadow: "0 4px 12px rgba(0,0,0,0.18)"
      });
      if (topPos) btn.style.top = isChatgptContext ? "34px" : topPos;
      if (bottomPos) btn.style.bottom = isChatgptContext ? "0px" : bottomPos;
      btn.style.right = `${contextRightOffset}px`;
      btn.style.borderColor = contextAccentColor;
      btn.style.boxShadow = `0 4px 12px rgba(0,0,0,0.18), 0 0 0 1px ${contextAccentColor}`;

      bindScrollButton(btn, dir);
      document.body.appendChild(btn);
  };

  createScrollBtn("agScrollUpBtn", "▲", "75px", null, -1);
  createScrollBtn("agScrollDownBtn", "▼", null, "136px", 1);

  // 3. RTL Controller
  const createAntigravityRtlController = () => {
      const managedAttributeName = "data-ag-rtl-managed";
      const previousDirAttributeName = "data-ag-rtl-previous-dir";
      const previousTextAlignAttributeName = "data-ag-rtl-previous-text-align";
      const previousUnicodeBidiAttributeName = "data-ag-rtl-previous-unicode-bidi";
      const previousWidthAttributeName = "data-ag-rtl-previous-width";
      const previousFlexAttributeName = "data-ag-rtl-previous-flex";
      const arabicCharacterPattern = /[\u0600-\u06FF]/;
      const plainTextCodeBlockLanguageLabels = new Set([
          "txt",
          "text",
          "plaintext",
      ]);
      const plainTextCodeBlockSelector = [
          "div.text-size-chat.overflow-y-auto.p-2",
          "div.text-size-chat.overflow-auto.p-2",
      ].join(", ");
      const permissionPromptCardSelector =
          "[class*=\"rounded-3xl\"]:has([role=\"radiogroup\"])";
      const permissionPromptTextSelector = [
          `${permissionPromptCardSelector} .text-base.font-medium`,
          `${permissionPromptCardSelector} [class*="text-base"][class*="font-medium"]`,
      ].join(", ");
      const rtlTargetSelector = [
          "p",
          "li",
          "blockquote",
          "table",
          "thead",
          "tbody",
          "tr",
          "th",
          "td",
          ".whitespace-pre-wrap",
          "[class*='whitespace-pre-wrap']",
          "[dir='auto']",
          "[role='article'] p",
          "[role='article'] li",
          "[role='article'] blockquote",
          plainTextCodeBlockSelector
      ].join(", ");

      let isStopped = false;
      let isObserverConnected = false;

      const getRtlScopeRoot = () => {
          if (isChatgptContext) {
              return document.querySelector("[class*='react-scroll-to-bottom']") || document.body;
          }

          return (
              document.getElementById("conversation")
              || document.querySelector(".antigravity-agent-side-panel")
              || document.body
          );
      };

      const isCodeElement = (candidateElement) =>
          candidateElement.closest("code, pre, kbd, .font-mono, [role='code'], .ProseMirror, .hljs");

      const isPermissionPromptTextElement = (candidateElement) =>
          candidateElement.matches(permissionPromptTextSelector);

      const getCodeBlockLanguageLabel = (candidateElement) => {
          const codeBlockHeaderElement = candidateElement.previousElementSibling;
          if (!codeBlockHeaderElement) {
              return null;
          }

          const codeBlockLanguageElement =
              codeBlockHeaderElement.querySelector(".min-w-0.truncate")
              || codeBlockHeaderElement.firstElementChild
              || codeBlockHeaderElement;

          const normalizedCodeBlockLanguageLabel =
              codeBlockLanguageElement.textContent.trim().toLowerCase();

          return normalizedCodeBlockLanguageLabel || null;
      };

      const isPlainTextCodeBlock = (candidateElement) => {
          if (!candidateElement.matches(plainTextCodeBlockSelector)) {
              return false;
          }

          const normalizedCodeBlockLanguageLabel = getCodeBlockLanguageLabel(candidateElement);
          if (!normalizedCodeBlockLanguageLabel) {
              return false;
          }

          return plainTextCodeBlockLanguageLabels.has(normalizedCodeBlockLanguageLabel);
      };

      const shouldSkipElement = (candidateElement, textContent) => {
          if (!textContent) {
              return true;
          }

          if (candidateElement.matches(plainTextCodeBlockSelector)) {
              return !isPlainTextCodeBlock(candidateElement);
          }

          return Boolean(isCodeElement(candidateElement));
      };

      const storeOriginalPresentationState = (candidateElement) => {
          if (candidateElement.hasAttribute(managedAttributeName)) {
              return;
          }

          const existingDirValue = candidateElement.getAttribute("dir");
          if (existingDirValue !== null) {
              candidateElement.setAttribute(previousDirAttributeName, existingDirValue);
          }

          if (candidateElement.style.textAlign) {
              candidateElement.setAttribute(previousTextAlignAttributeName, candidateElement.style.textAlign);
          }

          if (candidateElement.style.unicodeBidi) {
              candidateElement.setAttribute(previousUnicodeBidiAttributeName, candidateElement.style.unicodeBidi);
          }

          if (candidateElement.style.width) {
              candidateElement.setAttribute(previousWidthAttributeName, candidateElement.style.width);
          }

          if (candidateElement.style.flex) {
              candidateElement.setAttribute(previousFlexAttributeName, candidateElement.style.flex);
          }
      };

      const updateElementDirection = (candidateElement) => {
          const textContent = candidateElement.textContent ? candidateElement.textContent.trim() : "";
          if (shouldSkipElement(candidateElement, textContent)) {
              return;
          }

          storeOriginalPresentationState(candidateElement);
          candidateElement.setAttribute(managedAttributeName, "1");
          candidateElement.setAttribute("dir", arabicCharacterPattern.test(textContent) ? "rtl" : "ltr");
          candidateElement.style.unicodeBidi = "isolate";
          candidateElement.style.textAlign = "start";

          if (isPermissionPromptTextElement(candidateElement)) {
              candidateElement.style.width = "100%";
              candidateElement.style.flex = "1 1 auto";
          }
      };

      const apply = () => {
          if (isStopped) {
              return;
          }

          const rtlScopeRoot = getRtlScopeRoot();
          if (!rtlScopeRoot) {
              return;
          }

          const rtlTargetElements = [
              ...rtlScopeRoot.querySelectorAll(rtlTargetSelector),
              ...document.querySelectorAll(permissionPromptTextSelector),
          ];
          [...new Set(rtlTargetElements)].forEach(updateElementDirection);
      };

      const restoreManagedElement = (candidateElement) => {
          const previousDirValue = candidateElement.getAttribute(previousDirAttributeName);
          if (previousDirValue !== null) {
              candidateElement.setAttribute("dir", previousDirValue);
          } else {
              candidateElement.removeAttribute("dir");
          }

          const previousTextAlignValue = candidateElement.getAttribute(previousTextAlignAttributeName);
          candidateElement.style.textAlign = previousTextAlignValue !== null ? previousTextAlignValue : "";

          const previousUnicodeBidiValue = candidateElement.getAttribute(previousUnicodeBidiAttributeName);
          candidateElement.style.unicodeBidi = previousUnicodeBidiValue !== null ? previousUnicodeBidiValue : "";

          const previousWidthValue = candidateElement.getAttribute(previousWidthAttributeName);
          candidateElement.style.width = previousWidthValue !== null ? previousWidthValue : "";

          const previousFlexValue = candidateElement.getAttribute(previousFlexAttributeName);
          candidateElement.style.flex = previousFlexValue !== null ? previousFlexValue : "";

          candidateElement.removeAttribute(managedAttributeName);
          candidateElement.removeAttribute(previousDirAttributeName);
          candidateElement.removeAttribute(previousTextAlignAttributeName);
          candidateElement.removeAttribute(previousUnicodeBidiAttributeName);
          candidateElement.removeAttribute(previousWidthAttributeName);
          candidateElement.removeAttribute(previousFlexAttributeName);
      };

      const mutationObserver = new MutationObserver(() => {
          apply();
      });

      const ensureObserverIsConnected = () => {
          if (isObserverConnected || !document.body) {
              return;
          }

          mutationObserver.observe(document.body, {
              childList: true,
              subtree: true,
              characterData: true
          });
          isObserverConnected = true;
      };

      const disconnectObserver = () => {
          if (!isObserverConnected) {
              return;
          }

          mutationObserver.disconnect();
          isObserverConnected = false;
      };

      const start = () => {
          isStopped = false;
          ensureObserverIsConnected();
          apply();
      };

      const stop = () => {
          isStopped = true;
          disconnectObserver();
          document.querySelectorAll(`[${managedAttributeName}]`).forEach(restoreManagedElement);
      };

      const toggle = () => {
          if (isStopped) {
              start();
              return;
          }

          stop();
      };

      start();
      return { apply, stop, toggle, isStopped: () => isStopped };
  };

  const antigravityRtlController = createAntigravityRtlController();

  // 4. Control Bar with Clean Exit functionality
  const controlBar = document.createElement("div");
  controlBar.id = "agControlBar";
  Object.assign(controlBar.style, {
      position: "fixed", bottom: "6px", right: `${controlBarRightOffset}px`, zIndex: 1000000,
      display: "flex", gap: "6px", background: "rgba(0,0,0,0.85)",
      alignItems: "center", padding: "4px 6px", borderRadius: "8px", border: `1px solid ${contextAccentColor}`
  });

  const contextBadge = document.createElement("span");
  contextBadge.textContent = contextLabel;
  Object.assign(contextBadge.style, {
      background: contextAccentColor,
      color: "white",
      padding: "4px 8px",
      borderRadius: "999px",
      fontWeight: "bold",
      fontSize: "11px",
      lineHeight: "1.2",
      letterSpacing: "0.02em"
  });

  const btnRtl = document.createElement("button");
  btnRtl.textContent = "RTL";
  Object.assign(btnRtl.style, {
      color: "white",
      border: "none",
      padding: "6px 10px",
      borderRadius: "6px",
      cursor: "pointer",
      fontWeight: "bold",
      fontSize: "13px",
      lineHeight: "1.2"
  });

  const updateRtlButtonAppearance = () => {
      btnRtl.style.background = antigravityRtlController.isStopped() ? "#f33" : "#1ec11e";
  };

  btnRtl.onclick = () => {
      antigravityRtlController.toggle();
      updateRtlButtonAppearance();
  };
  updateRtlButtonAppearance();

  const btnExit = document.createElement("button");
  btnExit.textContent = "Exit";
  Object.assign(btnExit.style, { background: "#f33", color: "white", border: "none", padding: "6px 10px", borderRadius: "6px", cursor: "pointer", fontWeight: "bold", fontSize: "13px", lineHeight: "1.2" });

  const cleanupAntigravityUi = (shouldPreserveToolsState) => {
      stopContinuousScroll();
      window.removeEventListener('keydown', keydownListener, true);
      antigravityRtlController.stop();
      document.getElementById("agScrollUpBtn")?.remove();
      document.getElementById("agScrollDownBtn")?.remove();
      document.getElementById("agControlBar")?.remove();
      if (!shouldPreserveToolsState) {
          delete window[TOOLS_STATE_KEY];
      }
      delete window.__agCleanup;
      delete window[KEY];
      console.log("Antigravity UI fixes deactivated and removed completely.");
  };

  window.__agCleanup = () => {
      cleanupAntigravityUi(false);
  };

  btnExit.onclick = () => {
      if (window[TOOLS_STATE_KEY]) {
          window[TOOLS_STATE_KEY].triggerExit = true;
      }
      cleanupAntigravityUi(true);
  };

  controlBar.append(contextBadge, btnRtl, btnExit);
  document.body.append(controlBar);

  console.log("Antigravity Addons injected successfully!");
})();
"""

def create_websocket_connection(websocket_url: str) -> Any:
    return websocket.create_connection(websocket_url)

def fetch_debugger_targets() -> list[dict[str, Any]]:
    response = requests.get(f"{DEBUGGER_BASE_URL}/json", timeout=3)
    response.raise_for_status()

    targets = response.json()
    if not isinstance(targets, list):
        raise RuntimeError("Debugger target list is not a list.")
    return targets

def is_supported_target(target: dict[str, Any]) -> bool:
    target_type = target.get("type")
    target_url = target.get("url")

    if not isinstance(target_url, str):
        return False

    if target_type == "iframe":
        return CHATGPT_WEBVIEW_URL_MARKER in target_url

    if target_type == "page":
        return ANTIGRAVITY_AGENT_PAGE_URL_MARKER in target_url

    return False

def find_all_supported_targets(should_print_targets: bool = True) -> list[dict[str, Any]]:
    all_targets = fetch_debugger_targets()
    if should_print_targets:
        print(f"\\n[System] Found {len(all_targets)} targets internally. Printing available targets:")

    targets = []
    for t in all_targets:
        if should_print_targets:
            print(f" - Type: {t.get('type'):<8} | URL: {t.get('url')}")

        if is_supported_target(t):
            targets.append(t)
    return targets

def send_devtools_command(
    ws: Any,
    command_id: int,
    method_name: str,
    params: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {"id": command_id, "method": method_name}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))

def receive_devtools_result(ws: Any, expected_command_id: int) -> dict[str, Any]:
    while True:
        response = json.loads(ws.recv())
        if response.get("id") != expected_command_id:
            continue

        if "error" in response:
            raise RuntimeError(response["error"])

        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("DevTools command result payload is invalid.")

        return result

def evaluate_in_execution_context(
    websocket_connection: Any,
    context_id: int | None,
    expression: str,
) -> Any:
    evaluation_params: dict[str, Any] = {
        "expression": expression,
        "returnByValue": True,
    }

    if context_id is not None:
        evaluation_params["contextId"] = context_id

    send_devtools_command(
        websocket_connection,
        99,
        "Runtime.evaluate",
        evaluation_params,
    )

    while True:
        response = json.loads(websocket_connection.recv())
        if response.get("id") == 99:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result", {}).get("result", {}).get("value")

def dispatch_mouse_wheel_scroll(
    websocket_connection: Any,
    x: int,
    y: int,
    delta_y: int,
) -> None:
    send_devtools_command(
        websocket_connection,
        98,
        "Input.dispatchMouseEvent",
        {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": 0,
            "deltaY": delta_y,
            "pointerType": "mouse",
        },
    )
    receive_devtools_result(websocket_connection, 98)

def read_extension_state(
    websocket_connection: Any,
    context_id: int,
) -> dict[str, Any]:
    state = evaluate_in_execution_context(
        websocket_connection,
        context_id,
        """
(() => {
  const tools = window.__agTools;
  const isChatgptContext = location.href.includes('extensionId=openai.chatgpt');
  let scrollContainer = null;

  const isScrollableElement = (element, shouldAcceptOverlay) => {
    const style = window.getComputedStyle(element);
    const supportedOverflowValues = shouldAcceptOverlay
      ? ['auto', 'scroll', 'overlay']
      : ['auto', 'scroll'];

    return (
      supportedOverflowValues.includes(style.overflowY) &&
      element.scrollHeight > element.clientHeight
    );
  };

  const findChatgptScrollContainer = () => {
    const firstMessageElement = document.querySelector('[data-content-search-unit-key]');

    if (firstMessageElement) {
      let currentElement = firstMessageElement.parentElement;
      while (currentElement && currentElement !== document.body) {
        if (isScrollableElement(currentElement, false)) {
          return currentElement;
        }

        currentElement = currentElement.parentElement;
      }
    }

    return (
      [...document.querySelectorAll('div')].find((element) =>
        isScrollableElement(element, false)
      ) || null
    );
  };

  const findAntigravityScrollContainer = () => {
    const rootCandidates = [
      document.querySelector('#conversation'),
      document.querySelector('.antigravity-agent-side-panel'),
      document.querySelector('[class*="react-scroll-to-bottom"]'),
      document.querySelector('[data-content-search-unit-key]'),
    ].filter(Boolean);

    for (const rootCandidate of rootCandidates) {
      let currentElement = rootCandidate;
      while (currentElement && currentElement !== document.body) {
        if (isScrollableElement(currentElement, true)) {
          return currentElement;
        }

        currentElement = currentElement.parentElement;
      }
    }

    const scrollableElements = [...document.querySelectorAll('div, main, section')].filter((element) =>
      isScrollableElement(element, true)
    );

    return scrollableElements.sort((leftElement, rightElement) => {
      return rightElement.scrollHeight - leftElement.scrollHeight;
    })[0] || null;
  };

  scrollContainer = isChatgptContext
    ? findChatgptScrollContainer()
    : findAntigravityScrollContainer();

  const scrollStepDirection = tools?.scrollStepDirection || 0;
  if (tools) {
    tools.scrollStepDirection = 0;
  }

  if (!scrollContainer) {
    return {
      triggerExit: Boolean(tools?.triggerExit),
      hasControlBar: Boolean(document.getElementById('agControlBar')),
      activeScrollDirection: tools?.activeScrollDirection || 0,
      scrollStepDirection,
      scrollX: null,
      scrollY: null,
    };
  }

  const rect = scrollContainer.getBoundingClientRect();
  return {
    triggerExit: Boolean(tools?.triggerExit),
    hasControlBar: Boolean(document.getElementById('agControlBar')),
    activeScrollDirection: tools?.activeScrollDirection || 0,
    scrollStepDirection,
    scrollX: Math.round(rect.left + rect.width / 2),
    scrollY: Math.round(rect.top + rect.height / 2),
  };
})()
        """.strip(),
    )
    if not isinstance(state, dict):
        raise RuntimeError("Extension state payload is invalid.")
    return state

def open_target_session(target: dict[str, Any]) -> dict[str, Any] | None:
    print(f"[System] Injecting into: {target.get('title') or target.get('url')} ...")
    ws = create_websocket_connection(target["webSocketDebuggerUrl"])
    try:
        ws.settimeout(3)
        send_devtools_command(ws, 1, "Runtime.enable")
        
        deadline = time.time() + 3
        main_context_id: int | None = None

        while time.time() < deadline:
            response = json.loads(ws.recv())
            if response.get("method") == "Runtime.executionContextCreated":
                context = response["params"]["context"]
                aux_data = context.get("auxData", {})
                if aux_data.get("isDefault") and aux_data.get("frameId"):
                    main_context_id = context["id"]
                    break

        if main_context_id is None:
            print("[Warning] No main context found for this target. Skipping.")
            return

        # Inject the fixes script
        send_devtools_command(
            ws,
            2,
            "Runtime.evaluate",
            {"expression": ANTIGRAVITY_FIXES_JS, "contextId": main_context_id},
        )
        receive_devtools_result(ws, 2)
        print("[System] Injection successful!")
        return {
            "context_id": main_context_id,
            "target": target,
            "websocket_connection": ws,
        }
    except Exception as e:
        print(f"[Error] Failed to inject: {e}")
        ws.close()
        return None

def close_target_session(target_session: dict[str, Any]) -> None:
    websocket_connection = target_session.get("websocket_connection")
    if websocket_connection is None:
        return

    try:
        websocket_connection.close()
    except Exception:
        pass

def get_target_session_id(target_session: dict[str, Any]) -> str | None:
    target = target_session.get("target")
    if not isinstance(target, dict):
        return None

    target_id = target.get("id")
    return target_id if isinstance(target_id, str) else None

def refresh_missing_target_sessions(
    target_sessions: list[dict[str, Any]],
    exited_target_ids: set[str],
) -> None:
    active_target_ids = {
        target_session_id
        for target_session_id in (
            get_target_session_id(target_session)
            for target_session in target_sessions
        )
        if target_session_id is not None
    }

    for target in find_all_supported_targets(should_print_targets=False):
        target_id = target.get("id")
        if (
            not isinstance(target_id, str)
            or target_id in active_target_ids
            or target_id in exited_target_ids
        ):
            continue

        reopened_target_session = open_target_session(target)
        if reopened_target_session is not None:
            target_sessions.append(reopened_target_session)
            active_target_ids.add(target_id)

def run_scroll_monitor_loop(target_sessions: list[dict[str, Any]]) -> None:
    if not target_sessions:
        return

    print("[System] Scroll monitor active. Use Exit on each toolbar when done.")
    try:
        exited_target_ids: set[str] = set()
        next_target_rescan_time = time.monotonic() + TARGET_RESCAN_INTERVAL_SECONDS
        while target_sessions:
            current_time = time.monotonic()
            if current_time >= next_target_rescan_time:
                refresh_missing_target_sessions(target_sessions, exited_target_ids)
                next_target_rescan_time = current_time + TARGET_RESCAN_INTERVAL_SECONDS

            has_active_scroll = False
            target_sessions_to_remove: list[dict[str, Any]] = []

            for target_session in list(target_sessions):
                websocket_connection = target_session["websocket_connection"]
                context_id = target_session["context_id"]

                try:
                    state = read_extension_state(websocket_connection, context_id)
                except Exception as error:
                    print(
                        f"[Warning] Lost target session for "
                        f"{target_session['target'].get('title') or target_session['target'].get('url')}: {error}"
                    )
                    target_sessions_to_remove.append(target_session)
                    continue

                scroll_x = state.get("scrollX")
                scroll_y = state.get("scrollY")
                scroll_step_direction = state.get("scrollStepDirection")
                active_scroll_direction = state.get("activeScrollDirection")

                try:
                    if (
                        isinstance(scroll_x, int)
                        and isinstance(scroll_y, int)
                        and isinstance(scroll_step_direction, int)
                        and scroll_step_direction
                    ):
                        dispatch_mouse_wheel_scroll(
                            websocket_connection,
                            scroll_x,
                            scroll_y,
                            SCROLL_DELTA * scroll_step_direction,
                        )

                    if (
                        isinstance(scroll_x, int)
                        and isinstance(scroll_y, int)
                        and isinstance(active_scroll_direction, int)
                        and active_scroll_direction
                    ):
                        has_active_scroll = True
                        dispatch_mouse_wheel_scroll(
                            websocket_connection,
                            scroll_x,
                            scroll_y,
                            SCROLL_DELTA * active_scroll_direction,
                        )
                except Exception as error:
                    print(
                        f"[Warning] Scroll dispatch failed for "
                        f"{target_session['target'].get('title') or target_session['target'].get('url')}: {error}"
                    )
                    target_sessions_to_remove.append(target_session)
                    continue

                if state.get("triggerExit"):
                    target_session_id = get_target_session_id(target_session)
                    if target_session_id is not None:
                        exited_target_ids.add(target_session_id)
                    target_sessions_to_remove.append(target_session)
                    continue

                if not state.get("hasControlBar"):
                    target_sessions_to_remove.append(target_session)

            for target_session_to_remove in target_sessions_to_remove:
                close_target_session(target_session_to_remove)
                if target_session_to_remove in target_sessions:
                    target_sessions.remove(target_session_to_remove)

            time.sleep(POLL_INTERVAL_SECONDS / 2 if has_active_scroll else POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n[System] Interrupted.")
    finally:
        for remaining_target_session in list(target_sessions):
            close_target_session(remaining_target_session)
        print("[System] Terminated.")

def main() -> None:
    print("[System] Searching for Antigravity Windows...")
    while True:
        try:
            targets = find_all_supported_targets()
            if targets:
                break
        except Exception:
            pass
        time.sleep(3)
            
    print(f"\\n[System] Found {len(targets)} window(s), injecting fixes into ALL of them...")
    target_sessions: list[dict[str, Any]] = []
    for t in targets:
        opened_target_session = open_target_session(t)
        if opened_target_session is not None:
            target_sessions.append(opened_target_session)

    print("\\n[System] Done! Check the app now.")
    run_scroll_monitor_loop(target_sessions)

if __name__ == "__main__":
    main()
