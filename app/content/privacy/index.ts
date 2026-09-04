import { koPrivacy } from "./ko";
import { jaPrivacy } from "./ja";
import type { PrivacyDoc } from "./types";

export function getPrivacyDocument(locale: string): PrivacyDoc {
  return locale === "ja" ? jaPrivacy : koPrivacy;
}
