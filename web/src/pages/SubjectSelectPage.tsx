import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { useT } from "../i18n/useT";

export default function SubjectSelectPage() {
  const navigate = useNavigate();
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const handleLogout = () => {
    logout();
    navigate("/");
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <h1 className="text-base font-semibold sm:text-lg">{t("subject_select.title")}</h1>
          <div className="flex min-w-0 items-center gap-2 text-sm sm:gap-3">
            <LanguageSwitcher />
            {user && (
              <span className="hidden max-w-[12rem] truncate text-gray-700 sm:inline">
                {user.email}
              </span>
            )}
            <button
              type="button"
              onClick={handleLogout}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("generate.btn_logout")}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-12">
        <p className="mb-8 text-center text-gray-600">{t("subject_select.prompt")}</p>
        <div className="grid gap-6 sm:grid-cols-3">
          <button
            type="button"
            onClick={() => navigate("/generate/math")}
            className="flex flex-col items-center gap-3 rounded-xl border-2 border-blue-200 bg-white p-8 text-left shadow-sm transition hover:border-blue-500 hover:shadow-md"
          >
            <span className="text-4xl">📐</span>
            <div>
              <div className="text-lg font-semibold text-gray-900">{t("subject_select.math_title")}</div>
              <div className="mt-1 text-sm text-gray-500">{t("subject_select.math_desc")}</div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => navigate("/generate/social_studies")}
            className="flex flex-col items-center gap-3 rounded-xl border-2 border-green-200 bg-white p-8 text-left shadow-sm transition hover:border-green-500 hover:shadow-md"
          >
            <span className="text-4xl">📖</span>
            <div>
              <div className="text-lg font-semibold text-gray-900">{t("subject_select.ss_title")}</div>
              <div className="mt-1 text-sm text-gray-500">{t("subject_select.ss_desc")}</div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => navigate("/generate/natural_sciences")}
            className="flex flex-col items-center gap-3 rounded-xl border-2 border-cyan-200 bg-white p-8 text-left shadow-sm transition hover:border-cyan-500 hover:shadow-md"
          >
            <span className="text-4xl">🔬</span>
            <div>
              <div className="text-lg font-semibold text-gray-900">{t("subject_select.ns_title")}</div>
              <div className="mt-1 text-sm text-gray-500">{t("subject_select.ns_desc")}</div>
            </div>
          </button>
        </div>
      </main>
    </div>
  );
}
