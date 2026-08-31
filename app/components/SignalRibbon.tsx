interface SignalRibbonProps {
  className?: string;
}

export default function SignalRibbon({ className = "" }: SignalRibbonProps) {
  return (
    <svg
      viewBox="0 0 220 38"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="10" cy="23" r="4" fill="currentColor" />
      <circle cx="25" cy="23" r="2.5" fill="currentColor" opacity="0.72" />
      <circle cx="38" cy="23" r="2.5" fill="currentColor" opacity="0.48" />
      <path
        d="M54 23c28-11 43-10 71-4 30 7 51 7 85-8"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="2.5"
        opacity="0.72"
      />
    </svg>
  );
}
