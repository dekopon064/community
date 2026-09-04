export type PrivacyBlock =
  | { type: "p"; text: string }
  | { type: "ul"; items: readonly string[] };

export type PrivacySection = {
  id: string;
  title: string;
  blocks: readonly PrivacyBlock[];
};

export type PrivacyDoc = {
  title: string;
  version: string;
  intro: readonly string[];
  sections: readonly PrivacySection[];
};
