import type {
  HTMLAttributes,
  ReactNode,
  SVGProps,
} from "react";

export function Spinner({
  className,
  ...props
}: Omit<SVGProps<SVGSVGElement>, "aria-hidden">) {
  return (
    <svg
      {...props}
      className={
        className
          ? `feedback-spinner h-4 w-4 shrink-0 ${className}`
          : "feedback-spinner h-4 w-4 shrink-0"
      }
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="3"
        opacity=".2"
      />
      <path
        d="M12 3a9 9 0 0 1 9 9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Shimmer({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { children: ReactNode }) {
  return (
    <span
      {...props}
      className={className ? `status-shimmer ${className}` : "status-shimmer"}
    >
      {children}
    </span>
  );
}
