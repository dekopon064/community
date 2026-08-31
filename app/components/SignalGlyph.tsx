type SignalGlyphKind = "housing" | "identity" | "document";

interface SignalGlyphProps {
  kind: SignalGlyphKind;
  className?: string;
  accent?: boolean;
}

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  strokeWidth: 1.8,
};

export default function SignalGlyph({
  kind,
  className = "h-10 w-10",
  accent = false,
}: SignalGlyphProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {kind === "housing" && (
        <>
          <path {...stroke} d="M4.5 11.2 12 4.8l7.5 6.4M7.2 10.4v8h9.6v-8" />
          <circle cx="16.9" cy="17.1" r="1.45" fill={accent ? "#a8564a" : "currentColor"} />
        </>
      )}
      {kind === "identity" && (
        <>
          <path {...stroke} d="M6.4 6.3h9.1c1.2 0 2.1.9 2.1 2.1v7.2c0 1.2-.9 2.1-2.1 2.1H6.4c-1.2 0-2.1-.9-2.1-2.1V8.4c0-1.2.9-2.1 2.1-2.1Z" />
          <path {...stroke} d="M8 14.4c.8-1.2 2-1.8 3.3-1.8s2.5.6 3.3 1.8M11.3 11.4a1.7 1.7 0 1 0 0-3.4" />
          <circle cx="17.8" cy="16.8" r="1.3" fill="currentColor" />
        </>
      )}
      {kind === "document" && (
        <>
          <path {...stroke} d="M7 4.5h6.1l3.9 3.9v9.1A2 2 0 0 1 15 19.5H7a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2Z" />
          <path {...stroke} d="M13 4.8v3.7h3.7M8.7 12h5.4M8.7 15h3.4" />
          <circle cx="17.5" cy="18" r="1.25" fill={accent ? "#a8564a" : "currentColor"} />
        </>
      )}
    </svg>
  );
}
