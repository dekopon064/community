type NoticeCopy = {
  title: string;
  purposeLabel: string;
  purposes: readonly string[];
  itemsLabel: string;
  items: readonly string[];
  retentionLabel: string;
  retention: readonly string[];
  refusalLabel: string;
  refusal: readonly string[];
};

export default function FeedbackPrivacyNotice({
  legendId,
  copy,
}: {
  legendId: string;
  copy: NoticeCopy;
}) {
  return (
    <div className="rounded-[1.25rem] border border-stone bg-canvas-white px-4 py-5 md:px-5">
      <h3 id={legendId} className="text-base font-bold tracking-[-0.02em] text-ink">
        {copy.title}
      </h3>
      <p className="mt-4 text-sm font-bold text-ink">{copy.purposeLabel}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">
        {copy.purposes.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <p className="mt-4 text-sm font-bold text-ink">{copy.itemsLabel}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">
        {copy.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <p className="mt-4 text-sm font-bold text-ink">{copy.retentionLabel}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">
        {copy.retention.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <p className="mt-4 text-sm font-bold text-ink">{copy.refusalLabel}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">
        {copy.refusal.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
