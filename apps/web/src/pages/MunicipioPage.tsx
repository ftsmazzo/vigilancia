import { useEffect, useState, type FormEvent } from "react";
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
      setOk("Caracterização salva. O assistente passará a usar este contexto nas respostas.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao salvar.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <p>Carregando caracterização do município…</p>
      </div>
    );
  }

  return (
    <div className="page municipio-page">
      <div className="kpi-head fx-card">
        <h1 className="page-title">Caracterização do município</h1>
        <p className="ingestao-desc">
          Cadastro local usado pelo{" "}
          <Link to="/assistente">Assistente de vigilância</Link>: território, rede de serviços e
          prioridades. Complementa o dicionário CADU (<code>dicionariotudo.csv</code>) com o que só
          a equipe municipal sabe.
        </p>
        {data.updated_at && (
          <p className="fx-card-sub">
            Última atualização: {new Date(data.updated_at).toLocaleString("pt-BR")}
            {data.updated_by_email ? ` · ${data.updated_by_email}` : ""}
          </p>
        )}
      </div>

      <form className="municipio-form" onSubmit={handleSubmit}>
        <section className="fx-card municipio-section">
          <h2 className="fx-card-title">Identificação</h2>
          <div className="municipio-grid">
            <label>
              Município
              <input
                type="text"
                value={data.nome_municipio}
                disabled={!canEdit}
                onChange={(e) => setData({ ...data, nome_municipio: e.target.value })}
              />
            </label>
            <label>
              UF
              <input
                type="text"
                maxLength={2}
                value={data.uf}
                disabled={!canEdit}
                onChange={(e) => setData({ ...data, uf: e.target.value.toUpperCase() })}
              />
            </label>
            <label>
              Código IBGE
              <input
                type="text"
                value={data.codigo_ibge || ""}
                disabled={!canEdit}
                onChange={(e) => setData({ ...data, codigo_ibge: e.target.value || null })}
              />
            </label>
          </div>
        </section>

        <section className="fx-card municipio-section">
          <h2 className="fx-card-title">Caracterização</h2>
          {CAMPOS_CARACTERIZACAO.map(({ key, label, rows }) => (
            <label key={key} className="municipio-field-block">
              {label}
              <textarea
                rows={rows}
                disabled={!canEdit}
                value={data.caracterizacao[key] || ""}
                onChange={(e) => setCaracterizacao(key, e.target.value)}
              />
            </label>
          ))}
        </section>

        <section className="fx-card municipio-section">
          <div className="municipio-servicos-head">
            <h2 className="fx-card-title">Rede de serviços</h2>
            {canEdit && (
              <button type="button" className="btn btn-ghost" onClick={addServico}>
                + Serviço
              </button>
            )}
          </div>
          {data.servicos.length === 0 && (
            <p className="fx-card-sub">Nenhum serviço cadastrado. Ex.: CRAS, CREAS, Centro POP, SCFV.</p>
          )}
          {data.servicos.map((s, i) => (
            <div key={i} className="municipio-servico-card">
              <label>
                Nome
                <input
                  type="text"
                  required
                  disabled={!canEdit}
                  value={s.nome}
                  onChange={(e) => updateServico(i, "nome", e.target.value)}
                />
              </label>
              <label>
                Tipo
                <input
                  type="text"
                  placeholder="CRAS, CREAS, SCFV…"
                  disabled={!canEdit}
                  value={s.tipo}
                  onChange={(e) => updateServico(i, "tipo", e.target.value)}
                />
              </label>
              <label>
                Público atendido
                <input
                  type="text"
                  disabled={!canEdit}
                  value={s.publico}
                  onChange={(e) => updateServico(i, "publico", e.target.value)}
                />
              </label>
              <label>
                Observação
                <input
                  type="text"
                  disabled={!canEdit}
                  value={s.observacao}
                  onChange={(e) => updateServico(i, "observacao", e.target.value)}
                />
              </label>
              {canEdit && (
                <button type="button" className="btn btn-ghost municipio-remove" onClick={() => removeServico(i)}>
                  Remover
                </button>
              )}
            </div>
          ))}
        </section>

        {error && <p className="error">{error}</p>}
        {ok && <p className="success">{ok}</p>}

        {canEdit ? (
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? "Salvando…" : "Salvar caracterização"}
          </button>
        ) : (
          <p className="fx-card-sub">Somente gestor ou administrador pode editar. Você pode consultar e usar o assistente.</p>
        )}
      </form>
    </div>
  );
}
