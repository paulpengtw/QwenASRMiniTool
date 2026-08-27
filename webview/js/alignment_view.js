/* alignment_view.js — Pure UI-variant logic for alignment capability (ticket 07).
 *
 * Given a status.alignment snapshot from the backend, computes which UI
 * controls to render.  No DOM access; returns plain objects so the caller
 * can apply them however it likes (webview, tests, etc.).
 *
 * API
 * ---
 *   AlignmentView.fromStatus(alignment) -> ViewDescriptor
 *
 * ViewDescriptor shape
 * --------------------
 * {
 *   showToggle     : bool   // true = render normal 時間軸對齊 toggle
 *   showChip       : bool   // true = render read-only proportional chip
 *   chipLabel      : str    // e.g. "字級時間軸：比例估算 ⓘ"
 *   chipTooltip    : str    // tooltip / title
 *   showBadge      : bool   // true = karaoke view shows "≈ 估算" badge
 *   chunkDisabled  : bool   // true = chunk-length setting shown disabled
 *   chunkReason    : str    // reason message for disabled chunk setting
 *   faInUnsupported: bool   // true = FA system check is in collapsed group
 *   statusLine     : str    // stable status line text
 *   method         : str    // "exact" | "proportional"
 *   state          : str    // "ready" | "setup_required" | "platform_unsupported"
 * }
 */
(function () {
  "use strict";

  var CHIP_LABEL   = "字級時間軸：比例估算 ⓘ";
  var CHIP_TOOLTIP = "精確字級對齊僅支援 Windows（chatllm ForcedAligner）。Ubuntu 使用比例估算。";
  var CHUNK_REASON = "精確字級對齊在 Ubuntu 不可用；設定值已保留，切換至 Windows 時生效。";
  var STATUS_LINE  = "精確字級對齊在 Ubuntu 不可用 · Windows 設定已保留";

  /**
   * Derive a ViewDescriptor from an alignment capability snapshot.
   *
   * @param {object} alignment  The status.alignment dict from the backend:
   *   { method: "exact"|"proportional",
   *     state:  "ready"|"setup_required"|"platform_unsupported",
   *     reason: { code: string, params: object } }
   * @returns {object} ViewDescriptor
   */
  function fromStatus(alignment) {
    alignment = alignment || {};
    var method = alignment.method || "proportional";
    var state  = alignment.state  || "platform_unsupported";

    var isPlatformUnsupported = (method === "proportional" && state === "platform_unsupported");

    if (isPlatformUnsupported) {
      return {
        showToggle     : false,
        showChip       : true,
        chipLabel      : CHIP_LABEL,
        chipTooltip    : CHIP_TOOLTIP,
        showBadge      : true,
        chunkDisabled  : true,
        chunkReason    : CHUNK_REASON,
        faInUnsupported: true,
        statusLine     : STATUS_LINE,
        method         : method,
        state          : state,
      };
    }

    // Windows / exact path — normal UI
    return {
      showToggle     : true,
      showChip       : false,
      chipLabel      : "",
      chipTooltip    : "",
      showBadge      : false,
      chunkDisabled  : false,
      chunkReason    : "",
      faInUnsupported: false,
      statusLine     : "",
      method         : method,
      state          : state,
    };
  }

  var AlignmentView = { fromStatus: fromStatus };
  if (typeof module !== "undefined") module.exports = AlignmentView;
  else window.AlignmentView = AlignmentView;
})();
