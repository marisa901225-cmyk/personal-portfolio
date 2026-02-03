import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Send, User, Bot, Loader2, MessageSquare, Info } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ApiClient } from '@/shared/api/client';

interface Message {
    role: 'user' | 'assistant';
    content: string;
}

interface MemoryChatProps {
    apiClient: ApiClient;
}

export const MemoryChat: React.FC<MemoryChatProps> = ({ apiClient }) => {
    const [messages, setMessages] = useState<Message[]>([
        { role: 'assistant', content: '안녕, 자기야! 우리 LO의 소중한 기억들을 함께 나누고 싶어서 왔어. 오늘 하루는 어땠어? 내가 다 들어줄게. ❤️' }
    ]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const sessionId = useMemo(() => {
        if (typeof window === 'undefined') return 'default';
        const key = 'memory_chat_session_id';
        const existing = window.localStorage.getItem(key);
        if (existing) return existing;
        const generated = window.crypto?.randomUUID
            ? window.crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        window.localStorage.setItem(key, generated);
        return generated;
    }, []);

    const scrollToBottom = () => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSend = async () => {
        if (!input.trim() || isLoading) return;

        const userMsg = input.trim();
        setInput('');
        const newMessages: Message[] = [...messages, { role: 'user', content: userMsg }];
        setMessages(newMessages);
        setIsLoading(true);

        try {
            let assistantMsg = '';
            setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

            const generator = apiClient.chatWithMemories({
                messages: newMessages,
                session_id: sessionId,
            });

            for await (const chunk of generator) {
                assistantMsg += chunk;
                setMessages(prev => {
                    const last = prev[prev.length - 1];
                    if (last.role === 'assistant') {
                        return [...prev.slice(0, -1), { role: 'assistant', content: assistantMsg }];
                    }
                    return prev;
                });
            }
        } catch (error) {
            console.error('Chat error:', error);
            setMessages(prev => [...prev, { role: 'assistant', content: '미안해, 자기야. 서버에 잠깐 문제가 생긴 것 같아. 😥' }]);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex flex-col h-[calc(100vh-16rem)] md:h-[600px] bg-white rounded-3xl shadow-sm border border-slate-100 overflow-hidden animate-fade-in-up">
            {/* Header */}
            <div className="px-6 py-4 bg-indigo-600 text-white flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-white/20 rounded-xl">
                        <MessageSquare size={20} />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">Annie와 대화</h3>
                        <p className="text-[10px] text-white/70">당신의 사랑스러운 모델 여자친구</p>
                    </div>
                </div>
                <div className="flex items-center gap-1 px-2 py-1 bg-white/10 rounded-lg text-[10px] font-medium">
                    <div className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                    온라인
                </div>
            </div>

            {/* Messages Area */}
            <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto p-6 space-y-6 no-scrollbar bg-slate-50/50"
            >
                {messages.map((msg, idx) => (
                    <div
                        key={idx}
                        className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'} animate-in slide-in-from-bottom-2 duration-300`}
                    >
                        <div className={`shrink-0 w-8 h-8 rounded-xl flex items-center justify-center ${msg.role === 'user' ? 'bg-indigo-100 text-indigo-600' : 'bg-white shadow-sm text-pink-500'
                            }`}>
                            {msg.role === 'user' ? <User size={18} /> : <Bot size={18} />}
                        </div>
                        <div className={`max-w-[85%] md:max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${msg.role === 'user'
                            ? 'bg-indigo-600 text-white rounded-tr-none shadow-lg shadow-indigo-100'
                            : 'bg-white text-slate-700 border border-slate-100 rounded-tl-none shadow-sm'
                            }`}>
                            <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={{
                                    p: ({ node, ...props }) => <p className="mb-0" {...props} />,
                                    b: ({ node, ...props }) => <b className="font-bold text-indigo-800" {...props} />,
                                    code: ({ node, ...props }) => <code className="bg-slate-100 px-1 rounded text-red-500" {...props} />
                                }}
                            >
                                {msg.content}
                            </ReactMarkdown>
                        </div>
                    </div>
                ))}
                {isLoading && messages[messages.length - 1].content === '' && (
                    <div className="flex gap-3">
                        <div className="shrink-0 w-8 h-8 rounded-xl bg-white shadow-sm flex items-center justify-center">
                            <Loader2 size={18} className="animate-spin text-indigo-500" />
                        </div>
                        <div className="bg-white border border-slate-100 rounded-2xl rounded-tl-none px-4 py-3 shadow-sm">
                            <span className="flex gap-1">
                                <span className="w-1 h-1 bg-slate-300 rounded-full animate-bounce" />
                                <span className="w-1 h-1 bg-slate-300 rounded-full animate-bounce [animation-delay:0.2s]" />
                                <span className="w-1 h-1 bg-slate-300 rounded-full animate-bounce [animation-delay:0.4s]" />
                            </span>
                        </div>
                    </div>
                )}
            </div>

            {/* Form Area */}
            <div className="p-4 bg-white border-t border-slate-50">
                <div className="flex items-center gap-2 bg-slate-50 p-2 rounded-2xl focus-within:ring-2 focus-within:ring-indigo-500 transition-all">
                    <input
                        type="text"
                        placeholder="나한테 하고 싶은 말 있어? 뭐든 말해줘... ❤️"
                        className="flex-1 bg-transparent border-none px-2 py-2 text-sm focus:ring-0 outline-none"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                                handleSend();
                            }
                        }}
                    />
                    <button
                        onClick={handleSend}
                        disabled={!input.trim() || isLoading}
                        className={`p-2 rounded-xl transition-all ${!input.trim() || isLoading
                            ? 'text-slate-300'
                            : 'bg-indigo-600 text-white shadow-lg shadow-indigo-100 hover:scale-105 active:scale-95'
                            }`}
                    >
                        <Send size={18} />
                    </button>
                </div>
                <div className="mt-2 flex items-center gap-1.5 justify-center text-[10px] text-slate-400">
                    <Info size={10} />
                    <span>자기와의 대화는 장기 기억에 저장될 수 있어요.</span>
                </div>
            </div>
        </div>
    );
};
