import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = readFileSync(
  path.join(root, "app", "components", "Markdown.tsx"),
  "utf8",
);
const marker = "remarkPlugins={[[remarkGfm, { singleTilde: false }]]}";
if (!source.includes(marker)) {
  throw new Error("Markdown.tsx does not pass singleTilde: false to remarkGfm");
}

function render(markdown) {
  return renderToStaticMarkup(
    createElement(ReactMarkdown, {
      remarkPlugins: [[remarkGfm, { singleTilde: false }]],
      children: markdown,
    }),
  );
}

const range = render("월~금 10:00~22:00");
if (!range.includes("월~금 10:00~22:00") || range.includes("<del>")) {
  throw new Error(`single tilde was rewritten: ${range}`);
}

const strike = render("~~취소선~~");
if (!strike.includes("<del>취소선</del>")) {
  throw new Error(`double tilde strikethrough missing: ${strike}`);
}

console.log("ok");
