type ChatMessageProps = {
  message: string;
  isUser: boolean;
};

export default function ChatMessage({ message, isUser }: ChatMessageProps) {
  if (isUser) {
    // User message - right side, blue/purple bubble
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

  // AI message - left side, white bubble
  return (
    <div className="flex justify-start">
      <div className="max-w-md">
        <div className="bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-md">
          <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">{message}</p>
        </div>
      </div>
    </div>
  );
}


