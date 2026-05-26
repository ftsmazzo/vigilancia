import { useEffect, useState, type Dispatch, type FormEvent, type ReactNode, type SetStateAction } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import IngestaoPage from "./pages/IngestaoPage";
import PainelIndicadoresInicio from "./pages/PainelIndicadoresInicio";
import UsuariosPage from "./pages/UsuariosPage";
import ConvivenciaPage from "./pages/ConvivenciaPage";
import CrasPage from "./pages/CrasPage";
import AssistPage from "./pages/AssistPage";
import MunicipioPage from "./pages/MunicipioPage";
import VigilanciaPage from "./pages/VigilanciaPage";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOKEN_KEY = "vigsocial_token";

type HealthResponse = {
  status: string;
};

type LoginResponse = {
  access_token: string;
  role: string;
  name: string;
};

type UserMe = {
  id: number;
  name: string;
  email: string;
  role: string;
};

type NewUserPayload = {
  name: string;
  email: string;
  password: string;
  role: string;
};

function AppShell({
  loadingMe,
  me,
  onLogout,
  children,
}: {
  loadingMe: boolean;
  me: UserMe | null;
  onLogout: () => void;
  children: ReactNode;
}) {
  return (
    <div className="shell">
      <header className="shell-header fx-glass">
        <div className="shell-brand">
          <span className="shell-logo" aria-hidden>
            VS
          </span>
          <div className="shell-brand-text">
            <strong className="shell-title">VigSocial</strong>
            <span className="shell-tagline">Vigilância socioassistencial</span>
          </div>
        </div>

        <nav className="main-nav shell-nav" aria-label="Principal">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Início
          </NavLink>
          <NavLink to="/ingestao" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Ingestão
          </NavLink>
          <NavLink to="/vigilancia" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Vigilância
          </NavLink>
          <NavLink to="/convivencia" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Convivência
          </NavLink>
          <NavLink to="/cras" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            CRAS
          </NavLink>
          <NavLink to="/assistente" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Assistente
          </NavLink>
          <NavLink to="/municipio" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Município
          </NavLink>
          {me?.role === "superadmin" && (
            <NavLink to="/usuarios" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              Usuários
            </NavLink>
          )}
        </nav>

        <div className="shell-user">
          <span className="shell-session">
            {loadingMe ? "Carregando sessão…" : `${me?.name ?? "—"} · ${me?.role ?? ""}`}
          </span>
          <button type="button" className="btn btn-ghost" onClick={onLogout}>
            Sair
          </button>
        </div>
      </header>

      <main className="shell-main">{children}</main>
    </div>
  );
}

