// Codex calls its right-hand MCP App tab "fullscreen" in the standard protocol.
// A standalone global app surface advertises only "inline"; it is already a
// dedicated workspace. A conversation supports both modes and gets a small card.
export function presentationFor(context = {}) {
  const modes = context.availableDisplayModes || [];
  const standalone = modes.length === 1 && modes[0] === "inline";
  return context.displayMode === "fullscreen" || standalone ? "workspace" : "card";
}

export function safeAreaFor(context = {}) {
  const insets = context.safeAreaInsets || {};
  return Object.fromEntries(["top", "right", "bottom", "left"].map((edge) => {
    const value = Number(insets[edge]);
    return [edge, Number.isFinite(value) ? Math.max(0, value) : 0];
  }));
}
