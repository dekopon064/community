const SECTION_LABELS = {
  ko: ["한 줄 요약", "대상", "기간·상태", "주요 내용", "신청 방법"],
  ja: ["要約", "対象", "期間・状況", "主な内容", "申請方法"],
} as const;

type BodyLocale = keyof typeof SECTION_LABELS;

export type CurationBodySection = {
  heading: string;
  body: string;
};

export type ParsedCurationBody = {
  introduction: string;
  sections: CurationBodySection[];
};

function sectionAtStart(line: string, labels: readonly string[]) {
  for (const heading of labels) {
    const marker = `[${heading}]`;
    if (line === marker) {
      return { heading, rest: "" };
    }
    if (line.startsWith(marker) && /^[ \t]/.test(line[marker.length] ?? "")) {
      return { heading, rest: line.slice(marker.length).replace(/^[ \t]+/, "") };
    }
  }
  return null;
}

/** Only the known AI section format is reflowed; other Markdown stays untouched. */
export function parseCurationBodySections(
  content: string,
  locale: string,
): ParsedCurationBody | null {
  if (locale !== "ko" && locale !== "ja") return null;
  // A fence can contain literal bracket labels. Keep such documents in the
  // original Markdown renderer instead of interpreting their lines as sections.
  if (/^ {0,3}(?:`{3,}|~{3,})/m.test(content)) return null;

  const labels = SECTION_LABELS[locale as BodyLocale];
  const lines = content.split(/\r\n|\n|\r/);
  const introduction: string[] = [];
  const sections: { heading: string; lines: string[] }[] = [];
  const seen = new Set<string>();

  for (const line of lines) {
    const marker = sectionAtStart(line, labels);
    if (marker) {
      if (seen.has(marker.heading)) return null;
      seen.add(marker.heading);
      sections.push({ heading: marker.heading, lines: [marker.rest] });
    } else if (sections.length > 0) {
      sections[sections.length - 1].lines.push(line);
    } else {
      introduction.push(line);
    }
  }

  // Both required headings distinguish the generated format from an ordinary
  // paragraph that happens to start with a bracketed word.
  const required = locale === "ko" ? ["한 줄 요약", "주요 내용"] : ["要約", "主な内容"];
  if (!required.every((heading) => seen.has(heading))) return null;

  const parsedSections = sections.map(({ heading, lines: sectionLines }) => ({
    heading,
    body: sectionLines.join("\n").trim(),
  }));
  if (parsedSections.some((section) => !section.body)) return null;

  return {
    introduction: introduction.join("\n").trim(),
    sections: parsedSections,
  };
}
