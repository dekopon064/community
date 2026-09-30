import Markdown from "@/app/components/Markdown";
import { parseCurationBodySections } from "@/app/lib/curationBodySections";

export default function CurationBody({
  content,
  locale,
}: {
  content: string;
  locale: string;
}) {
  const parsed = parseCurationBodySections(content, locale);
  if (!parsed) return <Markdown>{content}</Markdown>;

  return (
    <div>
      {parsed.introduction && (
        <div className="pb-6 [&>p:first-child]:mt-0">
          <Markdown>{parsed.introduction}</Markdown>
        </div>
      )}
      {parsed.sections.map(({ heading, body }, index) => (
        <section
          key={heading}
          className={`py-6 first:pt-0 last:pb-0 ${
            index > 0 || parsed.introduction ? "border-t border-stone" : ""
          }`}
        >
          <h2 className="text-base font-bold leading-7 text-primary-text md:text-lg">
            {heading}
          </h2>
          <div className="mt-2 [&>p:first-child]:mt-0 [&>p:last-child]:mb-0">
            <Markdown>{body}</Markdown>
          </div>
        </section>
      ))}
    </div>
  );
}
