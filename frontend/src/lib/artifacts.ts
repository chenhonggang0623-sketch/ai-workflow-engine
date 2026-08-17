import { get } from "./api";
import type { Artifact } from "./types";

export function listArtifacts(params?: {
  execution_id?: string;
  node_id?: string;
  type?: string;
}): Promise<Artifact[]> {
  const query = new URLSearchParams();
  if (params?.execution_id) query.set("execution_id", params.execution_id);
  if (params?.node_id) query.set("node_id", params.node_id);
  if (params?.type) query.set("type", params.type);
  const qs = query.toString();
  return get<Artifact[]>(`/artifacts${qs ? `?${qs}` : ""}`);
}

export function getArtifact(id: string): Promise<Artifact> {
  return get<Artifact>(`/artifacts/${id}`);
}

export function getArtifactDownloadUrl(id: string): string {
  return `/api/artifacts/${id}/download`;
}
