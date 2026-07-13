import { useState, useEffect } from "react";
import { useIntl } from "react-intl";
import { ChevronDown, Copy, RefreshCw, Wrench, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ToolAdvancedSettings } from "@/components/tools/ToolAdvancedSettings";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";
import { useToolForm, type RequestType, type SchemaMode, type AuthType } from "@/hooks/useToolForm";
import type { Tool } from "@/types/tool";
import type { Visibility } from "@/types/server";

const AUTH_TYPE_FROM_API: Partial<Record<string, AuthType>> = {
  basic: "basic",
  bearer: "bearer",
  authheaders: "custom",
};

function toolToInitialValues(tool: Tool) {
  const authType: AuthType = AUTH_TYPE_FROM_API[tool.auth?.authType ?? ""] ?? "none";
  const customHeaders =
    tool.auth?.authHeaders && tool.auth.authHeaders.length > 0
      ? tool.auth.authHeaders.map((h, i) => ({ id: String(i + 1), key: h.key, value: h.value }))
      : tool.auth?.authHeaderKey
        ? [{ id: "1", key: tool.auth.authHeaderKey, value: tool.auth.authHeaderValue ?? "" }]
        : [];

  return {
    name: tool.customName || tool.originalName,
    url: tool.url ?? "",
    description: tool.description ?? "",
    requestType: tool.requestType as RequestType,
    integrationType: tool.integrationType,
    inputSchema: tool.inputSchema ? JSON.stringify(tool.inputSchema, null, 2) : "",
    outputSchema: tool.outputSchema ? JSON.stringify(tool.outputSchema, null, 2) : "",
    schemaMode: (tool.inputSchema || tool.outputSchema ? "manual" : "none") as SchemaMode,
    tags: (tool.tags || []).map((t) => (typeof t === "string" ? t : t.label)).join(", "),
    visibility: (tool.visibility || "public") as Visibility,
    teamId: tool.teamId ?? "",
    authType,
    authUsername: tool.auth?.username ?? "",
    authPassword: tool.auth?.password ?? "",
    bearerToken: tool.auth?.token ?? "",
    customHeaders,
    advancedOpen: Boolean(
      tool.description ||
      (tool.tags && tool.tags.length > 0) ||
      tool.visibility !== "public" ||
      tool.teamId ||
      authType !== "none",
    ),
  };
}

interface ToolFormProps {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess?: () => void;
  tool?: Tool;
}

