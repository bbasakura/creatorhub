// Legacy compatibility shim.
//
// Direct X writes from standalone runners are disabled. All replies must enter
// CreatorHub's durable reply draft/task queue so account locks, risk gates,
// submit-boundary uncertainty, and audit logging are preserved.

export async function processConcurrentBatch(_agent, tasks = []) {
  return {
    ok: false,
    disabled: true,
    reason: "legacy_direct_x_write_disabled",
    message: "Use CreatorHub /api/x/reply/draft and the durable task queue.",
    received: Array.isArray(tasks) ? tasks.length : 0,
    results: [],
  };
}
