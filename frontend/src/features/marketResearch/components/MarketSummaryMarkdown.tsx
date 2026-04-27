import ReactMarkdown from 'react-markdown';

type Props = { content: string };

/**
 * Renders the backend-generated Market Summary Markdown.
 * Styled with Tailwind utility classes per heading/paragraph — no
 * dependency on @tailwindcss/typography to keep the design consistent
 * with the rest of the app (card look, slate palette).
 */
export function MarketSummaryMarkdown({ content }: Props) {
  return (
    <div className="space-y-4 text-sm text-slate-700 leading-relaxed">
      <ReactMarkdown
        components={{
          h1: ({ children }) => (
            <h2 className="text-base font-semibold text-slate-900 mt-2">{children}</h2>
          ),
          h2: ({ children }) => (
            <h3 className="text-sm font-semibold text-slate-900 mt-4 border-b border-slate-100 pb-1.5">
              {children}
            </h3>
          ),
          h3: ({ children }) => (
            <h4 className="text-sm font-semibold text-slate-800 mt-3">{children}</h4>
          ),
          p: ({ children }) => (
            <p className="text-sm text-slate-600 leading-relaxed">{children}</p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-slate-900">{children}</strong>
          ),
          ul: ({ children }) => (
            <ul className="list-disc ps-5 space-y-1 text-sm text-slate-600">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal ps-5 space-y-1 text-sm text-slate-600">{children}</ol>
          ),
          li: ({ children }) => <li className="text-sm text-slate-600">{children}</li>,
          em: ({ children }) => <em className="italic text-slate-600">{children}</em>,
          code: ({ children }) => (
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">
              {children}
            </code>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-brand-600 hover:text-brand-700 underline underline-offset-2"
            >
              {children}
            </a>
          )
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
