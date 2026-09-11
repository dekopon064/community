type MailboxIllustrationProps = {
  className?: string;
};

export default function MailboxIllustration({ className }: MailboxIllustrationProps) {
  return (
    <svg
      viewBox="0 0 240 240"
      fill="none"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M103 146h34v56c0 10-7 17-17 17s-17-7-17-17v-56Z"
        className="fill-ink"
      />
      <path
        d="M38 148V96c0-29 23-52 52-52h83c17 0 31 14 31 31v73H38Z"
        className="fill-canvas-white stroke-ink"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M164 46h9c17 0 31 14 31 31v71h-40V46Z"
        className="fill-mineral stroke-ink"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x="176" y="96" width="17" height="6" rx="3" className="fill-ink" />
      <path
        d="M76 96V31h40v18H92"
        className="stroke-coral"
        strokeWidth="9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx="76"
        cy="96"
        r="7"
        className="fill-canvas-white stroke-coral"
        strokeWidth="5"
      />
      <path
        d="M53 137h99"
        className="stroke-sky"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
