import { useEffect, useState, type FormEvent } from "react";
import { Building2, Link2, Plus, Save, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Props = {
  token: string;
  canEdit: boolean;
};

type Servico = {
  nome: string;
  tipo: string;
  publico: string;
  observacao: string;
};

type ContextPayload = {
  nome_municipio: string;
  uf: string;
  codigo_ibge: string | null;
  caracterizacao: Record<string, string>;
  servicos: Servico[];
  updated_at?: string | null;
  updated_by_email?: string | null;
};

const CAMPOS_CARACTERIZACAO: { key: string; label: string; rows: number }[] = [
  { key: "territorio", label: "Território e divisão administrativa", rows: 3 },
  { key: "perfil_socioeconomico", label: "Perfil socioeconômico", rows: 3 },
  { key: "rede_suas", label: "Rede SUAS e parcerias", rows: 3 },
  { key: "vulnerabilidades", label: "Vulnerabilidades e prioridades de vigilância", rows: 4 },
  { key: "notas", label: "Notas gerais para o assistente", rows: 3 },
];

const emptyServico = (): Servico => ({ nome: "", tipo: "", publico: "", observacao: "" });

export default function MunicipioPage({ token, canEdit }: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [data, setData] = useState<ContextPayload>({
    nome_municipio: "",
    uf: "",
    codigo_ibge: null,
    caracterizacao: {},
    servicos: [],
  });

  useEffect(() => {
    setLoading(true);
    fetch(`${API_URL}/api/v1/municipio/context`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("Falha ao carregar");
        return res.json() as Promise<ContextPayload>;
      })
      .then((json) => {
        setData({
          ...json,
          caracterizacao: json.caracterizacao || {},
          servicos: (json.servicos || []).map((s) => ({
            nome: s.nome || "",
            tipo: s.tipo || "",
            publico: s.publico || "",
            observacao: s.observacao || "",
          })),
        });
      })
      .catch(() => setError("Não foi possível carregar a caracterização."))
      .finally(() => setLoading(false));
  }, [token]);

  function setCaracterizacao(key: string, value: string) {
    setData((d) => ({
      ...d,
      caracterizacao: { ...d.caracterizacao, [key]: value },
    }));
  }

  function updateServico(index: number, field: keyof Servico, value: string) {
    setData((d) => {
      const list = [...d.servicos];
      list[index] = { ...list[index], [field]: value };
      return { ...d, servicos: list };
    });
  }

  function addServico() {
    setData((d) => ({ ...d, servicos: [...d.servicos, emptyServico()] }));
  }

  function removeServico(index: number) {
    setData((d) => ({ ...d, servicos: d.servicos.filter((_, i) => i !== index) }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canEdit) return;
    setSaving(true);
    setError("");
    setOk("");
    const servicos = data.servicos.filter((s) => s.nome.trim());
    try {
      const res = await fetch(`${API_URL}/api/v1/municipio/context`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ...data, servicos }),
      });
      const raw = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (raw as { detail?: string }).detail;
        throw new Error(detail || `Erro ${res.status}`);
      }
      setData(raw as ContextPayload);
      setOk("Caracterização salva. O VigIA passará a usar este contexto.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao salvar.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="municipio-page">
        <div className="municipio-shell municipio-shell--loading">
          <p className="municipio-loading">Carregando caracterização…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="municipio-page">
      <form className="municipio-shell" onSubmit={handleSubmit}>
        <header className="municipio-header">
          <div className="municipio-header-brand">
            <div className="municipio-brand-icon" aria-hidden>
              <Building2 size={18} />
            </div>
            <div>
              <h1 className="municipio-header-title">Caracterização do município</h1>
              <p className="municipio-header-sub">
                Contexto local para o{" "}
                <Link to="/assistente" className="municipio-inline-link">
                  VigIA
                </Link>
                {data.updated_at && (
                  <>
                    {" · "}
                    Atualizado em {new Date(data.updated_at).toLocaleString("pt-BR")}
                    {data.updated_by_email ? ` (${data.updated_by_email})` : ""}
                  </>
                )}
              </p>
            </div>
          </div>
        </header>

        <div className="municipio-body">
          <section className="municipio-block">
            <h2 className="municipio-block-title">Identificação</h2>
            <div className="municipio-grid">
              <label className="municipio-field">
                <span>Município</span>
                <input
                  type="text"
                  className="municipio-input"
                  value={data.nome_municipio}
                  disabled={!canEdit}
                  onChange={(e) => setData({ ...data, nome_municipio: e.target.value })}
                />
              </label>
              <label className="municipio-field municipio-field--uf">
                <span>UF</span>
                <input
                  type="text"
                  className="municipio-input"
                  maxLength={2}
                  value={data.uf}
                  disabled={!canEdit}
                  onChange={(e) => setData({ ...data, uf: e.target.value.toUpperCase() })}
                />
              </label>
              <label className="municipio-field municipio-field--ibge">
                <span>IBGE</span>
                <input
                  type="text"
                  className="municipio-input"
                  value={data.codigo_ibge || ""}
                  disabled={!canEdit}
                  onChange={(e) => setData({ ...data, codigo_ibge: e.target.value || null })}
                />
              </label>
            </div>
          </section>

          <section className="municipio-block">
            <h2 className="municipio-block-title">Perfil e prioridades</h2>
            <div className="municipio-fields-stack">
              {CAMPOS_CARACTERIZACAO.map(({ key, label, rows }) => (
                <label key={key} className="municipio-field municipio-field--area">
                  <span>{label}</span>
                  <textarea
                    className="municipio-textarea"
                    rows={rows}
                    disabled={!canEdit}
                    value={data.caracterizacao[key] || ""}
                    onChange={(e) => setCaracterizacao(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
          </section>

          <section className="municipio-block">
            <div className="municipio-block-head">
              <h2 className="municipio-block-title">Rede de serviços</h2>
              {canEdit && (
                <button type="button" className="municipio-add-btn" onClick={addServico}>
                  <Plus size={16} />
                  <span>Adicionar</span>
                </button>
              )}
            </div>
            {data.servicos.length === 0 && (
              <p className="municipio-empty">Nenhum serviço cadastrado (CRAS, CREAS, SCFV…).</p>
            )}
            <div className="municipio-servicos-list">
              {data.servicos.map((s, i) => (
                <article key={i} className="municipio-servico-card">
                  <div className="municipio-servico-grid">
                    <label className="municipio-field">
                      <span>Nome</span>
                      <input
                        type="text"
                        className="municipio-input"
                        required
                        disabled={!canEdit}
                        value={s.nome}
                        onChange={(e) => updateServico(i, "nome", e.target.value)}
                      />
                    </label>
                    <label className="municipio-field">
                      <span>Tipo</span>
                      <input
                        type="text"
                        className="municipio-input"
                        placeholder="CRAS, CREAS, SCFV…"
                        disabled={!canEdit}
                        value={s.tipo}
                        onChange={(e) => updateServico(i, "tipo", e.target.value)}
                      />
                    </label>
                    <label className="municipio-field">
                      <span>Público atendido</span>
                      <input
                        type="text"
                        className="municipio-input"
                        disabled={!canEdit}
                        value={s.publico}
                        onChange={(e) => updateServico(i, "publico", e.target.value)}
                      />
                    </label>
                    <label className="municipio-field municipio-field--wide">
                      <span>Observação</span>
                      <input
                        type="text"
                        className="municipio-input"
                        disabled={!canEdit}
                        value={s.observacao}
                        onChange={(e) => updateServico(i, "observacao", e.target.value)}
                      />
                    </label>
                  </div>
                  {canEdit && (
                    <button
                      type="button"
                      className="municipio-remove-btn"
                      onClick={() => removeServico(i)}
                    >
                      <Trash2 size={14} />
                      <span>Remover</span>
                    </button>
                  )}
                </article>
              ))}
            </div>
          </section>
        </div>

        <footer className="municipio-footer">
          {error && (
            <div className="municipio-alert municipio-alert--error" role="alert">
              {error}
            </div>
          )}
          {ok && (
            <div className="municipio-alert municipio-alert--ok" role="status">
              {ok}
            </div>
          )}
          <div className="municipio-footer-actions">
            {!canEdit && (
              <p className="municipio-readonly-hint">
                Somente gestor ou administrador pode editar.
              </p>
            )}
            {canEdit ? (
              <button type="submit" className="municipio-save-btn" disabled={saving}>
                <Save size={18} />
                <span>{saving ? "Salvando…" : "Salvar caracterização"}</span>
              </button>
            ) : (
              <Link to="/assistente" className="municipio-save-btn municipio-save-btn--link">
                <Link2 size={18} />
                <span>Abrir VigIA</span>
              </Link>
            )}
          </div>
        </footer>
      </form>
    </div>
  );
}
