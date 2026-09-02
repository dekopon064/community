import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// B 셸의 읽기 화면에 맞춘 마크다운 요소 스타일.
const components: Components = {
  h1: (props) => (
    <h1
      className="mt-10 mb-4 break-words text-2xl font-bold leading-tight tracking-[-0.035em] text-ink"
      {...props}
    />
  ),
  h2: (props) => (
    <h2
      className="mt-10 mb-4 break-words text-xl font-bold leading-snug tracking-[-0.03em] text-ink md:text-2xl"
      {...props}
    />
  ),
  h3: (props) => (
    <h3
      className="mt-7 mb-3 break-words text-lg font-bold leading-snug text-ink"
      {...props}
    />
  ),
  p: (props) => (
    <p
      className="my-4 break-words text-base leading-8 text-ink"
      {...props}
    />
  ),
  ul: (props) => (
    <ul
      className="my-4 list-disc space-y-2 pl-5 text-base text-ink marker:text-coral"
      {...props}
    />
  ),
  ol: (props) => (
    <ol
      className="my-4 list-decimal space-y-2 pl-5 text-base text-ink marker:font-bold marker:text-coral"
      {...props}
    />
  ),
  li: (props) => <li className="break-words leading-8" {...props} />,
  strong: (props) => <strong className="font-bold text-ink" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  a: (props) => (
    <a
      className="break-words font-bold text-ink underline decoration-focus decoration-1 underline-offset-4 hover:text-focus"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  blockquote: (props) => (
    <blockquote
      className="my-6 border-l border-stone pl-5 text-base italic leading-8 text-ink-sub"
      {...props}
    />
  ),
  hr: (props) => <hr className="my-9 border-stone" {...props} />,
  code: (props) => (
    <code
      className="rounded bg-canvas px-1.5 py-0.5 font-mono text-[0.85em] text-ink"
      {...props}
    />
  ),
  pre: (props) => (
    <pre
      className="my-5 overflow-x-auto rounded-xl bg-ink p-4 text-xs leading-6 text-canvas-white [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-canvas-white"
      {...props}
    />
  ),
  table: (props) => (
    <div className="my-5 overflow-x-auto rounded-xl border border-stone">
      <table
        className="w-full border-collapse text-sm text-ink [&_td]:border-b [&_td]:border-stone [&_td]:px-3 [&_td]:py-3 [&_th]:border-b [&_th]:border-stone [&_th]:bg-mineral [&_th]:px-3 [&_th]:py-3 [&_th]:text-left [&_th]:font-bold"
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
