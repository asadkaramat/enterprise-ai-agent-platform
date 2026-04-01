import { useState, useRef, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Send, RefreshCw } from 'lucide-react';
import {
  fetchSession,
  fetchSessionMessages,
  sendMessage,
} from '../api/sessions';
import StatusBadge from '../components/StatusBadge';
import LoadingSpinner from '../components/LoadingSpinner';
import type { Message, SessionStatus } from '../types';

/* ─── Tool card (collapsible) ─── */
function ToolCard({ msg }: { msg: Message }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mx-auto my-3 max-w-2xl rounded-lg border border-yellow-200 bg-yellow-50">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-semibold text-yellow-800"
      >
        <span className="flex items-center gap-2">
          <span className="rounded bg-yellow-200 px-1.5 py-0.5 text-yellow-900">
            TOOL
          </span>
          {msg.tool_name}
        </span>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>
      {open && (
        <div className="border-t border-yellow-100 px-4 pb-3 pt-2 space-y-3">
          <div>
            <p className="mb-1 text-xs font-semibold text-yellow-700 uppercase tracking-wide">
              Input
            </p>
            <pre className="overflow-auto rounded bg-yellow-100 p-2 text-xs text-yellow-900 max-h-48">
              {JSON.stringify(msg.tool_input, null, 2)}
            </pre>
          </div>
          {msg.tool_result !== undefined && (
            <div>
              <p className="mb-1 text-xs font-semibold text-yellow-700 uppercase tracking-wide">
                Result
              </p>
              <pre className="overflow-auto rounded bg-yellow-100 p-2 text-xs text-yellow-900 max-h-48">
                {JSON.stringify(msg.tool_result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Single message bubble ─── */
function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === 'tool') return <ToolCard msg={msg} />;

  if (msg.role === 'system') {
    return (
      <div className="flex justify-center my-3">
        <span className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-500">
          {msg.event_type ?? msg.content}
        </span>
      </div>
    );
  }

  const isUser = msg.role === 'user';

  return (
    <div className={`flex my-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="mr-2 mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-gray-200 text-xs font-bold text-gray-600">
          AI
        </div>
      )}
      <div
        className={`max-w-lg rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
          isUser
            ? 'rounded-br-sm bg-blue-600 text-white'
            : 'rounded-bl-sm bg-gray-100 text-gray-800'
        }`}
      >
        <p className="whitespace-pre-wrap">{msg.content}</p>
        <p
          className={`mt-1 text-right text-xs ${
            isUser ? 'text-blue-200' : 'text-gray-400'
          }`}
        >
          {new Date(msg.created_at).toLocaleTimeString()}
        </p>
      </div>
      {isUser && (
        <div className="ml-2 mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
          U
        </div>
      )}
    </div>
  );
}

/* ─── Main page ─── */
export default function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState('');

  const { data: session, isLoading: sessionLoading } = useQuery({
    queryKey: ['session', id],
    queryFn: () => fetchSession(id!),
    refetchInterval: (query) =>
      query.state.data?.status === 'active' ? 5000 : false,
  });

  const { data: messages = [], isLoading: msgsLoading } = useQuery({
    queryKey: ['session-messages', id],
    queryFn: () => fetchSessionMessages(id!),
    refetchInterval: session?.status === 'active' ? 5000 : false,
  });

  const sendMutation = useMutation({
    mutationFn: (content: string) => sendMessage(id!, content),
    onSuccess: () => {
      setInput('');
      qc.invalidateQueries({ queryKey: ['session-messages', id] });
      qc.invalidateQueries({ queryKey: ['session', id] });
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const isActive = session?.status === 'active';

  function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || sendMutation.isPending) return;
    sendMutation.mutate(trimmed);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  if (sessionLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 max-w-3xl mx-auto h-full">
      {/* Session header */}
      {session && (
        <div className="rounded-xl bg-white px-5 py-4 shadow-sm ring-1 ring-gray-200">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">
                Session
              </p>
              <p className="font-mono font-medium text-gray-800 mt-0.5">
                {session.id.slice(0, 16)}…
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">
                Status
              </p>
              <div className="mt-0.5">
                <StatusBadge status={session.status as SessionStatus} />
              </div>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">
                Agent
              </p>
              <p className="font-medium text-gray-800 mt-0.5">
                {session.agent_name ?? session.agent_id}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">
                Steps
              </p>
              <p className="font-medium text-gray-800 mt-0.5">
                {session.step_count}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide">
                Tokens
              </p>
              <p className="font-medium text-gray-800 mt-0.5">
                {session.total_tokens.toLocaleString()}
              </p>
            </div>
            {isActive && (
              <div className="ml-auto">
                <span className="flex items-center gap-1.5 text-xs text-green-600">
                  <RefreshCw size={11} className="animate-spin" />
                  Auto-refreshing
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Message timeline */}
      <div
        className="flex-1 overflow-y-auto rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-200"
        style={{ minHeight: '400px', maxHeight: 'calc(100vh - 340px)' }}
      >
        {msgsLoading ? (
          <div className="flex h-full items-center justify-center py-10">
            <LoadingSpinner />
          </div>
        ) : messages.length === 0 ? (
          <p className="py-16 text-center text-sm text-gray-400">
            No messages yet.
          </p>
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Input area (only for active sessions) */}
      {isActive && (
        <div className="flex gap-2">
          <textarea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Continue the conversation… (Enter to send, Shift+Enter for newline)"
            className="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 shadow-sm"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || sendMutation.isPending}
            className="flex items-center justify-center rounded-xl bg-blue-600 px-4 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm"
            title="Send message"
          >
            {sendMutation.isPending ? (
              <LoadingSpinner size="sm" />
            ) : (
              <Send size={18} />
            )}
          </button>
        </div>
      )}

      {sendMutation.isError && (
        <p className="text-sm text-red-600">
          Failed to send message. Please try again.
        </p>
      )}
    </div>
  );
}
