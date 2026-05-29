import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Bot, RotateCcw, Send, Sparkles, User } from "lucide-react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sql?: string | null;
};

type ChatResponse = {
  session_id: string;
  answer: string;
  sql: string | null;
  row_count: number;
  preview: Record<string, unknown>[];
  error?: string;
};

const SUGESTOES = [
  "Quantas famílias estão na folha do PBF?",
  "Famílias PBF com crianças no Serviço de Convivência",
  "Divida os atendidos do SISC por CRAS",
  "Total de famílias no CRAS Bonfim (território CADU)",
];

function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  parts.forEach((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      nodes.push(<strong key={`b-${i}`}>{part.slice(2, -2)}</strong>);
      return;
    }
    part.split("\n").forEach((line, j, lines) => {
      nodes.push(<span key={`l-${i}-${j}`}>{line}</span>);
      if (j < lines.length - 1) nodes.push(<br key={`br-${i}-${j}`} />);
    });
  });
  return nodes;
}

function Welcome({ onPick, disabled }: { onPick: (text: string) => void; disabled: boolean }) {
  return (
    <div className="assist-welcome">
      <div className="assist-welcome-icon" aria-hidden>
        <Sparkles size={28} strokeWidth={1.5} />
      </div>
      <h2 className="assist-welcome-title">Como posso ajudar?</h2>
      <p className="assist-welcome-sub">
        Pergunte sobre CADU, PBF, CRAS ou SISC — em linguagem natural, com contexto na conversa.
      </p>
      <div className="assist-chips">
        {SUGESTOES.map((s) => (
          <button
            key={s}
            type="button"
            className="assist-chip"
            disabled={disabled}
            onClick={() => onPick(s)}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="assist-row assist-row--bot" aria-live="polite" aria-label="Assistente digitando">
      <div className="assist-msg-avatar assist-msg-avatar--bot">
        <Bot size={16} />
      </div>
      <div className="assist-bubble assist-bubble--bot assist-bubble--typing">
        <span className="assist-dot" />
        <span className="assist-dot" />
        <span className="assist-dot" />
      </div>
    </div>
  );
}

export default function AssistPage({ token }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setError("");
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/api/v1/assist/chat`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message: trimmed, session_id: sessionId }),
      });
      const raw = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (raw as { detail?: unknown }).detail;
        const msg = typeof detail === "string" ? detail : `Erro ${res.status} no assistente.`;
        throw new Error(msg);
      }
      const data = raw as ChatResponse;
      setSessionId(data.session_id);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer, sql: data.sql },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao consultar o assistente.");
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void sendMessage(input);
  }

  function novaConversa() {
    setSessionId(null);
    setMessages([]);
    setError("");
    inputRef.current?.focus();
  }

  return (
    <div className="assist-page">
      <div className="assist-shell">
        <header className="assist-header">
          <div className="assist-header-brand">
            <div className="assist-brand-icon" aria-hidden>
              <Sparkles size={18} />
            </div>
            <div>
              <h1 className="assist-header-title">VigIA</h1>
              <p className="assist-header-sub">Assistente de vigilância</p>
            </div>
          </div>
          <button
            type="button"
            className="assist-new-btn"
            onClick={novaConversa}
            disabled={loading}
            title="Nova conversa"
          >
            <RotateCcw size={16} />
            <span>Nova conversa</span>
          </button>
        </header>

        <div className="assist-thread" role="log" aria-label="Mensagens">
          {messages.length === 0 && !loading && (
            <Welcome onPick={(s) => void sendMessage(s)} disabled={loading} />
          )}

          {messages.map((msg, i) => (
            <div
              key={`${i}-${msg.role}`}
              className={msg.role === "user" ? "assist-row assist-row--user" : "assist-row assist-row--bot"}
            >
              {msg.role === "assistant" && (
                <div className="assist-msg-avatar assist-msg-avatar--bot" aria-hidden>
                  <Bot size={16} />
                </div>
              )}
              <article
                className={
                  msg.role === "user"
                    ? "assist-bubble assist-bubble--user"
                    : "assist-bubble assist-bubble--bot"
                }
              >
                <div className="assist-bubble-body">{renderInlineMarkdown(msg.content)}</div>
                {msg.sql && (
                  <details className="assist-sql-details">
                    <summary>Ver consulta SQL</summary>
                    <pre className="assist-sql-pre">{msg.sql}</pre>
                  </details>
                )}
              </article>
              {msg.role === "user" && (
                <div className="assist-msg-avatar assist-msg-avatar--user" aria-hidden>
                  <User size={16} />
                </div>
              )}
            </div>
          ))}

          {loading && <TypingIndicator />}
          <div ref={bottomRef} className="assist-scroll-anchor" />
        </div>

        {error && (
          <div className="assist-error" role="alert">
            {error}
          </div>
        )}

        <form className="assist-composer" onSubmit={handleSubmit}>
          <div className="assist-composer-inner">
            <textarea
              ref={inputRef}
              className="assist-input"
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Pergunte sobre famílias, PBF, CRAS ou convivência…"
              disabled={loading}
              aria-label="Sua mensagem"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void sendMessage(input);
                }
              }}
            />
            <button
              type="submit"
              className="assist-send-btn"
              disabled={loading || !input.trim()}
              aria-label="Enviar mensagem"
            >
              <Send size={18} />
            </button>
          </div>
          <p className="assist-composer-hint">Enter para enviar · Shift+Enter para nova linha</p>
        </form>
      </div>
    </div>
  );
}
