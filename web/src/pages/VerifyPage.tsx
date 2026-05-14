import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useT } from "../i18n/useT";

type Status = "verifying" | "error";

export default function VerifyPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { verifyToken } = useAuth();
  const t = useT();
  const [status, setStatus] = useState<Status>("verifying");
  const [error, setError] = useState<string | null>(null);
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    const token = searchParams.get("token");
    const email = searchParams.get("email");

    if (!token || !email) {
      setError(t("verify.error_default"));
      setStatus("error");
      return;
    }

    void (async () => {
      const result = await verifyToken(token, email);
      if (result.success) {
        navigate("/generate", { replace: true });
      } else {
        setError(t("verify.error_default"));
        setStatus("error");
      }
    })();
  }, [searchParams, verifyToken, navigate, t]);

  if (status === "verifying") {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div role="status" className="inline-flex items-center gap-3 text-gray-700">
          <span
            aria-hidden="true"
            className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-gray-400 border-t-transparent"
          />
          <span>{t("verify.verifying")}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4 text-center">
        <p role="alert" className="text-red-600">
          {error ?? t("verify.error_default")}
        </p>
        <button
          type="button"
          onClick={() => navigate("/", { replace: true })}
          className="rounded bg-blue-600 px-4 py-2 text-white font-medium hover:bg-blue-700"
        >
          {t("verify.btn_request_new")}
        </button>
      </div>
    </div>
  );
}
