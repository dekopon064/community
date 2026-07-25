import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// 디자인 토큰(ink/canvas/stone) 기반 마크다운 요소 스타일.
// 액센트(turquoise)는 CTA 전용이므로 링크에는 사용하지 않고 밑줄+볼드로 구분.
const components: Components = {
  h1: (props) => (
    <h1 className="mt-6 mb-3 text-xl font-black text-ink" {...props} />
  ),
  h2: (props) => (
    <h2 className="mt-6 mb-2 text-lg font-extrabold text-ink" {...props} />
  ),
  h3: (props) => (
    <h3 className="mt-4 mb-2 text-base font-bold text-ink" {...props} />
  ),
  p: (props) => (
    <p className="my-3 text-sm leading-loose text-ink" {...props} />
  ),
  ul: (props) => (
    <ul className="my-3 list-disc space-y-1 pl-5 text-sm text-ink" {...props} />
  ),
  ol: (props) => (
    <ol
      className="my-3 list-decimal space-y-1 pl-5 text-sm text-ink"
      {...props}
    />
  ),
  li: (props) => <li className="leading-relaxed" {...props} />,
  strong: (props) => <strong className="font-bold text-ink" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  a: (props) => (
    <a
      className="font-bold text-ink underline underline-offset-2"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  blockquote: (props) => (
    <blockquote
      className="my-3 border-l-2 border-stone pl-4 text-sm italic text-ink-sub"
      {...props}
    />
  ),
  hr: (props) => <hr className="my-6 border-stone" {...props} />,
  code: (props) => (
    <code
      className="rounded bg-canvas px-1.5 py-0.5 font-mono text-[0.85em] text-ink"
      {...props}
    />
  ),
  pre: (props) => (
    <pre
      className="my-3 overflow-x-auto rounded-xl bg-ink p-4 text-xs text-canvas-white [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-canvas-white"
      {...props}
    />
  ),
  table: (props) => (
    <div className="my-3 overflow-x-auto">
      <table
        className="w-full border-collapse text-sm text-ink [&_td]:border [&_td]:border-stone [&_td]:px-3 [&_td]:py-2 [&_th]:border [&_th]:border-stone [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-bold"
        {...props}
      />
    </div>
  ),
};

export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </ReactMarkdown>
  );
}