function DashboardHome({ token }: { token: string }) {
  return <PainelIndicadoresInicio token={token} />;
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [token, setToken] = useState<string>(localStorage.getItem(TOKEN_KEY) || "");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [me, setMe] = useState<UserMe | null>(null);
  const [loadingMe, setLoadingMe] = useState(false);
  const [users, setUsers] = useState<UserMe[]>([]);
  const [userError, setUserError] = useState("");
  const [newUser, setNewUser] = useState<NewUserPayload>({
    name: "",
    email: "",
    password: "",
    role: "tecnico",
  });

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((res) => res.json())
      .then((data) => setHealth(data))
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    if (!token) {
      setMe(null);
      return;
    }

    setLoadingMe(true);
    fetch(`${API_URL}/api/v1/users/me`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error("Falha ao buscar usuário");
        }
        return res.json();
      })
      .then((data: UserMe) => setMe(data))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken("");
        setAuthError("Sessão inválida. Faça login novamente.");
      })
      .finally(() => setLoadingMe(false));
  }, [token]);

  useEffect(() => {
    if (!token || me?.role !== "superadmin") {
      setUsers([]);
      return;
    }

    fetch(`${API_URL}/api/v1/users`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("Falha ao listar usuários");
        return res.json();
      })
      .then((data: UserMe[]) => setUsers(data))
      .catch(() => setUserError("Não foi possível carregar usuários."));
  }, [token, me?.role]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError("");

    try {
      const response = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });

      const raw = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = (raw as { detail?: unknown }).detail;
        const msg =
          typeof detail === "string"
            ? detail
            : response.status === 401
              ? "Credenciais inválidas."
              : `Erro ${response.status} na API.`;
        setAuthError(msg);
        return;
      }

      const data = raw as LoginResponse;
      localStorage.setItem(TOKEN_KEY, data.access_token);
      setToken(data.access_token);
      setPassword("");
    } catch {
      setAuthError(
        `Não foi possível contactar a API em ${API_URL}. Verifique VITE_API_URL no build do frontend, CORS e se a API está no ar.`
      );
    }
  }

  function handleLogout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setMe(null);
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setUserError("");

    try {
      const response = await fetch(`${API_URL}/api/v1/users`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(newUser),
      });

      if (!response.ok) {
        throw new Error("Erro ao criar usuário");
      }

      const created: UserMe = await response.json();
      setUsers((prev) => [created, ...prev]);
      setNewUser({ name: "", email: "", password: "", role: "tecnico" });
    } catch {
      setUserError("Falha ao criar usuário. Verifique os dados.");
    }
  }

  return (
    <BrowserRouter>
      <div className="app-viewport">
        <Routes>
          <Route
            path="/"
            element={
              !token ? (
                <main className="page page--login">
                  <div className="login-bg" aria-hidden />
                  <div className="login-grid">
                    <div className="login-brand">
                      <div className="login-badge">
                        <span className="login-badge-chip">VS</span>
                        <span>Vigilância socioassistencial</span>
                      </div>
                      <h1 className="login-title">
                        Diagnóstico e dados em{" "}
                        <span className="fx-accent-word">um só lugar</span>
                      </h1>
                      <p className="login-lead">
                        Painel da vigilância socioassistencial com ingestão do Cadastro Único e bases correlatas.
                      </p>
                      <ul className="login-points">
                        <li>Indicadores e manutenções</li>
                        <li>Ingestão segura de arquivos</li>
                        <li>Visões materializadas para análise</li>
                      </ul>
                    </div>
                    <section className="auth-card fx-card fx-card--lift">
                      <h2 className="fx-card-title">Entrar</h2>
                      <p className="fx-card-sub">Use o email e a senha fornecidos pelo administrador.</p>
                      <form onSubmit={handleLogin} className="auth-form">
                        <label>
                          Email
                          <input
                            type="email"
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                            required
                            autoComplete="username"
                          />
                        </label>
                        <label>
                          Senha
                          <input
                            type="password"
                            value={password}
                            onChange={(event) => setPassword(event.target.value)}
                            required
                            autoComplete="current-password"
                          />
                        </label>
                        <button type="submit" className="btn btn-primary">
                          Entrar
                        </button>
                      </form>
                      {authError && <p className="error">{authError}</p>}
                    </section>
                  </div>
                </main>
              ) : (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <DashboardHome token={token} />
                </AppShell>
              )
            }
          />
          <Route
            path="/ingestao"
            element={
              token ? (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <IngestaoPage token={token} />
                </AppShell>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/usuarios"
            element={
              token ? (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <UsuariosPage
                    me={me}
                    users={users}
                    userError={userError}
                    newUser={newUser}
                    setNewUser={setNewUser}
                    onCreateUser={handleCreateUser}
                  />
                </AppShell>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/vigilancia"
            element={
              token ? (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <VigilanciaPage token={token} />
                </AppShell>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/convivencia"
            element={
              token ? (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <ConvivenciaPage token={token} />
                </AppShell>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/cras"
            element={
              token ? (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <CrasPage token={token} />
                </AppShell>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/assistente"
            element={
              token ? (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <AssistPage token={token} />
                </AppShell>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route
            path="/municipio"
            element={
              token ? (
                <AppShell loadingMe={loadingMe} me={me} onLogout={handleLogout}>
                  <MunicipioPage
                    token={token}
                    canEdit={
                      me?.role === "superadmin" ||
                      me?.role === "gestor" ||
                      me?.role === "admin_local"
                    }
                  />
                </AppShell>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
