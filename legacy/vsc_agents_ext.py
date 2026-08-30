import json
import os
import time
from pathlib import Path
from typing import Any

import requests
import websocket

DEBUGGER_BASE_URL = "http://127.0.0.1:9222"
CHAT_SAVER_OUTPUT_FILE_PATH = Path(
    "/home/nad3r/Nad3rCloud/sync/remote/home/nad3r/Nad3rCloud/problems/chatgpt/chatgpt_replies.txt"
)
SCROLL_DELTA = 120
POLL_INTERVAL_SECONDS = 0.08

RTL_FIX = r"""
// === RTL-Pro v6 (clean isolate edition) ===
(() => {
  const KEY = "__rtlPro6";
  const RTL_PROCESSED_MARKER = "1";
  const MISSING_PRESENTATION_VALUE = "__rtlp6_missing__";
  const PLAIN_TEXT_CODE_BLOCK_LANGUAGE_LABELS = new Set([
    "txt",
    "text",
    "plaintext",
  ]);
  const PLAIN_TEXT_CODE_BLOCK_SELECTOR = [
    "div.text-size-chat.overflow-y-auto.p-2",
    "div.text-size-chat.overflow-auto.p-2",
  ].join(",");
  const CHAT_TEXT_SELECTOR = [
    "p",
    "li",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "[data-content-search-unit-key$=':user'] .text-size-chat.whitespace-pre-wrap",
    PLAIN_TEXT_CODE_BLOCK_SELECTOR,
  ].join(",");
  const PERMISSION_PROMPT_CARD_SELECTOR =
    "[class*=\"rounded-3xl\"]:has([role=\"radiogroup\"])";
  const PERMISSION_PROMPT_TEXT_SELECTOR = [
    `${PERMISSION_PROMPT_CARD_SELECTOR} .text-base.font-medium`,
    `${PERMISSION_PROMPT_CARD_SELECTOR} [class*=\"text-base\"][class*=\"font-medium\"]`,
  ].join(",");
  const CODE_LIKE_SELECTOR =
    "code,pre,kbd,.font-mono,[role=\"code\"],.ProseMirror,.hljs";

  if (window[KEY]?.installed) return;
  window[KEY] = { installed: true };

  const containsArabicCharacters = (text) => /[\u0600-\u06FF]/.test(text);

  const isCodeLikeElement = (element) => element.closest(CODE_LIKE_SELECTOR);

  const isPermissionPromptTextElement = (element) =>
    element.matches(PERMISSION_PROMPT_TEXT_SELECTOR);

  const getCodeBlockLanguageLabel = (element) => {
    const codeBlockHeaderElement = element.previousElementSibling;
    if (!codeBlockHeaderElement) return null;

    const codeBlockLanguageElement =
      codeBlockHeaderElement.querySelector(".min-w-0.truncate") ||
      codeBlockHeaderElement.firstElementChild ||
      codeBlockHeaderElement;

    const normalizedCodeBlockLanguageLabel =
      codeBlockLanguageElement.textContent.trim().toLowerCase();

    return normalizedCodeBlockLanguageLabel || null;
  };

  const isPlainTextCodeBlock = (element) => {
    if (!element.matches(PLAIN_TEXT_CODE_BLOCK_SELECTOR)) return false;

    const normalizedCodeBlockLanguageLabel = getCodeBlockLanguageLabel(element);
    if (!normalizedCodeBlockLanguageLabel) return false;

    return PLAIN_TEXT_CODE_BLOCK_LANGUAGE_LABELS.has(
      normalizedCodeBlockLanguageLabel
    );
  };

  const shouldSkipElement = (element) => {
    if (!element.textContent.trim() || element.dataset.rtlp6) return true;
    if (element.matches(PLAIN_TEXT_CODE_BLOCK_SELECTOR)) {
      return !isPlainTextCodeBlock(element);
    }
    return Boolean(isCodeLikeElement(element));
  };

  const preserveOriginalPresentation = (element) => {
    element.dataset.rtlp6 = RTL_PROCESSED_MARKER;
    element.dataset.rtlp6OriginalDir =
      element.getAttribute("dir") ?? MISSING_PRESENTATION_VALUE;
    element.dataset.rtlp6OriginalUnicodeBidi =
      element.style.unicodeBidi || MISSING_PRESENTATION_VALUE;
    element.dataset.rtlp6OriginalTextAlign =
      element.style.textAlign || MISSING_PRESENTATION_VALUE;
    element.dataset.rtlp6OriginalWidth =
      element.style.width || MISSING_PRESENTATION_VALUE;
    element.dataset.rtlp6OriginalFlex =
      element.style.flex || MISSING_PRESENTATION_VALUE;
  };

  const restoreOriginalPresentation = (element) => {
    const originalDir = element.dataset.rtlp6OriginalDir;
    if (originalDir && originalDir !== MISSING_PRESENTATION_VALUE) {
      element.setAttribute("dir", originalDir);
    } else {
      element.removeAttribute("dir");
    }

    const originalUnicodeBidi = element.dataset.rtlp6OriginalUnicodeBidi;
    element.style.unicodeBidi =
      originalUnicodeBidi && originalUnicodeBidi !== MISSING_PRESENTATION_VALUE
        ? originalUnicodeBidi
        : "";

    const originalTextAlign = element.dataset.rtlp6OriginalTextAlign;
    element.style.textAlign =
      originalTextAlign && originalTextAlign !== MISSING_PRESENTATION_VALUE
        ? originalTextAlign
        : "";

    const originalWidth = element.dataset.rtlp6OriginalWidth;
    element.style.width =
      originalWidth && originalWidth !== MISSING_PRESENTATION_VALUE
        ? originalWidth
        : "";

    const originalFlex = element.dataset.rtlp6OriginalFlex;
    element.style.flex =
      originalFlex && originalFlex !== MISSING_PRESENTATION_VALUE
        ? originalFlex
        : "";

    delete element.dataset.rtlp6;
    delete element.dataset.rtlp6OriginalDir;
    delete element.dataset.rtlp6OriginalUnicodeBidi;
    delete element.dataset.rtlp6OriginalTextAlign;
    delete element.dataset.rtlp6OriginalWidth;
    delete element.dataset.rtlp6OriginalFlex;
  };

  const applyTextDirection = (element) => {
    if (shouldSkipElement(element)) return;

    preserveOriginalPresentation(element);

    if (containsArabicCharacters(element.textContent)) {
      element.setAttribute("dir", "rtl");
    } else {
      element.setAttribute("dir", "ltr");
    }

    element.style.unicodeBidi = "isolate";
    element.style.textAlign = "start";

    if (isPermissionPromptTextElement(element)) {
      element.style.width = "100%";
      element.style.flex = "1 1 auto";
    }
  };

  const apply = () => {
    if (window.__rtlProStop) return;

    const chatScope =
      document.querySelector('[class*="react-scroll-to-bottom"]') ||
      document.body;

    const textElements = [
      ...chatScope.querySelectorAll(CHAT_TEXT_SELECTOR),
      ...document.querySelectorAll(PERMISSION_PROMPT_TEXT_SELECTOR),
    ];

    [...new Set(textElements)].forEach(applyTextDirection);
  };

  const obs = new MutationObserver((mutations) => {
    if (window.__rtlProStop) return;

    mutations.forEach((m) => {
      m.addedNodes.forEach(apply);
    });
  });

  obs.observe(document.body, { childList: true, subtree: true });
  apply();

  const stop = () => {
    window.__rtlProStop = true;
    obs.disconnect();

    document.querySelectorAll("[data-rtlp6]").forEach((e) => {
      restoreOriginalPresentation(e);
    });

    console.log("RTL-Pro v6 stopped");
  };

  window.RTL_PRO6 = {
    apply,
    stop,
    toggle: () => {
      if (window.__rtlProStop) {
        window.__rtlProStop = false;
        obs.observe(document.body, { childList: true, subtree: true });
        apply();
      } else {
        stop();
      }
    },
  };

  console.log("RTL-Pro v6 (isolate edition) installed");
})();
"""

