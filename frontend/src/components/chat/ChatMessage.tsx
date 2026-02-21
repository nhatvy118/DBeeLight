import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';


type ChatMessageProps = {
  message: string;
  isUser: boolean;
  enableTyping?: boolean;
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

      // Fix inline code that is on its own line
      return part
        // Case 1: newline before and after `code`
        .replace(/\n`([^`\n]+)`\n/g, ' `$1` ')
        // Case 2: newline before `code`
        .replace(/\n`([^`\n]+)`/g, ' `$1`')
        // Case 3: `code` followed by newline
        .replace(/`([^`\n]+)`\n/g, '`$1` ');
    })
    .join('');
}

export default function ChatMessage({ message, isUser, enableTyping = true }: ChatMessageProps) {
  const [displayedText, setDisplayedText] = useState<string>('');
  const [isTyping, setIsTyping] = useState<boolean>(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentIndexRef = useRef<number>(0);
  const codeBlockIndexRef = useRef<number>(0);

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

    const tokens = message.split(/(\s+)/).filter((t) => t.length > 0);

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

  // -------------------------
  // USER MESSAGE
  // -------------------------
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-md">
          <div className="bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 shadow-md">
            <p className="text-sm whitespace-pre-wrap break-words">{message}</p>
          </div>
        </div>
      </div>
    );
  }

  const normalizedMessage = normalizeInlineCode(message);

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
  // AI MESSAGE - Full width (ChatGPT style), no bubble
  // -------------------------
  return (
    <div className="w-full">
      <div className="py-3">
        <div className="prose prose-sm prose-slate max-w-none prose-headings:font-semibold prose-a:text-indigo-600 prose-a:no-underline hover:prose-a:underline prose-table:border-collapse prose-th:border prose-th:border-gray-300 prose-th:bg-gray-50 prose-th:px-3 prose-th:py-2 prose-td:border prose-td:border-gray-200 prose-td:px-3 prose-td:py-2 prose-ul:list-disc prose-ol:list-decimal prose-pre:bg-gray-900 prose-pre:rounded-lg prose-pre:overflow-x-auto">
          {/* IMPORTANT:
              While typing -> render plain text only.
              When finished -> render markdown.
          */}
          {isTyping ? (
            <p className="text-sm text-gray-800 whitespace-pre-wrap break-words leading-relaxed">
              {displayedText}
              <span className="inline-block w-2 h-4 bg-gray-800 ml-1 animate-pulse align-middle" />
            </p>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                code: ({ className, children, ...props }) => {
                  const isInline = !className;
                  if (isInline) {
                    return (
                      <code className="bg-gray-100 text-pink-600 px-1.5 py-0.5 rounded font-mono text-xs font-semibold" {...props}>
                        {children}
                      </code>
                    );
                  }

                  // Block code - copy button always visible (especially for SQL)
                  const codeBlockIndex = codeBlockIndexRef.current++;
                  const codeString = extractCodeText(children).replace(/\n$/, '');
                  const isCopied = copiedIndex === codeBlockIndex;

                  return (
                    <div className="relative group my-3 not-prose">
                      <button
                        type="button"
                        onClick={() => handleCopyCode(codeString, codeBlockIndex)}
                        className="absolute top-2 right-2 z-10 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded transition-colors flex items-center gap-1.5"
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
                      <pre className="bg-gray-900 rounded-lg p-4 pr-24 overflow-x-auto">
                        <code className={`${className} text-gray-100 text-sm font-mono block`} {...props}>
                          {children}
                        </code>
                      </pre>
                    </div>
                  );
                },
              }}
            >
              {normalizedMessage}
            </ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  );
}
