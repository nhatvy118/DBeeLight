import { useEffect, useRef, useState } from 'react';

type ChatMessageProps = {
  message: string;
  isUser: boolean;
  enableTyping?: boolean;
};

export default function ChatMessage({ message, isUser, enableTyping = true }: ChatMessageProps) {
  const [displayedText, setDisplayedText] = useState<string>('');
  const [isTyping, setIsTyping] = useState<boolean>(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentIndexRef = useRef<number>(0);

  useEffect(() => {
    // Clear any existing timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    if (isUser || !enableTyping) {
      // User messages display immediately
      setDisplayedText(message);
      setIsTyping(false);
      currentIndexRef.current = 0;
      return;
    }

    // AI messages: type word by word
    setDisplayedText('');
    setIsTyping(true);
    currentIndexRef.current = 0;

    // Split message into tokens (words and spaces)
    // This regex splits on whitespace but keeps the whitespace as separate tokens
    const tokens = message.split(/(\s+)/).filter((token) => token.length > 0);

    const typeNextWord = () => {
      if (currentIndexRef.current < tokens.length) {
        // Build text from scratch based on current index to prevent duplicates
        const newText = tokens.slice(0, currentIndexRef.current + 1).join('');
        setDisplayedText(newText);
        currentIndexRef.current++;
        // Adjust typing speed: faster for spaces, normal for words
        const delay = tokens[currentIndexRef.current - 1]?.trim() === '' ? 10 : 30;
        timeoutRef.current = setTimeout(typeNextWord, delay);
      } else {
        setIsTyping(false);
        timeoutRef.current = null;
      }
    };

    // Start typing
    typeNextWord();

    // Cleanup function
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, [message, isUser, enableTyping]);

  if (isUser) {
    // User message - right side, blue/purple bubble
    return (
      <div className="flex justify-end">
        <div className="max-w-md">
          <div className="bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 shadow-md">
            <p className="text-sm whitespace-pre-wrap break-words">{displayedText}</p>
          </div>
        </div>
      </div>
    );
  }

  // AI message - left side, white bubble with typing cursor
  return (
    <div className="flex justify-start">
      <div className="max-w-md">
        <div className="bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-md">
          <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">
            {displayedText}
            {isTyping && <span className="inline-block w-2 h-4 bg-gray-800 ml-1 animate-pulse" />}
          </p>
        </div>
      </div>
    </div>
  );
}

