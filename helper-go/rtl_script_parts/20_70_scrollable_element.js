	const isScrollableElement = (element) => {
    if (!element || element === document.body) return false;
    const overflowY = getComputedStyle(element).overflowY;
    return /auto|scroll|overlay/.test(overflowY) &&
      element.scrollHeight > element.clientHeight + SCROLL_HEIGHT_TOLERANCE_PX;
  };