export function ToolForm({ isOpen, onToggle, onSuccess, tool }: ToolFormProps) {
  const intl = useIntl();
  const [copiedInput, setCopiedInput] = useState(false);
  const [copiedOutput, setCopiedOutput] = useState(false);
  const [showOverwriteConfirm, setShowOverwriteConfirm] = useState(false);

  const isEditMode = Boolean(tool);

  const initialValues = tool ? toolToInitialValues(tool) : undefined;

  const {
    name,
    url,
    description,
    requestType,
    integrationType,
    advancedOpen,
    visibility,
    teamId,
    authType,
    authUsername,
    authPassword,
    bearerToken,
    customHeaders,
    responseFilter,
    tags,
    inputSchema,
    outputSchema,
    isGeneratingSchema,
    schemaMode,
    openApiSpecUrl,
    showSpecUrlInput,
    generatedSpecUrl,
    errors,
    isValid,
    isSubmitting,
    setName,
    setUrl,
    setDescription,
    setRequestType,
    setAdvancedOpen,
    setVisibility,
    setTeamId,
    setAuthType,
    setAuthUsername,
    setAuthPassword,
    setBearerToken,
    setCustomHeaders,
    setResponseFilter,
    setTags,
    setInputSchema,
    setOutputSchema,
    setSchemaMode,
    setOpenApiSpecUrl,
    generateSchema,
    handleSubmit,
  } = useToolForm({ maxCustomHeaders: 1, toolId: tool?.id, initialValues });

  // When the full tool is fetched in the background, update auth fields only
  useEffect(() => {
    if (!tool?.auth?.authType) return;
    const newAuthType: AuthType = AUTH_TYPE_FROM_API[tool.auth.authType] ?? "none";
    setAuthType(newAuthType);
    setAuthUsername(tool.auth.username ?? "");
    setAuthPassword(tool.auth.password ?? "");
    setBearerToken(tool.auth.token ?? "");
    if (newAuthType !== "none") setAdvancedOpen(true);
    const headers =
      tool.auth.authHeaders && tool.auth.authHeaders.length > 0
        ? tool.auth.authHeaders.map((h, i) => ({ id: String(i + 1), key: h.key, value: h.value }))
        : tool.auth.authHeaderKey
          ? [{ id: "1", key: tool.auth.authHeaderKey, value: tool.auth.authHeaderValue ?? "" }]
          : [];
    if (headers.length > 0) setCustomHeaders(headers);
  }, [
    tool,
    setAuthType,
    setAuthUsername,
    setAuthPassword,
    setBearerToken,
    setAdvancedOpen,
    setCustomHeaders,
  ]);

  const handleCopy = (text: string, setCopied: (v: boolean) => void) => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const handleCancel = () => {
    onToggle();
  };

  // Schema generation reads an OpenAPI spec, so it only applies to REST tools.
  // This form only ever creates REST tools, so "MCP" appears only when editing.
  const showGenerate = integrationType === "REST";

  // Guard against silently clobbering schemas the user has already entered:
  // confirm first whenever either schema field is non-empty.
  const handleGenerateClick = () => {
    if (inputSchema.trim() || outputSchema.trim()) {
      setShowOverwriteConfirm(true);
    } else {
      void generateSchema();
    }
  };

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    handleSubmit(event, () => {
      if (onSuccess) {
        onSuccess();
      } else {
        onToggle();
      }
    });
  };

  if (!isOpen) return null;

  return (
    <>
      <div className="mx-auto mt-6 w-full max-w-3xl rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-8 p-6 sm:p-8">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-purple-500 shadow-sm">
                <Wrench className="h-4 w-4 text-black" />
              </div>
              <h2 className="text-lg font-semibold tracking-tight text-neutral-950 dark:text-neutral-50">
                {isEditMode
                  ? intl.formatMessage({ id: "tools.form.heading.edit" })
                  : intl.formatMessage({ id: "tools.form.heading.add" })}
              </h2>
            </div>

            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "tools.form.description" })}
            </p>
          </div>

          <form className="space-y-6" onSubmit={onSubmit}>
            {integrationType !== "MCP" && (
              <div className="space-y-3">
                <label
                  id="request-type-label"
                  className="text-sm font-medium text-neutral-950 dark:text-white"
                >
                  {intl.formatMessage({ id: "tools.form.requestType" })}
                </label>
                <div
                  role="radiogroup"
                  aria-labelledby="request-type-label"
                  className="flex gap-2 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800"
                >
                  {(["GET", "POST", "PUT", "PATCH", "DELETE"] as RequestType[]).map((type) => {
                    return (
                      <div key={type} className="flex-1">
                        <input
                          type="radio"
                          id={`request-${type}`}
                          name="requestType"
                          value={type}
                          checked={requestType === type}
                          onChange={(e) => setRequestType(e.target.value as RequestType)}
                          className="peer sr-only"
                        />
                        <label
                          htmlFor={`request-${type}`}
                          className="flex cursor-pointer items-center justify-center rounded-md px-4 py-1 text-sm font-medium text-neutral-500 transition hover:bg-neutral-200 hover:text-neutral-700 peer-checked:bg-neutral-800 peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 dark:text-neutral-400 dark:hover:bg-neutral-900 dark:hover:text-neutral-300 dark:peer-checked:bg-neutral-950 dark:peer-checked:text-white"
                        >
                          {type}
                        </label>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="space-y-1">
              <label
                htmlFor="tool-name"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "tools.form.name" })}
                <span className="text-red-500">*</span>
                <span className="sr-only">{intl.formatMessage({ id: "tools.form.required" })}</span>
              </label>
              <Input
                id="tool-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={intl.formatMessage({ id: "tools.form.name.placeholder" })}
                className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? "name-error" : undefined}
              />
              {errors.name && (
                <p id="name-error" className="text-sm text-red-500">
                  {errors.name}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label
                htmlFor="tool-url"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                {intl.formatMessage({ id: "tools.form.url" })}
                <span className="text-red-500">*</span>
                <span className="sr-only">{intl.formatMessage({ id: "tools.form.required" })}</span>
              </label>
              <Input
                id="tool-url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder={intl.formatMessage({ id: "tools.form.url.placeholder" })}
                className="rounded-md border-neutral-300 px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                aria-invalid={!!errors.url}
                aria-describedby={errors.url ? "url-error" : undefined}
              />
              {errors.url && (
                <p id="url-error" className="text-sm text-red-500">
                  {errors.url}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-5 pt-2">
              <div className="space-y-3">
                <label className="text-sm font-medium text-neutral-950 dark:text-white">
                  {intl.formatMessage({ id: "tools.form.schema" })}
                  <span className="text-red-500">*</span>
                  <span className="sr-only">
                    {intl.formatMessage({ id: "tools.form.required" })}
                  </span>
                </label>
                <p className="text-sm text-neutral-600 dark:text-neutral-400">
                  {intl.formatMessage({ id: "tools.form.schema.description" })}
                </p>
                {/* Generate reads an OpenAPI spec (REST only); "Add manually"
                    reveals the fields in add-mode (when editing they're always
                    shown below). */}
                {showGenerate && (
                  <div className="flex gap-3">
                    <Button
                      type="button"
                      variant="outline"
                      className="flex-1 gap-2"
                      disabled={isGeneratingSchema || !url.trim() || !requestType}
                      onClick={handleGenerateClick}
                    >
                      {schemaMode === "generated" ? (
                        <RefreshCw
                          className={`h-4 w-4 ${isGeneratingSchema ? "animate-spin" : ""}`}
                        />
                      ) : (
                        <Zap className={`h-4 w-4 ${isGeneratingSchema ? "animate-pulse" : ""}`} />
                      )}
                      {isGeneratingSchema
                        ? intl.formatMessage({ id: "tools.form.schema.generating" })
                        : schemaMode === "generated"
                          ? intl.formatMessage({ id: "tools.form.schema.regenerate" })
                          : intl.formatMessage({ id: "tools.form.schema.generate" })}
                    </Button>
                    {!isEditMode && (
                      <Button
                        type="button"
                        variant="ghost"
                        className="flex-1"
                        onClick={() => {
                          setSchemaMode("manual");
                          if (!inputSchema.trim()) {
                            setInputSchema('{\n  "type": "object",\n  "properties": {}\n}');
                          }
                        }}
                      >
                        {intl.formatMessage({ id: "tools.form.schema.addManually" })}
                      </Button>
                    )}
                  </div>
                )}

                {schemaMode === "generated" && generatedSpecUrl && !errors.schema && (
                  <p aria-live="polite" className="text-xs text-neutral-500 dark:text-neutral-400">
                    {intl.formatMessage(
                      { id: "tools.form.schema.generatedFrom" },
                      { specUrl: generatedSpecUrl },
                    )}
                  </p>
                )}

                {errors.schema && (
                  <div className="space-y-2">
                    <p role="alert" aria-live="assertive" className="text-sm text-red-500">
                      {errors.schema}
                    </p>
                    {showSpecUrlInput && (
                      <div className="space-y-1">
                        <label
                          htmlFor="openapi-spec-url"
                          className="text-xs font-medium text-neutral-600 dark:text-neutral-400"
                        >
                          {intl.formatMessage({ id: "tools.form.schema.specUrlLabel" })}
                        </label>
                        <Input
                          id="openapi-spec-url"
                          value={openApiSpecUrl}
                          onChange={(e) => setOpenApiSpecUrl(e.target.value)}
                          placeholder={intl.formatMessage({
                            id: "tools.form.schema.specUrlPlaceholder",
                          })}
                          className="h-8 rounded-md border-neutral-300 px-3 text-xs text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                        />
                      </div>
                    )}
                  </div>
                )}

                {/* In edit mode the schemas are the thing being edited, so the
                    fields are always visible even when empty. */}
                {(isEditMode || schemaMode !== "none") && (
                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <label
                        htmlFor="input-schema"
                        className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
                      >
                        {intl.formatMessage({ id: "tools.form.inputSchema" })}
                        <span className="text-red-500">*</span>
                        <span className="sr-only">
                          {intl.formatMessage({ id: "tools.form.required" })}
                        </span>
                      </label>
                      <div className="relative">
                        <Textarea
                          id="input-schema"
                          value={inputSchema}
                          onChange={(e) => setInputSchema(e.target.value)}
                          className="min-h-40 pr-9 font-mono text-xs focus-visible:ring-1 focus-visible:ring-offset-0"
                          placeholder={'{\n  "type": "object",\n  "properties": {}\n}'}
                          spellCheck={false}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          aria-label={intl.formatMessage({ id: "tools.form.copyInputSchema" })}
                          className="absolute right-2 top-2 h-6 w-6 p-0 opacity-60 hover:opacity-100"
                          onClick={() => handleCopy(inputSchema, setCopiedInput)}
                        >
                          <Copy className="h-3.5 w-3.5" />
                          {copiedInput && (
                            <span className="sr-only">
                              {intl.formatMessage({ id: "tools.form.copied" })}
                            </span>
                          )}
                        </Button>
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <label
                        htmlFor="output-schema"
                        className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
                      >
                        {intl.formatMessage({ id: "tools.form.outputSchema" })}
                      </label>
                      <div className="relative">
                        <Textarea
                          id="output-schema"
                          value={outputSchema}
                          onChange={(e) => setOutputSchema(e.target.value)}
                          className="min-h-40 pr-9 font-mono text-xs focus-visible:ring-1 focus-visible:ring-offset-0"
                          placeholder={'{\n  "type": "object",\n  "properties": {}\n}'}
                          spellCheck={false}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          aria-label={intl.formatMessage({ id: "tools.form.copyOutputSchema" })}
                          className="absolute right-2 top-2 h-6 w-6 p-0 opacity-60 hover:opacity-100"
                          onClick={() => handleCopy(outputSchema, setCopiedOutput)}
                        >
                          <Copy className="h-3.5 w-3.5" />
                          {copiedOutput && (
                            <span className="sr-only">
                              {intl.formatMessage({ id: "tools.form.copied" })}
                            </span>
                          )}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <button
                type="button"
                onClick={() => setAdvancedOpen((current) => !current)}
                className="inline-flex w-full items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-600 transition hover:text-neutral-950 dark:border-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-300"
                aria-expanded={advancedOpen}
                aria-controls="advanced-settings-panel"
              >
                <ChevronDown className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`} />
                {intl.formatMessage({ id: "tools.form.advancedSettings" })}
              </button>

              {advancedOpen && (
                <div id="advanced-settings-panel">
                  <ToolAdvancedSettings
                    visibility={visibility}
                    onVisibilityChange={setVisibility}
                    teamId={teamId}
                    onTeamIdChange={setTeamId}
                    authType={authType}
                    onAuthTypeChange={setAuthType}
                    basicAuthUsername={authUsername}
                    basicAuthPassword={authPassword}
                    onBasicAuthUsernameChange={setAuthUsername}
                    onBasicAuthPasswordChange={setAuthPassword}
                    bearerToken={bearerToken}
                    onBearerTokenChange={setBearerToken}
                    customHeaders={customHeaders}
                    onCustomHeadersChange={setCustomHeaders}
                    responseFilter={responseFilter}
                    onResponseFilterChange={setResponseFilter}
                    tags={tags}
                    onTagsChange={setTags}
                    description={description}
                    onDescriptionChange={setDescription}
                  />
                </div>
              )}

              {errors.submit && (
                <div
                  role="alert"
                  aria-live="assertive"
                  className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/50 dark:bg-red-950/50"
                >
                  <p className="text-sm text-red-600 dark:text-red-400">{errors.submit}</p>
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-6">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => handleCancel()}
                  className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
                >
                  {intl.formatMessage({ id: "tools.form.cancel" })}
                </Button>
                <Button
                  type="submit"
                  disabled={!isValid || isSubmitting}
                  className="h-10 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:enabled:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-950 dark:hover:enabled:bg-neutral-200"
                >
                  {isSubmitting
                    ? isEditMode
                      ? intl.formatMessage({ id: "tools.form.button.updating" })
                      : intl.formatMessage({ id: "tools.form.button.adding" })
                    : isEditMode
                      ? intl.formatMessage({ id: "tools.form.button.update" })
                      : intl.formatMessage({ id: "tools.form.button.add" })}
                </Button>
              </div>
            </div>
          </form>
        </div>
      </div>

      <ConfirmDialog
        open={showOverwriteConfirm}
        onOpenChange={setShowOverwriteConfirm}
        title={intl.formatMessage({ id: "tools.form.schema.overwrite.title" })}
        description={intl.formatMessage({ id: "tools.form.schema.overwrite.description" })}
        confirmLabel={intl.formatMessage({ id: "tools.form.schema.overwrite.confirm" })}
        cancelLabel={intl.formatMessage({ id: "tools.form.cancel" })}
        onConfirm={() => void generateSchema()}
      />
    </>
  );
}
