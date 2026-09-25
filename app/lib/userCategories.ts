export const USER_CATEGORIES = [
  "policy",
  "program",
  "event",
  "youth_space",
  "living",
] as const;

export type UserCategory = (typeof USER_CATEGORIES)[number];

export function isUserCategory(value: unknown): value is UserCategory {
  return USER_CATEGORIES.some((category) => category === value);
}

export function userCategoryGlyphKind(
  category: UserCategory,
): "housing" | "identity" | "document" {
  if (category === "youth_space") return "housing";
  if (category === "policy") return "identity";
  return "document";
}
