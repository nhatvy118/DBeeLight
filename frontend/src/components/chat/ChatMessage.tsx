import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';
import VegaLiteChart from './VegaLiteChart';

// Tolerate the agent occasionally wrapping the marker block in a markdown
// code fence (it copies the format from its system-prompt example). The
// optional ``` before/after gets eaten alongside the markers so trailing
// markdown text isn't dragged into a phantom code block.
const VEGA_SPEC_RE = /(?:```[a-zA-Z]*\s*\n?)?\[VEGA_SPEC_START\]\s*([\s\S]*?)\s*\[VEGA_SPEC_END\](?:\s*\n?```)?/g;

type MessagePart = { type: 'text'; content: string } | { type: 'chart'; spec: string };

/** Split an assistant message on [VEGA_SPEC_START]…[VEGA_SPEC_END] markers
 * so each chart spec can be rendered as a real <VegaLite> component while
 * surrounding prose still flows through the markdown renderer. */
function splitMessageOnVegaSpecs(message: string): MessagePart[] {
  const parts: MessagePart[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  VEGA_SPEC_RE.lastIndex = 0;
  while ((match = VEGA_SPEC_RE.exec(message)) !== null) {
    if (match.index > lastIdx) {
      parts.push({ type: 'text', content: message.slice(lastIdx, match.index) });
    }
    parts.push({ type: 'chart', spec: match[1].trim() });
    lastIdx = VEGA_SPEC_RE.lastIndex;
  }
  if (lastIdx < message.length) {
    parts.push({ type: 'text', content: message.slice(lastIdx) });
  }
  return parts.length === 0 ? [{ type: 'text', content: message }] : parts;
}

/** While the typing animation is running we don't want to stream the raw
 * Vega-Lite JSON character by character — it's a wall of braces. Replace
 * each spec block with a short placeholder for the typing pass. */
function stripVegaSpecsForTyping(message: string): string {
  return message.replace(VEGA_SPEC_RE, '_[chart rendering…]_');
}


type ChatMessageAttachment = {
  name: string;
  fileId?: string;
};

type ChatMessageProps = {
  message: string;
  isUser: boolean;
  attachments?: ChatMessageAttachment[];
  enableTyping?: boolean;
  onTypingStateChange?: (isTyping: boolean) => void;
  typingStopSignal?: number;
};

function extractCodeText(children: any): string {
  if (typeof children === 'string') return children;

  if (Array.isArray(children)) {
    return children
      .map((child) => {
        if (typeof child === 'string') return child;
        if (child?.props?.children) return child.props.children;
        return '';
      })
      .join('');
  }

  return '';
}

function normalizeInlineCode(text: string): string {
  // Split by triple backticks to protect code blocks
  const parts = text.split(/(```[\s\S]*?```)/g);

  return parts
    .map((part) => {
      // If this part is a code block, return as-is
      if (part.startsWith('```')) {
        return part;
      }

      let p = part;

      // ----- Backtick noise stripping (run BEFORE markdown parses) -----
      // The agent sometimes wraps identifiers in MySQL-style multi-tick
      // patterns or escape sequences. CommonMark would still render them
      // as inline code but with the inner backticks visible inside the
      // chip. Collapse those patterns to a clean single-backtick wrap so
      // markdown produces a chip whose *content* has no backticks.
      //
      // Cases handled (text source → normalized):
      //   ``foo``           →  `foo`
      //   `` `foo` ``       →  `foo`
      //   ``` `foo` ```     →  `foo`
      //   \`foo\`           →  `foo`
      p = p
        .replace(/``\s*`([^`\n]+)`\s*``/g, '`$1`')
        .replace(/```\s*`([^`\n]+)`\s*```/g, '`$1`')
        .replace(/``([^`\n]+)``/g, '`$1`')
        .replace(/\\`([^`\n]+)\\`/g, '`$1`');

      // Fix inline code that is on its own line.
      return p
        // Case 1: newline before and after `code`
        .replace(/\n`([^`\n]+)`\n/g, ' `$1` ')
        // Case 2: newline before `code`
        .replace(/\n`([^`\n]+)`/g, ' `$1`')
        // Case 3: `code` followed by newline
        .replace(/`([^`\n]+)`\n/g, '`$1` ');
    })
    .join('');
}

export default function ChatMessage({
  message,
  isUser,
  attachments,
  enableTyping = true,
  onTypingStateChange,
  typingStopSignal = 0,
}: ChatMessageProps) {
  const [displayedText, setDisplayedText] = useState<string>('');
  const [isTyping, setIsTyping] = useState<boolean>(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentIndexRef = useRef<number>(0);
  const codeBlockIndexRef = useRef<number>(0);
  const lastHandledStopSignalRef = useRef<number>(typingStopSignal);

  useEffect(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    if (isUser || !enableTyping) {
      setDisplayedText(message);
      setIsTyping(false);
      currentIndexRef.current = 0;
      return;
    }

    // AI typing
    setDisplayedText('');
    setIsTyping(true);
    currentIndexRef.current = 0;

    // Don't stream Vega-Lite JSON characters — substitute placeholder so
    // typing UX stays readable until the final render swaps in the chart.
    const typingSource = stripVegaSpecsForTyping(message);
    const tokens = typingSource.split(/(\s+)/).filter((t) => t.length > 0);

    const typeNext = () => {
      if (currentIndexRef.current < tokens.length) {
        setDisplayedText(tokens.slice(0, currentIndexRef.current + 1).join(''));
        currentIndexRef.current++;

        const delay = tokens[currentIndexRef.current - 1]?.trim() === '' ? 10 : 25;
        timeoutRef.current = setTimeout(typeNext, delay);
      } else {
        setIsTyping(false);
        timeoutRef.current = null;
      }
    };

    typeNext();

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [message, isUser, enableTyping]);

  useEffect(() => {
    if (!onTypingStateChange || isUser) return;
    onTypingStateChange(isTyping);
  }, [isTyping, isUser, onTypingStateChange]);

  useEffect(() => {
    if (isUser || !enableTyping || typingStopSignal === 0) return;
    if (typingStopSignal === lastHandledStopSignalRef.current) return;
    lastHandledStopSignalRef.current = typingStopSignal;

    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    // Stop immediately at the current cursor position (keep partial text as-is)
    setIsTyping(false);
  }, [typingStopSignal, isUser, enableTyping]);

  // -------------------------
  // USER MESSAGE
  // -------------------------
  if (isUser) {
    // ChatGPT-style user bubble: light gray pill, dark text, no shadow,
    // generous rounded corners. Identification is by position (right-aligned)
    // not by colour.
    return (
      <div className="flex justify-end">
        <div className="w-full max-w-3xl flex flex-col items-end gap-1.5 min-w-0">
          {attachments && attachments.length > 0 && (
            <div className="flex flex-col items-end gap-1.5 w-full min-w-0">
              {attachments.map((att, i) => (
                <span
                  key={att.fileId ?? `${i}-${att.name}`}
                  className="inline-flex items-center gap-2 bg-gray-100 dark:bg-slate-800 text-gray-800 dark:text-gray-100 px-3 py-2.5 rounded-xl border border-gray-200 dark:border-slate-700 max-w-full min-w-0"
                  title={att.name}
                >
                  <svg
                    className="w-4 h-4 flex-shrink-0 text-gray-600 dark:text-gray-300"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                  >
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                  <span className="text-sm sm:text-base font-semibold leading-snug truncate min-w-0">{att.name}</span>
                </span>
              ))}
            </div>
          )}
          {!!(message || '').trim() && (
            <div className="bg-gray-100 dark:bg-slate-800 text-gray-900 dark:text-gray-100 rounded-3xl px-5 py-2.5">
              <p className="text-[16px] whitespace-pre-wrap break-words leading-[1.6]">{message}</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Copy code to clipboard
  const handleCopyCode = async (code: string, index: number) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch (err) {
      console.error('Failed to copy code:', err);
    }
  };

  // Reset code block index when message changes
  useEffect(() => {
    codeBlockIndexRef.current = 0;
  }, [message]);

  // -------------------------
  // AI MESSAGE — full width, no bubble, no avatar (ChatGPT style).
  // Hierarchy comes from spacing (handled by MessageList's space-y-6),
  // not from container chrome. Body text is 16px / 1.75 line height like
  // chatgpt.com.
  // -------------------------
  return (
    <div className="w-full">
      <div
        className="
          prose prose-slate dark:prose-invert max-w-none
          text-[16px] leading-[1.75]
          prose-p:my-3 prose-p:leading-[1.75]
          prose-headings:font-semibold prose-headings:tracking-tight
          prose-headings:mt-6 prose-headings:mb-3
          prose-h1:text-[1.4em] prose-h2:text-[1.2em] prose-h3:text-[1.05em]
          prose-h1:mt-7 prose-h1:mb-3
          prose-a:text-indigo-600 dark:prose-a:text-indigo-400
          prose-a:no-underline hover:prose-a:underline
          prose-strong:text-gray-900 dark:prose-strong:text-white
          prose-strong:font-semibold
          prose-em:text-gray-800 dark:prose-em:text-gray-200
          prose-ul:my-3 prose-ol:my-3 prose-ul:pl-6 prose-ol:pl-6
          prose-li:my-1 prose-li:marker:text-gray-400 dark:prose-li:marker:text-gray-500
          prose-blockquote:border-l-2 prose-blockquote:border-gray-300
          dark:prose-blockquote:border-slate-600
          prose-blockquote:px-4 prose-blockquote:my-3
          prose-blockquote:not-italic prose-blockquote:text-gray-600
          dark:prose-blockquote:text-gray-300
          prose-blockquote:font-normal
          prose-table:border-collapse prose-table:my-4 prose-table:w-auto
          prose-th:border prose-th:border-gray-200 dark:prose-th:border-slate-700
          prose-th:bg-gray-50 dark:prose-th:bg-slate-800
          prose-th:px-3 prose-th:py-2 prose-th:text-left prose-th:font-semibold
          prose-td:border prose-td:border-gray-200 dark:prose-td:border-slate-700
          prose-td:px-3 prose-td:py-2
          prose-hr:my-6 prose-hr:border-gray-200 dark:prose-hr:border-slate-700
        "
      >
        {/* IMPORTANT:
            While typing -> render plain text only.
            When finished -> split on Vega-Lite spec markers and render
            each chunk as either markdown or an interactive chart.
        */}
        {isTyping ? (
          <p className="text-[16px] text-gray-800 dark:text-gray-200 whitespace-pre-wrap break-words leading-[1.75]">
            {displayedText}
            <span className="inline-block w-[2px] h-[18px] bg-gray-700 dark:bg-gray-300 ml-0.5 animate-pulse align-text-bottom" />
          </p>
        ) : (
          splitMessageOnVegaSpecs(message).map((part, i) =>
            part.type === 'chart' ? (
              <VegaLiteChart key={i} specJson={part.spec} />
            ) : (
              <ReactMarkdown
                key={i}
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={{
                  code: ({ className, children, ...props }) => {
                    const isInline = !className;
                    if (isInline) {
                      // Inside an inline-code chip, raw backticks are NEVER
                      // meaningful content — they're markdown delimiters that
                      // leaked through (agent uses MySQL-style ``name``,
                      // double/triple wrapping, escape \`, etc.). Strip every
                      // backtick from the rendered chip so it shows just the
                      // identifier.
                      const stripBackticks = (s: string) => s.replace(/`/g, '').trim();
                      const stripped = Array.isArray(children)
                        ? children.map((c) => (typeof c === 'string' ? stripBackticks(c) : c))
                        : typeof children === 'string'
                          ? stripBackticks(children)
                          : children;
                      return (
                        <code
                          className="bg-gray-100 dark:bg-slate-800 text-gray-800 dark:text-gray-200 px-1.5 py-0.5 rounded font-mono text-[0.9em]"
                          {...props}
                        >
                          {stripped}
                        </code>
                      );
                    }

                    // Block code — header bar with language label + copy button.
                    const codeBlockIndex = codeBlockIndexRef.current++;
                    const codeString = extractCodeText(children).replace(/\n$/, '');
                    const isCopied = copiedIndex === codeBlockIndex;
                    const langMatch = /language-([\w-]+)/.exec(className || '');
                    const language = langMatch ? langMatch[1] : 'text';

                    return (
                      <div className="my-3 not-prose rounded-lg overflow-hidden border border-gray-800">
                        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 text-gray-300 text-xs">
                          <span className="font-mono lowercase">{language}</span>
                          <button
                            type="button"
                            onClick={() => handleCopyCode(codeString, codeBlockIndex)}
                            className="flex items-center gap-1.5 px-2 py-0.5 rounded hover:bg-gray-700 text-gray-300 hover:text-white transition-colors"
                            aria-label="Copy code"
                          >
                            {isCopied ? (
                              <>
                                <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                                Copied
                              </>
                            ) : (
                              <>
                                <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                </svg>
                                Copy
                              </>
                            )}
                          </button>
                        </div>
                        <pre className="bg-gray-900 m-0 p-4 overflow-x-auto">
                          <code className={`${className} text-gray-100 text-sm font-mono block leading-relaxed`} {...props}>
                            {children}
                          </code>
                        </pre>
                      </div>
                    );
                  },
                }}
              >
                {normalizeInlineCode(part.content)}
              </ReactMarkdown>
            )
          )
        )}
      </div>
    </div>
  );
}
