// Legacy cron compatibility shim.
//
// Standalone browser writes are forbidden. X replies must be represented as
// durable CommentTask drafts and executed by CreatorHub's single worker.

export async function runCronRemindStep(_agent, accountId = null, count = 4) {
  return {
    ok: false,
    disabled: true,
    reason: "legacy_direct_x_write_disabled",
    message: "Use CreatorHub /api/x/reply/draft and the durable task queue.",
    accountId,
    requested: Number.isFinite(Number(count)) ? Number(count) : 0,
    queued: [],
  };
}
