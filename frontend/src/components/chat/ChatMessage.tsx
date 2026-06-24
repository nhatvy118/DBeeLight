import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Icons } from '../../icons';
import { CodeBlockCard, ResultTableCard } from './RichResponse';
import { FileTypeBadge, getFileTypeInfo } from '../../utils/fileType';

// Charts are detected from `tool_events` (tool `generate_chart`) and rendered by
// MessageList — the message text is pure prose, so it renders as-is.

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

    // Charts render separately (from tool_events); the message is pure prose.
    const typingSource = message;
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
                  <FileTypeBadge filename={att.name} size={30} radius={7} />
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: 'block', fontSize: 13, fontWeight: 600, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{att.name}</span>
                    <span style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)' }}>{getFileTypeInfo(att.name).label}</span>
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
  // AI MESSAGE — soft surface bubble so the response stands out from the
  // page background (the user bubble uses the honey accent; the AI bubble
  // uses a neutral surface tint to stay distinguishable). Body text is
  // 16px / 1.75 line height like chatgpt.com.
  // -------------------------
  return (
    <div style={{ width: '100%' }}>
      <div
        className="ldb-prose"
        style={{
          background: 'var(--ai-bubble)',
          border: '1px solid var(--ai-bubble-border)',
          borderRadius: '6px var(--r) var(--r) var(--r)',
          padding: '12px 18px',
        }}
      >
        {/* While typing -> plain text. When finished -> markdown. Charts are
            rendered separately by MessageList from tool_events. */}
        {isTyping ? (
          <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {displayedText}
            <span style={{ display: 'inline-block', width: 2, height: 18, background: 'var(--text-soft)', marginLeft: 2, verticalAlign: 'text-bottom' }} className="animate-pulse" />
          </p>
        ) : (
          <ReactMarkdown
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
            {normalizeInlineCode(message)}
          </ReactMarkdown>
        )}
      </div>
    </div>
  );
}
