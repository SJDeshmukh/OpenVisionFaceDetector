import { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { Bot, ChevronLeft, Clock3, History, Loader2, MessageCircle, Plus, Send, Trash2, X } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { API_URL } from '../config';
import { useAuth } from '../context/AuthContext';

const allowedRoles = new Set(['vendor_admin', 'admin', 'owner']);

const iso = (value) => value.toISOString().slice(0, 10);
const dateRange = (days = 7) => {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - days + 1);
  return { start: iso(start), end: iso(end) };
};

const Suggestions = ({ path, onSelect }) => {
  const week = dateRange(7);
  const monthStart = `${week.end.slice(0, 8)}01`;
  const suggestions = path.includes('wage') || path.includes('payroll')
    ? [
        `What are my estimated wages from ${monthStart} to ${week.end}?`,
        `Who recorded the most payable hours from ${week.start} to ${week.end}?`,
      ]
    : [
        `Summarize attendance from ${week.start} to ${week.end}.`,
        `Which attendance records are incomplete from ${week.start} to ${week.end}?`,
      ];
  return (
    <div className="grid gap-2 px-4 pb-4">
      {suggestions.map((suggestion) => (
        <button key={suggestion} type="button" onClick={() => onSelect(suggestion)}
          className="rounded-xl border border-slate-700/80 bg-slate-800/60 px-3 py-2.5 text-left text-xs text-slate-200 transition hover:border-cyan-500/60 hover:bg-slate-800">
          {suggestion}
        </button>
      ))}
    </div>
  );
};

