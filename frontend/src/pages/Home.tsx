import { useState } from 'react';

export default function Home() {
  const [inputValue, setInputValue] = useState('');

  const handleVoiceClick = () => {
    // Voice input functionality
    console.log('Voice input clicked');
  };

  const handleAttachClick = () => {
    // File attachment functionality
    console.log('Attach clicked');
  };

  const handleActionClick = (action: string) => {
    // Handle action button clicks
    console.log(`${action} clicked`);
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Main Content Area */}
      <div className="flex-1 flex flex-col items-center justify-center px-4 py-12">
        {/* Question */}
        <h1 className="text-4xl md:text-5xl font-bold text-gray-900 mb-8 text-center">
          How are you today?
        </h1>

        {/* Input Field */}
        <div className="w-full max-w-3xl mb-6">
          <div className="relative flex items-center bg-white border-2 border-gray-300 rounded-2xl px-4 py-4 shadow-sm hover:border-gray-400 transition-colors">
            {/* Attach Button */}
            <button
              onClick={handleAttachClick}
              className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mr-3 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
              <span className="text-sm font-medium">Attach</span>
            </button>

            {/* Input */}
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Ask anything"
              className="flex-1 outline-none text-gray-900 placeholder-gray-500 text-lg"
            />

            {/* Voice Button */}
            <button
              onClick={handleVoiceClick}
              className="ml-3 flex items-center gap-2 bg-black text-white px-4 py-2 rounded-xl hover:bg-gray-800 transition-colors font-medium"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
              <span>Voice</span>
            </button>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="w-full max-w-3xl flex flex-wrap justify-center gap-3">
          <button
            onClick={() => handleActionClick('Analyze')}
            className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <span>Analyze</span>
          </button>

          <button
            onClick={() => handleActionClick('SQL')}
            className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            <span>SQL</span>
          </button>

          <button
            onClick={() => handleActionClick('Summarize Text')}
            className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span>Summarize Text</span>
          </button>

          <button
            onClick={() => handleActionClick('Business Insight')}
            className="flex items-center gap-2 px-6 py-3 bg-white border-2 border-gray-300 rounded-xl hover:border-gray-400 hover:bg-gray-50 transition-colors font-medium text-gray-700"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l9-5-9-5-9 5 9 5z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" />
            </svg>
            <span>Business Insight</span>
          </button>
        </div>
      </div>

      {/* Footer */}
      <div className="w-full flex items-center justify-between px-6 py-4 border-t border-gray-200">
        <p className="text-sm text-gray-600 italic text-center flex-1">
          By using LightDBee, you agree to our Term and Service Policy
        </p>
        <button className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center transition-colors ml-4">
          <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </button>
      </div>
    </div>
  );
}

