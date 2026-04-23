import { useRouter } from "../router";

export function NotFound() {
  const { navigate } = useRouter();
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4">
      <p className="text-4xl font-bold text-neutral-300 dark:text-neutral-600">404</p>
      <p className="text-neutral-500 dark:text-neutral-400">Page not found.</p>
      <button
        onClick={() => navigate("/app/")}
        className="text-sm text-neutral-900 dark:text-neutral-100 underline hover:no-underline"
      >
        Go to Dashboard
      </button>
    </div>
  );
}