const XChat = () => {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const bottomRef = useRef(null);

  const enabled = Boolean(user?.features?.includes('xchat_ai') && allowedRoles.has(user?.role));
  const filters = useMemo(() => {
    const values = new URLSearchParams(location.search);
    return ['start_date', 'end_date', 'department'].reduce((result, key) => {
      if (values.get(key)) result[key] = values.get(key);
      return result;
    }, {});
  }, [location.search]);

  const loadConversations = async () => {
    try {
      const { data } = await axios.get(`${API_URL}/xchat/conversations`);
      setConversations(data.conversations || []);
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'Could not load chat history.');
    }
  };

  useEffect(() => {
    if (open && enabled) loadConversations();
  }, [open, enabled]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    const closeOnEscape = (event) => event.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, []);

  const newChat = () => {
    setConversationId(null);
    setMessages([]);
    setError('');
    setHistoryOpen(false);
  };

  const openConversation = async (conversation) => {
    setLoading(true);
    setError('');
    try {
      const { data } = await axios.get(`${API_URL}/xchat/conversations/${conversation.id}/messages`);
      setConversationId(conversation.id);
      setMessages(data.messages || []);
      setHistoryOpen(false);
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'Could not open this conversation.');
    } finally {
      setLoading(false);
    }
  };

  const removeConversation = async (event, id) => {
    event.stopPropagation();
    try {
      await axios.delete(`${API_URL}/xchat/conversations/${id}`);
      if (conversationId === id) newChat();
      await loadConversations();
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'Could not delete this conversation.');
    }
  };

  const send = async (preset) => {
    const text = String(preset || draft).trim();
    if (!text || loading) return;
    setDraft('');
    setError('');
    setMessages((current) => [...current, { id: `local-${Date.now()}`, role: 'user', content: text }]);
    setLoading(true);
    try {
      const { data } = await axios.post(`${API_URL}/xchat/messages`, {
        message: text,
        conversation_id: conversationId,
        page_context: { page: location.pathname, filters },
      });
      setConversationId(data.conversation_id);
      setMessages((current) => [...current, {
        id: `assistant-${Date.now()}`, role: 'assistant', content: data.answer,
        metadata: { tools_used: data.tools_used || [], sources: data.sources || [] },
      }]);
      loadConversations();
    } catch (requestError) {
      setError(requestError.response?.data?.error || 'XChat is temporarily unavailable. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (!enabled) return null;

  return (
    <>
      {!open && (
        <button type="button" onClick={() => setOpen(true)} aria-label="Open XChat assistant"
          className="fixed bottom-5 right-5 z-40 flex h-14 items-center gap-2 rounded-full bg-gradient-to-r from-cyan-500 to-blue-600 px-4 text-white shadow-2xl shadow-cyan-950/50 transition hover:scale-105 focus:outline-none focus:ring-2 focus:ring-cyan-300">
          <MessageCircle size={23} /><span className="hidden text-sm font-semibold sm:inline">Ask XChat</span>
        </button>
      )}
      {open && (
        <section aria-label="XChat business assistant"
          className="fixed inset-0 z-50 flex flex-col overflow-hidden border-slate-700 bg-slate-950 text-slate-100 shadow-2xl sm:inset-auto sm:bottom-5 sm:right-5 sm:h-[min(680px,calc(100vh-40px))] sm:w-[410px] sm:rounded-2xl sm:border">
          <header className="flex h-16 shrink-0 items-center gap-3 border-b border-slate-800 bg-slate-900/95 px-4">
            {historyOpen && <button type="button" onClick={() => setHistoryOpen(false)} aria-label="Back to chat"><ChevronLeft size={20} /></button>}
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-cyan-500/15 text-cyan-300"><Bot size={21} /></span>
            <div className="min-w-0 flex-1"><h2 className="text-sm font-semibold">XChat</h2><p className="truncate text-[11px] text-slate-400">Read-only attendance & payroll</p></div>
            <button type="button" onClick={() => setHistoryOpen(!historyOpen)} className="rounded-lg p-2 hover:bg-slate-800" aria-label="Chat history"><History size={19} /></button>
            <button type="button" onClick={newChat} className="rounded-lg p-2 hover:bg-slate-800" aria-label="New chat"><Plus size={19} /></button>
            <button type="button" onClick={() => setOpen(false)} className="rounded-lg p-2 hover:bg-slate-800" aria-label="Close XChat"><X size={19} /></button>
          </header>

          {historyOpen ? (
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              <p className="px-2 pb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Recent conversations</p>
              {!conversations.length && <p className="p-5 text-center text-sm text-slate-500">No conversations yet.</p>}
              {conversations.map((conversation) => (
                <button key={conversation.id} type="button" onClick={() => openConversation(conversation)}
                  className="group mb-1 flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left hover:bg-slate-900">
                  <Clock3 size={16} className="shrink-0 text-slate-500" />
                  <span className="min-w-0 flex-1 truncate text-sm">{conversation.title}</span>
                  <span role="button" tabIndex={0} onClick={(event) => removeConversation(event, conversation.id)}
                    onKeyDown={(event) => event.key === 'Enter' && removeConversation(event, conversation.id)}
                    className="rounded p-1 text-slate-600 opacity-0 hover:text-red-400 group-hover:opacity-100" aria-label="Delete conversation"><Trash2 size={15} /></span>
                </button>
              ))}
            </div>
          ) : (
            <>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                {!messages.length && (
                  <div className="flex min-h-full flex-col justify-center">
                    <div className="mb-5 text-center"><Bot className="mx-auto mb-3 text-cyan-400" size={34} /><h3 className="font-medium">Ask about your workforce data</h3><p className="mt-1 text-xs leading-5 text-slate-400">I can use five secure, read-only tools. Dates make answers more precise.</p></div>
                    <Suggestions path={location.pathname} onSelect={send} />
                  </div>
                )}
                <div className="space-y-4">
                  {messages.map((message) => (
                    <div key={message.id} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                      <div className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-3.5 py-3 text-sm leading-6 ${message.role === 'user' ? 'rounded-br-md bg-blue-600 text-white' : 'rounded-bl-md border border-slate-800 bg-slate-900 text-slate-200'}`}>
                        {message.content}
                        {message.role === 'assistant' && message.metadata?.sources?.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1.5 border-t border-slate-800 pt-2">
                            {message.metadata.sources.map((source) => <button key={source} type="button" onClick={() => { setOpen(false); navigate(source); }} className="rounded-full bg-cyan-950/60 px-2 py-0.5 text-[10px] text-cyan-300 hover:bg-cyan-900">View source</button>)}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {loading && <div className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="animate-spin" size={16} /> Checking your data…</div>}
                  <div ref={bottomRef} />
                </div>
              </div>
              {error && <div role="alert" className="mx-4 mb-2 rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">{error}</div>}
              <footer className="shrink-0 border-t border-slate-800 bg-slate-900/80 p-3">
                <div className="flex items-end gap-2 rounded-xl border border-slate-700 bg-slate-950 p-2 focus-within:border-cyan-600">
                  <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={1} maxLength={1000} placeholder="Ask about attendance or payroll…"
                    onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }}
                    className="max-h-24 min-h-9 flex-1 resize-none bg-transparent px-1 py-2 text-sm outline-none placeholder:text-slate-600" />
                  <button type="button" disabled={!draft.trim() || loading} onClick={() => send()} aria-label="Send message"
                    className="grid h-9 w-9 place-items-center rounded-lg bg-cyan-500 text-slate-950 disabled:cursor-not-allowed disabled:opacity-40"><Send size={17} /></button>
                </div>
                <p className="mt-2 text-center text-[10px] text-slate-500">Read-only insights · Verify payroll before processing</p>
              </footer>
            </>
          )}
        </section>
      )}
    </>
  );
};

export default XChat;
