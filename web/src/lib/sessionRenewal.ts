const DAY_MS = 24 * 60 * 60 * 1_000;

export function shouldRenew(me: {
  session_expires_at: string;
  renewal_threshold_days: number;
  server_time: string;
}): boolean {
  const remaining =
    Date.parse(me.session_expires_at) - Date.parse(me.server_time);
  return remaining < me.renewal_threshold_days * DAY_MS;
}
