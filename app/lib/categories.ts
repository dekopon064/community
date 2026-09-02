export type CurationCategoryKey =
  | "housing"
  | "identity"
  | "work"
  | "education"
  | "welfare"
  | "participation"
  | "other";

const CATEGORY_RULES: ReadonlyArray<{
  key: Exclude<CurationCategoryKey, "other">;
  pattern: RegExp;
}> = [
  { key: "housing", pattern: /(주거|주택|임대|부동산|청약|집)/i },
  { key: "identity", pattern: /(비자|체류|외국인|등록|행정)/i },
  { key: "work", pattern: /(일자리|취업|창업|고용|근로)/i },
  { key: "education", pattern: /(교육|학습|진로|역량)/i },
  { key: "welfare", pattern: /(복지|문화|예술|건강|금융|생활)/i },
  { key: "participation", pattern: /(참여|권리|활동|커뮤니티)/i },
];

export function classifyCurationCategory(
  category: string,
): CurationCategoryKey {
  const normalized = category.trim();
  return (
    CATEGORY_RULES.find(({ pattern }) => pattern.test(normalized))?.key ??
    "other"
  );
}

export function categoryGlyphKind(
  category: CurationCategoryKey,
): "housing" | "identity" | "document" {
  if (category === "housing") return "housing";
  if (category === "identity") return "identity";
  return "document";
}
