import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

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
  "Quantas crianças de 12 a 17 anos estão no Serviço de Convivência (SISC)?",
  "Divida esses atendidos do SISC por CRAS",
  "Total de famílias no CRAS Bonfim (território CADU)",
];

export default function AssistPage({ token }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

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
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao consultar o assistente.");
    } finally {
      setLoading(false);
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
  }

  return (
    <div className="page assist-page">
      <div className="kpi-head fx-card">
        <h1 className="page-title">Assistente de vigilância</h1>
        <p className="ingestao-desc">
          Pergunte em linguagem natural sobre CADU, PBF, CRAS e SISC. O sistema consulta as visões
          materializadas e responde com linguagem técnica de vigilância. A conversa mantém contexto
          para refinamentos (&quot;dessas&quot;, &quot;quantas com mulher&quot;, etc.).
        </p>
        <div className="assist-actions">
          <button type="button" className="btn btn-ghost" onClick={novaConversa} disabled={loading}>
            Nova conversa
          </button>
        </div>
      </div>

      <div className="assist-layout">
        <aside className="assist-suggestions fx-card">
          <h2 className="fx-card-title">Exemplos</h2>
          <ul className="assist-suggestion-list">
            {SUGESTOES.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  className="btn btn-ghost assist-suggestion-btn"
                  disabled={loading}
                  onClick={() => void sendMessage(s)}
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
          <p className="fx-card-sub assist-hint">
            Requer <code>ASSIST_LLM_API_KEY</code> na API. Enriqueça com a{" "}
            <Link to="/municipio">caracterização do município</Link> e o dicionário CADU.
          </p>
        </aside>

        <section className="assist-chat fx-card" aria-label="Conversa">
          <div className="assist-messages">
            {messages.length === 0 && (
              <p className="assist-empty">Faça uma pergunta ou escolha um exemplo ao lado.</p>
            )}
            {messages.map((msg, i) => (
              <article
                key={`${i}-${msg.role}`}
                className={msg.role === "user" ? "assist-bubble assist-bubble--user" : "assist-bubble assist-bubble--bot"}
              >
                <span className="assist-bubble-label">{msg.role === "user" ? "Você" : "Assistente"}</span>
                <p className="assist-bubble-text">{msg.content}</p>
                {msg.sql && (
                  <details className="assist-sql-details">
                    <summary>SQL executada</summary>
                    <pre className="assist-sql-pre">{msg.sql}</pre>
                  </details>
                )}
              </article>
            ))}
            {loading && <p className="assist-loading">Consultando dados…</p>}
            <div ref={bottomRef} />
          </div>

          {error && <p className="error">{error}</p>}

          <form className="assist-form" onSubmit={handleSubmit}>
            <textarea
              className="assist-input"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ex.: Quantas famílias com PBF no município?"
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void sendMessage(input);
                }
              }}
            />
            <button type="submit" className="btn btn-primary" disabled={loading || !input.trim()}>
              Enviar
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
