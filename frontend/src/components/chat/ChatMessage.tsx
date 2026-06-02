import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import VegaLiteChart from './VegaLiteChart';
import { Icons } from '../../icons';
import { CodeBlockCard, ResultTableCard } from './RichResponse';

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
  /** The gated SQL in this message has been executed → render its card green. */
  sqlExecuted?: boolean;
  /** The gated SQL failed on execution → render its card red. */
  sqlFailed?: boolean;
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
  sqlExecuted = false,
  sqlFailed = false,
}: ChatMessageProps) {
  const [displayedText, setDisplayedText] = useState<string>('');
  const [isTyping, setIsTyping] = useState<boolean>(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentIndexRef = useRef<number>(0);
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
    // User turn: right-aligned, accent-soft bubble. Attachments show above
    // the text as file chips with a green file glyph (matches Chat/ design).
    return (
      <div className="fade-up" style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <div style={{ maxWidth: '76%', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
          {attachments && attachments.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
              {attachments.map((att, i) => (
                <div
                  key={att.fileId ?? `${i}-${att.name}`}
                  title={att.name}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 9, padding: '8px 12px 8px 9px', borderRadius: 'var(--r-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                >
                  <span style={{ width: 30, height: 30, borderRadius: 7, display: 'grid', placeItems: 'center', background: 'var(--green-soft)', color: 'var(--green-ink)', flexShrink: 0 }}>
                    <Icons.File size={16} />
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 13, fontWeight: 600, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{att.name}</span>
                    <span style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)' }}>Excel</span>
                  </span>
                </div>
              ))}
            </div>
          )}
          {!!(message || '').trim() && (
            <div
              style={{
                background: 'var(--accent-soft)', color: 'var(--text)',
                border: '1px solid var(--accent-soft-2)',
                borderRadius: 'var(--r) var(--r) 6px var(--r)', padding: '12px 18px',
                fontSize: 15.5, lineHeight: 1.5, fontWeight: 500,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}
            >
              {message}
            </div>
          )}
        </div>
      </div>
    );
  }

  // -------------------------
  // AI MESSAGE — full width, no bubble, no avatar (ChatGPT style).
  // Hierarchy comes from spacing (handled by MessageList's space-y-6),
  // not from container chrome. Body text is 16px / 1.75 line height like
  // chatgpt.com.
  // -------------------------
  return (
    <div style={{ width: '100%' }}>
      <div className="ldb-prose">
        {/* IMPORTANT:
            While typing -> render plain text only.
            When finished -> split on Vega-Lite spec markers and render
            each chunk as either markdown or an interactive chart.
        */}
        {isTyping ? (
          <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {displayedText}
            <span style={{ display: 'inline-block', width: 2, height: 18, background: 'var(--text-soft)', marginLeft: 2, verticalAlign: 'text-bottom' }} className="animate-pulse" />
          </p>
        ) : (
          splitMessageOnVegaSpecs(message).map((part, i) =>
            part.type === 'chart' ? (
              <VegaLiteChart key={i} specJson={part.spec} />
            ) : (
              <ReactMarkdown
                key={i}
                remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ node }) => <ResultTableCard node={node} />,
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
                          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 6, padding: '1px 6px', fontFamily: 'var(--font-mono)', fontSize: '0.88em' }}
                          {...props}
                        >
                          {stripped}
                        </code>
                      );
                    }

                    // Block code — on-theme card. SQL gets the "Query
                    // executed" / "SQL query" header; other languages get a
                    // neutral language label. (See RichResponse.CodeBlockCard.)
                    const codeString = extractCodeText(children).replace(/\n$/, '');
                    const langMatch = /language-([\w-]+)/.exec(className || '');
                    const language = langMatch ? langMatch[1] : 'text';

                    return (
                      <CodeBlockCard language={language} codeString={codeString} codeProps={{ className, ...props }} executed={language === 'sql' && sqlExecuted} failed={language === 'sql' && sqlFailed}>
                        {children}
                      </CodeBlockCard>
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
