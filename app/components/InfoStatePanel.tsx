import type { ReactNode } from "react";
import SignalGlyph from "@/app/components/SignalGlyph";

interface InfoStatePanelProps {
  title: string;
  description: string;
  children?: ReactNode;
  role?: "alert" | "status";
  headingLevel?: 1 | 2;
}

export default function InfoStatePanel({
  title,
  description,
  children,
  role,
  headingLevel = 1,
}: InfoStatePanelProps) {
  const Heading = headingLevel === 2 ? "h2" : "h1";

  return (
    <section
      role={role}
      className="rounded-[1.5rem] border border-stone bg-canvas-white px-6 py-10 text-center md:px-10 md:py-14"
    >
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-mineral text-ink">
        <SignalGlyph kind="document" accent className="h-9 w-9" />
      </div>
      <Heading className="mx-auto mt-5 max-w-xl text-2xl font-bold leading-tight tracking-[-0.035em] text-ink md:text-3xl">
        {title}
      </Heading>
      <p className="mx-auto mt-3 max-w-lg text-sm leading-7 text-ink-sub md:text-base">
        {description}
      </p>
      {children && (
        <div className="mt-7 flex flex-wrap justify-center gap-3">{children}</div>
      )}
    </section>
  );
}
