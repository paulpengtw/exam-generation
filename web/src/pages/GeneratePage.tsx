import { useNavigate } from "react-router-dom";

import ParamForm, { type GenerateParams as FormParams } from "../components/ParamForm";
import ProgressLog from "../components/ProgressLog";
import QuestionCard from "../components/QuestionCard";
import { useGenerate } from "../hooks/useGenerate";
import { useAuthStore } from "../store/authStore";

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function GeneratePage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const { status, progressLines, results, generate, reset } = useGenerate();

  const handleLogout = () => {
    logout();
    navigate("/");
  };

  const handleSubmit = (params: FormParams) => {
    generate({
      grade: params.grade,
      style: params.style ? [params.style] : [],
      context: params.context,
      set_type: params.set_type,
      q_type: params.q_type,
      count: params.count,
      skip_verify: params.skip_verify,
    });
  };

  const handleDownloadAll = () => {
    const json = JSON.stringify(results, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    downloadBlob(blob, `batch_${ts}.json`);
  };

  const showProgress = !(progressLines.length === 0 && status === "idle");
  const hasResults = results.length > 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <h1 className="text-lg font-semibold">Exam Generator</h1>
          <div className="flex items-center gap-3 text-sm">
            {user && <span className="text-gray-700">{user.email}</span>}
            <button
              type="button"
              onClick={handleLogout}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6">
        <section className="rounded-lg border bg-white p-4 shadow-sm">
          <ParamForm onSubmit={handleSubmit} disabled={status === "generating"} />
        </section>

        {showProgress && (
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <ProgressLog lines={progressLines} status={status} />
          </section>
        )}

        {hasResults && (
          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">Results ({results.length})</h2>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleDownloadAll}
                  className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                >
                  Download all as JSON
                </button>
                <button
                  type="button"
                  onClick={reset}
                  className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Clear results
                </button>
              </div>
            </div>
            <div className="space-y-3">
              {results.map((q, i) => (
                <QuestionCard key={q.id ?? `q-${i}`} question={q} />
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
