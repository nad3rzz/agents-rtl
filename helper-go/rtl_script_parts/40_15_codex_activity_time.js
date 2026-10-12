  const codexLastReplyDateTimeFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const codexLastReplyRelativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, {
    numeric: "auto",
  });
  const codexConversationLastReplyTimestampMs = (conversation) => {
    const timestampMs = Number(conversation?.activityOccurredAtMs || 0);
    if (!Number.isFinite(timestampMs) || timestampMs < 0) {
      throw new Error("Codex conversation has an invalid last reply timestamp.");
    }
    return timestampMs;
  };
  const codexConversationLastReplyRelativeText = (conversation) => {
    const timestampMs = codexConversationLastReplyTimestampMs(conversation);
    if (timestampMs === 0) return "Unavailable";
    const differenceSeconds = (timestampMs - Date.now()) / 1000;
    const absoluteDifferenceSeconds = Math.abs(differenceSeconds);
    for (const relativeTimeUnit of CODEX_RELATIVE_TIME_UNITS) {
      if (absoluteDifferenceSeconds < relativeTimeUnit.seconds && relativeTimeUnit.unit !== "second") continue;
      const relativeValue = Math.round(differenceSeconds / relativeTimeUnit.seconds);
      return codexLastReplyRelativeTimeFormatter.format(relativeValue, relativeTimeUnit.unit);
    }
    throw new Error("Codex relative time units are empty.");
  };
  const codexConversationLastReplyTooltip = (conversation) => {
    const timestampMs = codexConversationLastReplyTimestampMs(conversation);
    if (timestampMs === 0) return conversation.title + "\nLast reply: unavailable";
    return conversation.title +
      "\nLast reply: " + codexLastReplyDateTimeFormatter.format(new Date(timestampMs)) +
      "\n" + codexConversationLastReplyRelativeText(conversation);
  };
