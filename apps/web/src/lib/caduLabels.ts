export const ROTULO_CADU: Record<string, string> = {
  masculino: "Masculino",
  feminino: "Feminino",
  nao_informado: "Não informado",
  branca: "Branca",
  preta: "Preta",
  amarela: "Amarela",
  parda: "Parda",
  indigena: "Indígena",
  outro_codigo: "Outro código",
  analfabeto: "Analfabeto",
  fundamental_incompleto: "Fundamental incompleto",
  fundamental_completo: "Fundamental completo",
  medio_incompleto: "Médio incompleto",
  medio_completo: "Médio completo",
  superior_incompleto: "Superior incompleto",
  superior_completo: "Superior completo",
  crianca_0_11: "0–11 anos",
  adolescente_12_17: "12–17 anos",
  adulto_18_59: "18–59 anos",
  idoso_60_mais: "60 anos ou mais",
  idade_nao_informada: "Idade não informada",
  sem_deficiencia: "Sem deficiência",
  deficiencia_fisica: "Deficiência física",
  deficiencia_visual: "Deficiência visual",
  deficiencia_auditiva: "Deficiência auditiva",
  deficiencia_mental_cognitiva: "Deficiência mental / cognitiva",
  deficiencia_multipla: "Deficiência múltipla",
  com_deficiencia_sem_tipo: "Com deficiência (tipo não detalhado)",
};

export function rotuloAmigavel(chave: string): string {
  return ROTULO_CADU[chave] ?? chave.replace(/_/g, " ");
}
