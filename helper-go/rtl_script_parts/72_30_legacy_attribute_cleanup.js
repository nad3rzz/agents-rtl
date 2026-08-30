  document.querySelectorAll("[data-agents-rtl-composer-dry],[data-agents-rtl-composer-content-dry],[data-agents-rtl-composer-editor-dry],[data-agents-rtl-native-composer-dry],[data-agents-rtl-native-composer-dry2],[data-agents-rtl-dry-steered],[data-agents-rtl-dry-steered-child],[data-agents-rtl-table-dry]").forEach((element) => {
    element.removeAttribute("data-agents-rtl-composer-dry");
    element.removeAttribute("data-agents-rtl-composer-content-dry");
    element.removeAttribute("data-agents-rtl-composer-editor-dry");
    element.removeAttribute("data-agents-rtl-native-composer-dry");
    element.removeAttribute("data-agents-rtl-native-composer-dry2");
    element.removeAttribute("data-agents-rtl-dry-steered");
    element.removeAttribute("data-agents-rtl-dry-steered-child");
    element.removeAttribute("data-agents-rtl-table-dry");
    element.removeAttribute("dir");
    element.style.removeProperty("direction");
    element.style.removeProperty("text-align");
    element.style.removeProperty("unicode-bidi");
  });
  document.querySelectorAll("[data-agents-rtl-table-wrap-dry],[" + TABLE_WRAPPER_ATTRIBUTE_NAME + "],[" + MESSAGE_BUBBLE_ATTRIBUTE_NAME + "]").forEach((element) => {
    element.removeAttribute("data-agents-rtl-table-wrap-dry");
    element.removeAttribute(TABLE_WRAPPER_ATTRIBUTE_NAME);
    element.removeAttribute(MESSAGE_BUBBLE_ATTRIBUTE_NAME);
  });
