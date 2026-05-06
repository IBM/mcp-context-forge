import { useEffect, useState } from "react";
import { useIntl } from "react-intl";
import { useAuth } from "../auth/useAuth";
import { useRouter } from "../router";
import { ApiError } from "../api/client";

export function Login() {
  const intl = useIntl();
  const { isAuthenticated, login } = useAuth();
  const { navigate } = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isAuthenticated) {
      navigate("/app/");
    }
  }, [isAuthenticated, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      navigate("/app/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 401
            ? intl.formatMessage({ id: "auth.login.error.invalidCredentials" })
            : intl.formatMessage({ id: "auth.login.error.failed" }, { status: err.status }),
        );
      } else {
        setError(intl.formatMessage({ id: "auth.login.error.unexpected" }));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900">
      <div className="w-full max-w-sm bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100 mb-6">
          {intl.formatMessage({ id: "auth.login.title" })}
        </h1>
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
            >
              {intl.formatMessage({ id: "auth.login.email" })}
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-neutral-300 dark:border-neutral-600 rounded px-3 py-2 text-sm bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-neutral-900 dark:focus:ring-neutral-400"
            />
          </div>
          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
            >
              {intl.formatMessage({ id: "auth.login.password" })}
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-neutral-300 dark:border-neutral-600 rounded px-3 py-2 text-sm bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-neutral-900 dark:focus:ring-neutral-400"
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-neutral-900 dark:bg-neutral-700 text-white rounded px-3 py-2 text-sm font-medium hover:bg-neutral-700 dark:hover:bg-neutral-600 disabled:opacity-50 transition-colors"
          >
            {loading
              ? intl.formatMessage({ id: "auth.login.submitting" })
              : intl.formatMessage({ id: "auth.login.submit" })}
          </button>
        </form>
        <div className="mt-4 text-center">
          <button
            onClick={() => navigate("/app/forgot-password")}
            className="text-sm text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100 transition-colors"
          >
            {intl.formatMessage({ id: "auth.login.forgotPassword" })}
          </button>
        </div>
      </div>
    </div>
  );
}
