import { useMemo, useState } from "react";
import { useIntl } from "react-intl";
import { Blocks, Bot, Code } from "lucide-react";
import { createVirtualServer } from "@/api/virtualServers";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { CreateServerForm } from "@/components/gateways/CreateServerForm";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import type { ActionCard, CreateServerDetails } from "@/components/gateways/types";
import { ApiError } from "@/api/client";
import { useRouter } from "@/router";

const SERVERS_FORM_PATH = "/app/servers?openForm=true";

type CreateServerStep = "details" | "sources";

function getCreateServerError(error: unknown, fallbackMessage: string): string {
  if (error instanceof ApiError) {
    const body = error.body as { message?: string; detail?: unknown } | null;
    if (body?.message) return body.message;
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length > 0) {
      return body.detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg?: unknown }).msg);
          }
          return String(item);
        })
        .join("; ");
    }
  }

  if (error instanceof Error) return error.message;
  return fallbackMessage;
}

export function CreateServer() {
  const intl = useIntl();
  const { navigate } = useRouter();
  const [step, setStep] = useState<CreateServerStep>("details");
  const [serverDetails, setServerDetails] = useState<CreateServerDetails | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const actionCards: ActionCard[] = useMemo(
    () => [
      {
        icon: MCPIcon,
        title: intl.formatMessage({ id: "gateways.action.mcpServer.title" }),
        description: intl.formatMessage({ id: "gateways.action.mcpServer.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        onAction: () => navigate(SERVERS_FORM_PATH),
      },
      {
        icon: Bot,
        title: intl.formatMessage({ id: "gateways.action.aiAgent.title" }),
        description: intl.formatMessage({ id: "gateways.action.aiAgent.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        onAction: () => navigate("/app/agents"),
      },
      {
        icon: Code,
        title: intl.formatMessage({ id: "gateways.action.restApi.title" }),
        description: intl.formatMessage({ id: "gateways.action.restApi.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        disabled: true,
        disabledReason: intl.formatMessage({ id: "gateways.action.comingSoon" }),
        onAction: () => undefined,
      },
      {
        icon: Blocks,
        title: intl.formatMessage({ id: "gateways.action.grpc.title" }),
        description: intl.formatMessage({ id: "gateways.action.grpc.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        disabled: true,
        disabledReason: intl.formatMessage({ id: "gateways.action.comingSoon" }),
        onAction: () => undefined,
      },
    ],
    [intl, navigate],
  );

  const handleSkipForNow = async () => {
    if (!serverDetails) {
      setStep("details");
      return;
    }

    setIsCreating(true);
    setCreateError(null);
    try {
      await createVirtualServer(serverDetails);
      navigate("/app/gateways");
    } catch (error) {
      setCreateError(
        getCreateServerError(
          error,
          intl.formatMessage({ id: "gateways.createServer.errorFallback" }),
        ),
      );
    } finally {
      setIsCreating(false);
    }
  };

  if (step === "sources") {
    return (
      <main className="bg-background px-6 py-10">
        <SourceSelection
          actionCards={actionCards}
          associatedMCPServerIds={serverDetails?.associatedMCPServerIds}
          createServerActions={{
            onBack: () => setStep("details"),
            onSkip: handleSkipForNow,
            isSkipping: isCreating,
            skipError: createError,
          }}
        />
        {serverDetails && (
          <span className="sr-only" aria-live="polite">
            {intl.formatMessage(
              { id: "gateways.createServer.completedLive" },
              { name: serverDetails.name },
            )}
          </span>
        )}
      </main>
    );
  }

  return (
    <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-background px-6 py-10">
      <div className="w-full max-w-[56rem]">
        <CreateServerForm
          initialValues={serverDetails ?? undefined}
          onCancel={() => navigate("/app/gateways")}
          onSuccess={(details) => {
            setServerDetails(details);
            setCreateError(null);
            setStep("sources");
          }}
        />
      </div>
    </main>
  );
}