CHAT_SAVER_JS = f"""
(() => {{
    const USER_MESSAGE_STYLE_ELEMENT_ID = "nad3rUserMessageStyle";
    const USER_MESSAGE_SELECTOR = '[data-content-search-unit-key$=":user"]';
    const USER_MESSAGE_INNER_BUBBLE_SELECTOR =
        `${{USER_MESSAGE_SELECTOR}} [class*="bg-token-foreground"]`;
    const USER_MESSAGE_BACKGROUND_COLOR = "rgba(126, 87, 194, 0.18)";
    const USER_MESSAGE_BORDER_RADIUS = "8px";

    const removeUserMessageStyle = () => {{
        document.getElementById(USER_MESSAGE_STYLE_ELEMENT_ID)?.remove();
    }};

    const installUserMessageStyle = () => {{
        removeUserMessageStyle();

        const styleElement = document.createElement("style");
        styleElement.id = USER_MESSAGE_STYLE_ELEMENT_ID;
        styleElement.textContent =
            `${{USER_MESSAGE_SELECTOR}} {{\n` +
            `    background-color: ${{USER_MESSAGE_BACKGROUND_COLOR}} !important;\n` +
            `    border-radius: ${{USER_MESSAGE_BORDER_RADIUS}} !important;\n` +
            `}}\n` +
            `${{USER_MESSAGE_INNER_BUBBLE_SELECTOR}} {{\n` +
            `    background-color: transparent !important;\n` +
            `}}\n`;
        document.head.append(styleElement);
    }};

    const clearSavedMarkers = () => {{
        document.querySelectorAll("[data-nad3r-saved]").forEach((el) => {{
            delete el.dataset.nad3rSaved;
            el.style.transition = "";
            el.style.backgroundColor = "";
            el.style.borderRight = "";
        }});
    }};

    if (window.__nad3rTools?.observer) {{
        window.__nad3rTools.observer.disconnect();
    }}
    clearSavedMarkers();
    document.getElementById("nad3rScrollUpBtn")?.remove();
    document.getElementById("nad3rScrollDownBtn")?.remove();
    document.getElementById("nad3rControlBar")?.remove();
    removeUserMessageStyle();
    delete window.__nad3rTools;
    installUserMessageStyle();

    window.__nad3rTools = {{
        messages: new Map(),
        isRecording: false,
        triggerSave: false,
        triggerExit: false,
        msgCount: 0,
        speed: {SCROLL_DELTA},
        observer: null,
        activeScrollDirection: 0,
        scrollStepDirection: 0
    }};

    const getContainer = () => {{
        const el = document.querySelector('[data-content-search-unit-key]');
        if (!el) return window;
        let p = el.parentElement;
        while(p && p !== document.body) {{
            const style = window.getComputedStyle(p);
            if(style.overflowY === 'auto' || style.overflowY === 'scroll') return p;
            p = p.parentElement;
        }}
        return window;
    }};

    const stopContinuousScroll = () => {{
        window.__nad3rTools.activeScrollDirection = 0;
        window.__nad3rTools.scrollStepDirection = 0;
    }};

    const bindScrollButton = (button, direction) => {{
        let holdTimerId = null;
        let isContinuousScrollStarted = false;

        const clearHoldTimer = () => {{
            if (holdTimerId !== null) {{
                clearTimeout(holdTimerId);
                holdTimerId = null;
            }}
        }};

        button.onpointerdown = (event) => {{
            event.preventDefault();
            isContinuousScrollStarted = false;
            button.setPointerCapture?.(event.pointerId);
            holdTimerId = window.setTimeout(() => {{
                isContinuousScrollStarted = true;
                window.__nad3rTools.activeScrollDirection = direction;
            }}, 180);
        }};

        button.onpointerup = () => {{
            clearHoldTimer();
            if (isContinuousScrollStarted) {{
                stopContinuousScroll();
                isContinuousScrollStarted = false;
                return;
            }}
            window.__nad3rTools.scrollStepDirection = direction;
        }};

        button.onpointercancel = () => {{
            clearHoldTimer();
            if (isContinuousScrollStarted) {{
                stopContinuousScroll();
                isContinuousScrollStarted = false;
            }}
        }};
    }};

    const observer = new MutationObserver(() => {{
        if (!window.__nad3rTools.isRecording) return;
        let added = false;
        document.querySelectorAll('[data-content-search-unit-key]').forEach(el => {{
            const id = el.getAttribute('data-content-search-unit-key');
            if (!window.__nad3rTools.messages.has(id)) {{
                window.__nad3rTools.messages.set(id, el.innerText.trim());
                added = true;
            }}
            if (window.__nad3rTools.messages.has(id) && !el.dataset.nad3rSaved) {{
                el.dataset.nad3rSaved = "true";
                el.style.transition = "background-color 0.4s";
                el.style.backgroundColor = "rgba(30, 193, 30, 0.1)";
                el.style.borderRight = "3px solid #1ec11e";
            }}
        }});
        if (added) window.__nad3rTools.msgCount = window.__nad3rTools.messages.size;
    }});
    observer.observe(document.body, {{ childList: true, subtree: true }});
    window.__nad3rTools.observer = observer;

    const controlBar = document.createElement("div");
    controlBar.id = "nad3rControlBar";
    Object.assign(controlBar.style, {{
        position: "fixed", bottom: "6px", right: "60px", zIndex: 1000000,
        display: "flex", gap: "6px", background: "rgba(0,0,0,0.85)",
        alignItems: "center", padding: "4px 6px", borderRadius: "8px", border: "1px solid #444"
    }});

    const btnScrollUp = document.createElement("button");
    btnScrollUp.id = "nad3rScrollUpBtn";
    btnScrollUp.textContent = "▲";
    Object.assign(btnScrollUp.style, {{
        position: "fixed", top: "34px", right: "2px", zIndex: 1000001,
        background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.92)",
        border: "1px solid rgba(255,255,255,0.16)", padding: "6px 10px",
        borderRadius: "999px", cursor: "pointer", fontWeight: "bold",
        fontSize: "12px", lineHeight: "1.2", backdropFilter: "blur(8px)",
        boxShadow: "0 4px 12px rgba(0,0,0,0.18)"
    }});
    bindScrollButton(btnScrollUp, -1);

    const btnScrollDown = document.createElement("button");
    btnScrollDown.id = "nad3rScrollDownBtn";
    btnScrollDown.textContent = "▼";
    Object.assign(btnScrollDown.style, {{
        position: "fixed", bottom: "0px", right: "2px", zIndex: 1000001,
        background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.92)",
        border: "1px solid rgba(255,255,255,0.16)", padding: "6px 10px",
        borderRadius: "999px", cursor: "pointer", fontWeight: "bold",
        fontSize: "12px", lineHeight: "1.2", backdropFilter: "blur(8px)",
        boxShadow: "0 4px 12px rgba(0,0,0,0.18)"
    }});
    bindScrollButton(btnScrollDown, 1);

    const btnRtl = document.createElement("button");
    btnRtl.id = "nad3rRtlToggleBtn";
    btnRtl.textContent = "RTL";
    Object.assign(btnRtl.style, {{ color: "white", border: "none", padding: "6px 10px", borderRadius: "6px", cursor: "pointer", fontWeight: "bold", fontSize: "13px", lineHeight: "1.2" }});

    const updateRtlButton = () => {{
        btnRtl.style.background = window.__rtlProStop ? "#f33" : "#1ec11e";
    }};

    btnRtl.onclick = () => {{
        window.RTL_PRO6.toggle();
        updateRtlButton();
    }};
    updateRtlButton();

    const btnSave = document.createElement("button");
    btnSave.id = "nad3rSaveBtn";
    btnSave.textContent = "▶ Record";
    Object.assign(btnSave.style, {{ background: "#007acc", color: "white", border: "none", padding: "6px 10px", borderRadius: "6px", cursor: "pointer", fontWeight: "bold", fontSize: "13px", lineHeight: "1.2" }});
    btnSave.onclick = () => {{
        if (!window.__nad3rTools.isRecording) {{
            window.__nad3rTools.isRecording = true;
            btnSave.textContent = "💾 Save";
            btnSave.style.background = "#1ec11e";
        }} else {{
            window.__nad3rTools.triggerSave = true;
            btnSave.textContent = "⏳ Saving";
            btnSave.style.background = "#555";
        }}
    }};

    const btnExit = document.createElement("button");
    btnExit.textContent = "Exit";
    Object.assign(btnExit.style, {{ background: "#f33", color: "white", border: "none", padding: "6px 10px", borderRadius: "6px", cursor: "pointer", fontWeight: "bold", fontSize: "13px", lineHeight: "1.2" }});
    btnExit.onclick = () => {{
        stopContinuousScroll();
        window.__nad3rTools.isRecording = false;
        window.__nad3rTools.observer?.disconnect();
        clearSavedMarkers();
        if (window.RTL_PRO6 && typeof window.RTL_PRO6.stop === "function") {{
            window.RTL_PRO6.stop();
        }}
        document.getElementById("nad3rRtlToggleBtn")?.remove();
        document.getElementById("nad3rScrollUpBtn")?.remove();
        document.getElementById("nad3rScrollDownBtn")?.remove();
        document.getElementById("nad3rControlBar")?.remove();
        removeUserMessageStyle();
        window.__nad3rTools.triggerExit = true;
    }};

    controlBar.append(btnRtl);
    controlBar.append(btnSave, btnExit);
    document.body.append(controlBar);
    document.body.append(btnScrollUp, btnScrollDown);
}})();
"""


