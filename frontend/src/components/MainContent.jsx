import React, { useState, useRef, useEffect } from 'react';
import ChatMessage from './ChatMessage';
import { sendMessage } from '../services/api';

const MainContent = () => {
    const [query, setQuery] = useState('');
    const [messages, setMessages] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState(null);
    const messagesEndRef = useRef(null);
    const textareaRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // Auto-resize textarea
    useEffect(() => {
        if (textareaRef.current) {
            // Reset height to auto to get correct scrollHeight
            textareaRef.current.style.height = 'auto';
            const scrollHeight = textareaRef.current.scrollHeight;
            const maxHeight = 200; // Max height in pixels
            const minHeight = 60; // Min height in pixels
            const newHeight = Math.max(minHeight, Math.min(scrollHeight, maxHeight));
            textareaRef.current.style.height = `${newHeight}px`;

            // Enable scroll if content exceeds max height
            if (scrollHeight > maxHeight) {
                textareaRef.current.style.overflowY = 'auto';
            } else {
                textareaRef.current.style.overflowY = 'hidden';
            }
        }
    }, [query]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!query.trim() || isLoading) return;

        const userMessage = query.trim();

        // Add user message to UI immediately
        setMessages(prev => [...prev, { text: userMessage, isUser: true }]);
        setQuery('');
        setIsLoading(true);

        try {
            // Call API
            const response = await sendMessage(userMessage, sessionId);

            if (response.success) {
                // Add AI response
                setMessages(prev => [...prev, { text: response.response, isUser: false }]);

                // Update session ID if provided
                if (response.session_id) {
                    setSessionId(response.session_id);
                }
            } else {
                // Show error message
                setMessages(prev => [...prev, {
                    text: `Error: ${response.error || 'Failed to get response'}`,
                    isUser: false
                }]);
            }
        } catch (error) {
            console.error('Error sending message:', error);
            setMessages(prev => [...prev, {
                text: `Error: ${error.message || 'Failed to connect to server'}`,
                isUser: false
            }]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleRefreshResponse = async (index) => {
        // Find the user message before this AI response
        const userMessageIndex = index - 1;
        if (userMessageIndex < 0) return;

        const userMessage = messages[userMessageIndex];
        if (!userMessage || !userMessage.isUser) return;

        setIsLoading(true);

        try {
            const response = await sendMessage(userMessage.text, sessionId);

            if (response.success) {
                // Update the AI response at this index
                setMessages(prev => {
                    const updated = [...prev];
                    updated[index] = { text: response.response, isUser: false };
                    return updated;
                });
            } else {
                alert(`Error: ${response.error || 'Failed to refresh response'}`);
            }
        } catch (error) {
            console.error('Error refreshing response:', error);
            alert(`Error: ${error.message || 'Failed to refresh response'}`);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex-1 flex flex-col h-screen relative overflow-hidden">
            {/* Background Gradient */}
            <div className="absolute inset-0 bg-gradient-to-b from-white via-white to-blue-50">
                <div className="absolute inset-0 opacity-30">
                    <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-pink-200 rounded-full blur-3xl"></div>
                    <div className="absolute bottom-1/4 left-1/4 w-96 h-96 bg-purple-200 rounded-full blur-3xl"></div>
                </div>
            </div>

            {/* Chat Content */}
            <div className="relative z-10 flex-1 overflow-y-auto px-8 py-6">
                <div className="max-w-4xl mx-auto">
                    {messages.length === 0 ? (
                        // Show welcome screen when no messages
                        <div className="flex flex-col items-center justify-center h-full">
                            {/* Robot Avatar */}
                            <div className="mb-8 relative w-80 h-80">
                                {/* Outer pink ring */}
                                <div className="absolute inset-0 w-64 h-64 rounded-full border-4 border-pink-400 mx-auto"></div>

                                {/* Inner green circle */}
                                <div className="absolute inset-4 w-56 h-56 rounded-full bg-lime-400 mx-auto"></div>

                                {/* Robot Container */}
                                <div className="relative w-48 h-48 mx-auto mt-8">
                                    {/* Robot Head */}
                                    <div className="absolute top-0 left-1/2 transform -translate-x-1/2 w-32 h-32 bg-blue-700 rounded-full shadow-lg">
                                        {/* Eye */}
                                        <div className="absolute top-8 left-1/2 transform -translate-x-1/2 w-12 h-12 bg-white rounded-full">
                                            <div className="absolute top-2 left-1/2 transform -translate-x-1/2 w-8 h-8 bg-black rounded-full"></div>
                                        </div>
                                    </div>

                                    {/* Robot Body */}
                                    <div className="absolute top-24 left-1/2 transform -translate-x-1/2 w-24 h-32 bg-blue-600 rounded-lg shadow-md"></div>

                                    {/* Robot Arms */}
                                    <div className="absolute top-28 left-4 w-6 h-16 bg-blue-700 rounded-full"></div>
                                    <div className="absolute top-28 right-4 w-6 h-16 bg-blue-700 rounded-full"></div>
                                </div>

                                {/* Curved lines from robot head */}
                                <div className="absolute top-8 right-8 w-40 h-1 bg-blue-300 rounded-full transform rotate-12 opacity-70"></div>
                                <div className="absolute top-20 right-12 w-32 h-1 bg-blue-300 rounded-full transform -rotate-12 opacity-70"></div>

                                {/* Large faint circle on right */}
                                <div className="absolute top-1/2 right-0 w-32 h-32 border-2 border-blue-200 rounded-full opacity-50 transform translate-x-8"></div>
                            </div>

                            {/* Greeting Message */}
                            <h1 className="text-2xl font-semibold text-gray-900">
                                Hello! How may I help you?
                            </h1>
                        </div>
                    ) : (
                        // Show chat messages
                        <div className="space-y-4">
                            {messages.map((msg, index) => (
                                <div key={index} className={!msg.isUser ? 'flex flex-col items-start' : ''}>
                                    <ChatMessage message={msg.text} isUser={msg.isUser} />
                                    {!msg.isUser && (
                                        <button
                                            onClick={() => handleRefreshResponse(index)}
                                            className="mt-2 flex items-center gap-1 text-gray-500 hover:text-gray-700 text-xs transition-colors"
                                        >
                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                            </svg>
                                            <span>Refresh response</span>
                                        </button>
                                    )}
                                </div>
                            ))}
                            <div ref={messagesEndRef} />
                        </div>
                    )}
                </div>
            </div>

            {/* Input Field */}
            <div className="relative z-10 px-8 pb-8">
                <div className="max-w-4xl mx-auto">
                    <div className="relative bg-gradient-to-r from-blue-200 via-blue-300 to-purple-300 rounded-2xl p-1 shadow-lg">
                        <div className="bg-white rounded-xl p-4 flex flex-col gap-3">
                            {/* Top Section: Input Area */}
                            <div className="flex items-start gap-3">
                                {/* File and Microphone Icons */}
                                <div className="flex items-center gap-2 pt-2">
                                    {/* File/Attachment Icon */}
                                    <button className="flex items-center gap-1 text-gray-500 hover:text-gray-700 transition-colors">
                                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                                        </svg>
                                        <span className="text-sm font-medium">0</span>
                                    </button>

                                    {/* Microphone Icon */}
                                    <button className="w-10 h-10 rounded-full bg-gray-100 hover:bg-gray-200 flex items-center justify-center text-gray-500 transition-colors">
                                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                                        </svg>
                                    </button>
                                </div>

                                {/* Textarea for long queries */}
                                <textarea
                                    ref={textareaRef}
                                    value={query}
                                    onChange={(e) => setQuery(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && !e.shiftKey) {
                                            e.preventDefault();
                                            handleSubmit(e);
                                        }
                                    }}
                                    placeholder="Type you Query here!"
                                    rows={1}
                                    className="flex-1 outline-none text-gray-700 placeholder-gray-400 resize-none min-h-[60px] py-2 break-words whitespace-pre-wrap"
                                    style={{
                                        maxHeight: '200px',
                                        wordWrap: 'break-word',
                                        overflowWrap: 'break-word',
                                        lineHeight: '1.5'
                                    }}
                                />

                                {/* Submit Button */}
                                <button
                                    onClick={handleSubmit}
                                    disabled={isLoading || !query.trim()}
                                    className="mt-2 w-12 h-12 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-400 disabled:cursor-not-allowed rounded-full flex items-center justify-center text-white transition-colors shadow-md flex-shrink-0"
                                >
                                    {isLoading ? (
                                        <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                    ) : (
                                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                                        </svg>
                                    )}
                                </button>
                            </div>

                            {/* Bottom Section: Action Buttons */}
                            <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
                                <button className="px-4 py-2 bg-white hover:bg-gray-50 border border-blue-300 rounded-lg text-sm font-medium text-gray-700 flex items-center gap-2 transition-colors">
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
                                    </svg>
                                    Web Search
                                </button>

                                <button className="px-4 py-2 bg-white hover:bg-gray-50 border border-blue-300 rounded-lg text-sm font-medium text-gray-700 flex items-center gap-2 transition-colors">
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                                    </svg>
                                    Deep Think
                                </button>

                                <button className="px-4 py-2 bg-white hover:bg-gray-50 border border-blue-300 rounded-lg text-sm font-medium text-gray-700 flex items-center gap-2 transition-colors">
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                                    </svg>
                                    Database Connected
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MainContent;

