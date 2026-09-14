import type { ReactNode } from 'react';

export function Spinner({ className = '' }: { className?: string }) {
  return <svg className={`feedback-spinner h-4 w-4 shrink-0 ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity=".2" />
    <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
  </svg>;
}

// Reserved for the 生成進度列's live text.
export function Shimmer({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`status-shimmer ${className}`}>{children}</span>;
}
