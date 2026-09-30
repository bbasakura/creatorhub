// Legacy compatibility shim.
//
// This module used to send X replies directly from a browser tab. That bypasses
// CreatorHub's account lock, risk controller, durable queue and uncertain-write
// semantics, so the direct writer is intentionally disabled.

export async function remindConfirmedBatchDirect(_agent, count = 4) {
  return {
    ok: false,
    disabled: true,
    reason: "legacy_direct_x_write_disabled",
    message: "Create X reply drafts in CreatorHub and execute them through the durable task queue.",
    requested: Number.isFinite(Number(count)) ? Number(count) : 0,
    processed: 0,
    results: [],
  };
}