def create_websocket_connection(websocket_url: str) -> Any:
    return websocket.create_connection(websocket_url)


def fetch_debugger_targets() -> list[dict[str, Any]]:
    response = requests.get(f"{DEBUGGER_BASE_URL}/json", timeout=3)
    response.raise_for_status()

    debugger_targets = response.json()
    if not isinstance(debugger_targets, list):
        raise RuntimeError("Debugger target list is not a list.")

    return debugger_targets


def find_single_webview_target() -> dict[str, Any]:
    targets = [
        target
        for target in fetch_debugger_targets()
        if target["type"] in ("iframe", "page")
        and target["url"].startswith("vscode-webview://")
        and "/index.html" in target["url"]
    ]

    if not targets:
        raise RuntimeError("No matching VS Code webview target was found.")

    return targets[0]


def send_devtools_command(
    websocket_connection: Any,
    command_id: int,
    method_name: str,
    params: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {"id": command_id, "method": method_name}

    if params:
        payload["params"] = params

    websocket_connection.send(json.dumps(payload))


def receive_devtools_result(websocket_connection: Any, expected_command_id: int) -> dict[str, Any]:
    while True:
        response = json.loads(websocket_connection.recv())
        if response.get("id") == expected_command_id:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response["result"]


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
  const tools = window.__nad3rTools;
  let scrollContainer = null;
  const firstMessageElement = document.querySelector('[data-content-search-unit-key]');

  if (firstMessageElement) {
    let currentElement = firstMessageElement.parentElement;
    while (currentElement && currentElement !== document.body) {
      const style = window.getComputedStyle(currentElement);
      const isScrollable =
        (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
        currentElement.scrollHeight > currentElement.clientHeight;

      if (isScrollable) {
        scrollContainer = currentElement;
        break;
      }

      currentElement = currentElement.parentElement;
    }
  }

  if (!scrollContainer) {
    scrollContainer =
      [...document.querySelectorAll('div')].find((element) => {
        const style = window.getComputedStyle(element);
        return (
          (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
          element.scrollHeight > element.clientHeight
        );
      }) || null;
  }

  const scrollStepDirection = tools?.scrollStepDirection || 0;
  if (tools) {
    tools.scrollStepDirection = 0;
  }

  if (!scrollContainer) {
    return {
      msgCount: tools?.msgCount || 0,
      triggerSave: Boolean(tools?.triggerSave),
      triggerExit: Boolean(tools?.triggerExit),
      hasControlBar: Boolean(document.getElementById('nad3rControlBar')),
      activeScrollDirection: tools?.activeScrollDirection || 0,
      scrollStepDirection,
      scrollX: null,
      scrollY: null,
    };
  }

  const rect = scrollContainer.getBoundingClientRect();
  return {
    msgCount: tools?.msgCount || 0,
    triggerSave: Boolean(tools?.triggerSave),
    triggerExit: Boolean(tools?.triggerExit),
    hasControlBar: Boolean(document.getElementById('nad3rControlBar')),
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


def install_original_rtl_extension(target: dict[str, Any]) -> None:
    websocket_connection = create_websocket_connection(target["webSocketDebuggerUrl"])

    try:
        websocket_connection.settimeout(3)
        send_devtools_command(websocket_connection, 1, "Runtime.enable")
        send_devtools_command(websocket_connection, 2, "Page.enable")
        send_devtools_command(websocket_connection, 3, "Page.reload")

        deadline = time.time() + 5
        main_context_id: int | None = None

        while time.time() < deadline:
            response = json.loads(websocket_connection.recv())
            if response.get("method") == "Runtime.executionContextCreated":
                context = response["params"]["context"]
                aux_data = context.get("auxData", {})
                if aux_data.get("isDefault") and aux_data.get("frameId"):
                    main_context_id = context["id"]
                    break

        if main_context_id is None:
            raise RuntimeError("No main context")

        send_devtools_command(
            websocket_connection,
            4,
            "Runtime.evaluate",
            {"expression": RTL_FIX, "contextId": main_context_id},
        )
        receive_devtools_result(websocket_connection, 4)
    finally:
        websocket_connection.close()


def save_chat_messages_to_file(raw_data: Any) -> None:
    if not raw_data:
        return

    messages = json.loads(raw_data)
    os.makedirs(CHAT_SAVER_OUTPUT_FILE_PATH.parent, exist_ok=True)
    with open(CHAT_SAVER_OUTPUT_FILE_PATH, "w", encoding="utf-8") as output_file:
        output_file.write("\n\n" + "=" * 50 + "\n\n".join(messages))

    print(f"[Success] Saved {len(messages)} messages.")


def run_original_chat_saver_extension(target: dict[str, Any]) -> None:
    print("[System] Starting Combined Tools (Scroller + Saver)...")
    websocket_connection = create_websocket_connection(target["webSocketDebuggerUrl"])

    try:
        send_devtools_command(websocket_connection, 1, "Runtime.enable")

        context_id: int | None = None
        deadline = time.time() + 5

        while time.time() < deadline:
            response = json.loads(websocket_connection.recv())
            if response.get("method") == "Runtime.executionContextCreated":
                context = response["params"]["context"]
                if context.get("auxData", {}).get("isDefault"):
                    context_id = context["id"]
                    break

        if context_id is None:
            raise RuntimeError("No default execution context was found.")

        evaluate_in_execution_context(websocket_connection, context_id, CHAT_SAVER_JS)
        print("[System] Interface Ready!")

        last_count = 0
        polling_context_id: int | None = context_id

        while True:
            state = read_extension_state(websocket_connection, context_id)
            current_count = state.get("msgCount")
            if current_count and current_count > last_count:
                print(f"[Monitor] Captured {current_count} messages...")
                last_count = current_count

            scroll_x = state.get("scrollX")
            scroll_y = state.get("scrollY")
            scroll_step_direction = state.get("scrollStepDirection")
            active_scroll_direction = state.get("activeScrollDirection")

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
                dispatch_mouse_wheel_scroll(
                    websocket_connection,
                    scroll_x,
                    scroll_y,
                    SCROLL_DELTA * active_scroll_direction,
                )

            if state.get("triggerSave"):
                raw_data = evaluate_in_execution_context(
                    websocket_connection,
                    polling_context_id,
                    "JSON.stringify(Array.from(window.__nad3rTools.messages.values()))",
                )
                save_chat_messages_to_file(raw_data)
                evaluate_in_execution_context(
                    websocket_connection,
                    polling_context_id,
                    "window.__nad3rTools.triggerSave = false; "
                    "window.__nad3rTools.isRecording = false; "
                    "document.querySelectorAll('[data-nad3r-saved]').forEach((el) => { "
                    "delete el.dataset.nad3rSaved; "
                    "el.style.transition = ''; "
                    "el.style.backgroundColor = ''; "
                    "el.style.borderRight = ''; "
                    "}); "
                    "document.getElementById('nad3rSaveBtn').textContent = '▶ Record'; "
                    "document.getElementById('nad3rSaveBtn').style.background = '#007acc';",
                )

            if state.get("triggerExit"):
                evaluate_in_execution_context(
                    websocket_connection,
                    polling_context_id,
                    "if (window.RTL_PRO6 && typeof window.RTL_PRO6.stop === 'function') { "
                    "window.RTL_PRO6.stop(); "
                    "} "
                    "window.__nad3rTools?.observer?.disconnect(); "
                    "document.querySelectorAll('[data-nad3r-saved]').forEach((el) => { "
                    "delete el.dataset.nad3rSaved; "
                    "el.style.transition = ''; "
                    "el.style.backgroundColor = ''; "
                    "el.style.borderRight = ''; "
                    "}); "
                    "document.getElementById('nad3rRtlToggleBtn')?.remove(); "
                    "document.getElementById('nad3rScrollUpBtn')?.remove(); "
                    "document.getElementById('nad3rScrollDownBtn')?.remove(); "
                    "document.getElementById('nad3rControlBar')?.remove(); "
                    "document.getElementById('nad3rUserMessageStyle')?.remove(); "
                    "delete window.RTL_PRO6; "
                    "delete window.__rtlProStop; "
                    "delete window.__rtlPro6; "
                    "delete window.__nad3rTools;",
                )
                break

            if not state.get("hasControlBar"):
                break

            if active_scroll_direction:
                time.sleep(POLL_INTERVAL_SECONDS / 2)
            else:
                time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n[System] Interrupted.")
    finally:
        websocket_connection.close()
        print("[System] Terminated.")


def main() -> None:
    while True:
        try:
            target = find_single_webview_target()
            break
        except Exception:
            time.sleep(5)
    print("[System] Running original RTL extension...")
    install_original_rtl_extension(target)
    print("[System] Running original chat saver extension...")
    run_original_chat_saver_extension(target)


if __name__ == "__main__":
    main()
