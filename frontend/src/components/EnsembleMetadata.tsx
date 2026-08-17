import type { EnsembleInfo } from "@/lib/types";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "text-red-300 bg-red-950/50 border-red-800/60",
  major: "text-orange-300 bg-orange-950/40 border-orange-800/60",
  warning: "text-yellow-300 bg-yellow-950/40 border-yellow-800/60",
  minor: "text-blue-300 bg-blue-950/40 border-blue-800/60",
};

export function EnsembleMetadata({ output }: { output: Record<string, unknown> | null }) {
  const metadata = output?._executor_metadata as
    | { ensemble?: EnsembleInfo }
    | undefined;
  const ensemble = metadata?.ensemble;

  if (ensemble?.mode === "audit") {
    return <AuditView ensemble={ensemble} />;
  }
  if (ensemble?.mode === "best") {
    return <BestView ensemble={ensemble} />;
  }
  if (ensemble?.mode === "concatenate") {
    return <ConcatenateView ensemble={ensemble} />;
  }
  return null;
}

function BestView({ ensemble }: { ensemble: EnsembleInfo }) {
  return (
    <div className="mt-3 bg-blue-950/20 border border-blue-800/40 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-blue-400">
          Ensemble (best of {ensemble.scores?.length ?? ensemble.candidates?.length ?? "N"})
        </span>
        {ensemble.winner_provider && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-900/50 border border-blue-700 text-blue-300">
            Winner: {ensemble.winner_provider}
          </span>
        )}
      </div>

      {(ensemble.scores?.length ?? 0) > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="py-1 pr-2 font-medium">Candidate</th>
                <th className="py-1 pr-2 font-medium">Score</th>
                <th className="py-1 font-medium">Rationale</th>
              </tr>
            </thead>
            <tbody>
              {ensemble.scores!.map((s) => {
                const isWinner =
                  s.index === ensemble.winner_index ||
                  (ensemble.winner_provider && s.provider === ensemble.winner_provider);
                return (
                  <tr
                    key={s.index}
                    className={`border-t border-gray-800 ${
                      isWinner ? "bg-blue-900/20 text-blue-200" : "text-gray-400"
                    }`}
                  >
                    <td className="py-1 pr-2 whitespace-nowrap">
                      {isWinner && <span className="mr-1">★</span>}
                      {s.provider ?? s.index}
                    </td>
                    <td className="py-1 pr-2 font-mono">
                      {typeof s.score === "number"
                        ? s.score.toFixed(1)
                        : typeof s.total === "number"
                        ? s.total.toFixed(1)
                        : "N/A"}
                    </td>
                    <td className="py-1 text-gray-500 max-w-56 truncate" title={s.rationale}>
                      {s.rationale ?? ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {ensemble.rationale && (
        <p className="mt-2 text-xs text-gray-400">
          <span className="text-gray-500 font-medium">Why: </span>
          {ensemble.rationale}
        </p>
      )}
    </div>
  );
}

function AuditView({ ensemble }: { ensemble: EnsembleInfo }) {
  const findings = ensemble.findings ?? [];
  const critical = ensemble.critical_count ?? 0;
  return (
    <div
      className={`mt-3 rounded-lg border p-3 ${
        critical > 0
          ? "bg-red-950/20 border-red-800/40"
          : "bg-green-950/20 border-green-800/40"
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
          Ensemble audit
        </span>
        <span
          className={`text-[11px] px-2 py-0.5 rounded-full border ${
            critical > 0
              ? "bg-red-900/50 border-red-700 text-red-300"
              : "bg-green-900/50 border-green-700 text-green-300"
          }`}
        >
          {critical} critical
        </span>
        {ensemble.recommend_rerun && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-yellow-900/50 border border-yellow-700 text-yellow-300">
            Rerun recommended
          </span>
        )}
        {ensemble.reviewers && ensemble.reviewers.length > 0 && (
          <span className="text-[11px] text-gray-500">
            {ensemble.reviewers.length} reviewer(s)
          </span>
        )}
      </div>

      {findings.length === 0 ? (
        <p className="text-xs text-gray-500">No findings.</p>
      ) : (
        <ul className="space-y-1.5">
          {findings.map((f, i) => {
            const severity = f.severity ?? "minor";
            const color = SEVERITY_COLORS[severity] ?? SEVERITY_COLORS.minor;
            return (
              <li
                key={i}
                className={`text-xs rounded border px-2.5 py-1.5 ${color}`}
              >
                <div className="flex items-center gap-2">
                  <span className="uppercase text-[10px] font-semibold">{severity}</span>
                  {f.location && (
                    <span className="font-mono text-[10px] opacity-80">{f.location}</span>
                  )}
                  {f.reviewer && (
                    <span className="ml-auto text-[10px] opacity-70">{f.reviewer}</span>
                  )}
                </div>
                <div className="mt-0.5">{f.issue ?? ""}</div>
                {f.suggestion && (
                  <div className="mt-0.5 text-[11px] opacity-75">
                    <span className="font-medium">Suggestion: </span>
                    {f.suggestion}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ConcatenateView({ ensemble }: { ensemble: EnsembleInfo }) {
  const candidates = ensemble.candidates ?? [];
  return (
    <div className="mt-3 bg-purple-950/20 border border-purple-800/40 rounded-lg p-3">
      <span className="text-[11px] font-medium uppercase tracking-wide text-purple-300">
        Ensemble (concatenated)
      </span>
      {candidates.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {candidates.map((c) => (
            <li key={c.index} className="text-xs text-gray-400">
              <span className="text-gray-500 font-mono">[{c.index}]</span>{" "}
              {c.provider ?? "?"}{" "}
              <span className={c.success === false ? "text-red-400" : "text-green-400/80"}>
                {c.success === false ? `failed${c.error ? `: ${c.error}` : ""}` : "ok"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}