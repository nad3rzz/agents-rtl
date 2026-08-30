  const USER_MESSAGE_SELECTOR = "[data-content-search-unit-key$=':user']";
  const USER_MESSAGE_INNER_BUBBLE_SELECTOR = USER_MESSAGE_SELECTOR + " [class*='bg-token-foreground']";
  const WEBVIEW_CONTROL_FOOTER_SELECTOR = [
    ".composer-footer",
    "div[class*='_footer_']",
    "[data-composer-footer-responsive]",
  ].join(",");
  const PLAIN_TEXT_CODE_BLOCK_LANGUAGE_LABELS = new Set(["txt", "text", "plaintext"]);
  const PLAIN_TEXT_CODE_BLOCK_SELECTOR = [
    "div.text-size-chat.overflow-y-auto.p-2",
    "div.text-size-chat.overflow-auto.p-2",
  ].join(",");
  const PERMISSION_PROMPT_CARD_SELECTOR = [
    "[class*='rounded-3xl']:has([role='radiogroup'])",
    "[class*='rounded-3xl']:has(form):has([class*='font-mono'])",
  ].join(",");
  const PERMISSION_PROMPT_TEXT_SELECTOR = [
    PERMISSION_PROMPT_CARD_SELECTOR + " .text-base.font-medium",
    PERMISSION_PROMPT_CARD_SELECTOR + " [class*='text-base'][class*='font-medium']",
    PERMISSION_PROMPT_CARD_SELECTOR + " [class*='text-size-chat'][class*='font-medium'][class*='text-token-foreground']",
  ].join(",");
  const CODEX_RESPONSE_ANNOTATION_TEXT_SELECTOR =
    "li[class*='response-annotation'] .break-words.whitespace-pre-wrap";
  const CODEX_TRANSIENT_ANNOTATION_CONTENT_SELECTOR = [
    "[role='tooltip']",
    "[data-radix-tooltip-content]",
    "[data-slot='popover-content']",
  ].join(",");
  const CODEX_TRANSIENT_ANNOTATION_LABELS = new Set(["selected text:", "user comment:"]);
  const WEBVIEW_CHAT_TEXT_SELECTOR = [
    "p",
    "li",
    "blockquote",
    "ol",
    "ul",
    ".text-size-chat.whitespace-pre-wrap",
    "[data-content-search-unit-key$=':user'] .text-size-chat.whitespace-pre-wrap",
    "[data-content-search-unit-key$=':assistant'] [class*='_markdownContent_']",
    PERMISSION_PROMPT_TEXT_SELECTOR,
    PLAIN_TEXT_CODE_BLOCK_SELECTOR,
  ].join(",");
