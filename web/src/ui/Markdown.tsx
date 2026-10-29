import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
/** Only https links are followed; anything else (javascript:, data:, http:) is dropped. */
export const safeUrl = (url: string): string => (/^https:\/\//i.test(url) ? url : "");
/** Renders text written by AWS Transform or an agent. Raw HTML is skipped, never rendered. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={safeUrl}
        components={{ a: ({ href, children }) => (href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>) }}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
