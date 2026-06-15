import { useState } from "react";
import { PromptIcon } from "@/components/icons/PromptIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { usePromptForm } from "@/hooks/usePromptForm";
import { useRouter } from "@/router";
import { MoreVertical, Plus } from "lucide-react";


export function CreatePrompt() {
  const { navigate } = useRouter();
  const [newVariableName, setNewVariableName] = useState("");
  const [showVariableInput, setShowVariableInput] = useState(false);
  const {
    name,
    template,
    variables,
    errors,
    isValid,
    isSubmitting,
    setName,
    setTemplate,
    deleteVariable,
    addVariable,
    handleSubmit,
  } = usePromptForm();

  const handleCancel = () => {
    navigate("/app/prompts");
  };

  const handleAddVariable = () => {
    if (newVariableName.trim()) {
      const added = addVariable(newVariableName.trim());
      if (added) {
        setNewVariableName("");
        setShowVariableInput(false);
      }
    }
  };

  const handlePlusClick = () => {
    setShowVariableInput(true);
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddVariable();
    }
  };

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    handleSubmit(event, () => {
      navigate("/app/prompts");
    });
  };

  return (
    <div className="p-6">
      <div className="mx-auto w-full max-w-2xl rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-8 p-6 sm:p-8">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-indigo-500 text-white shadow-sm">
                <PromptIcon className="h-4 w-4" />
              </div>
              <h2 className="text-lg font-semibold tracking-tight text-neutral-950 dark:text-neutral-50">
                Add Prompt
              </h2>
            </div>
          </div>

          <form className="space-y-6" onSubmit={onSubmit}>
            <div className="space-y-1">
              <label
                htmlFor="prompt-name"
                className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                Name
              </label>
              <Input
                id="prompt-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Enter prompt name..."
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
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
                htmlFor="prompt-template"
                className="text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                Template
              </label>
              <Textarea
                id="prompt-template"
                value={template}
                onChange={(event) => setTemplate(event.target.value)}
                className="min-h-32 focus-visible:ring-1 focus-visible:ring-offset-0"
                aria-invalid={!!errors.template}
                aria-describedby={errors.template ? "template-error" : undefined}
              />
              {errors.template && (
                <p id="template-error" className="text-sm text-red-500">
                  {errors.template}
                </p>
              )}
            </div>

            <div className="space-y-3">
              <div className="rounded-lg bg-neutral-100 p-3 dark:bg-neutral-900">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                    Variables
                  </label>
                  <div className="flex items-center gap-2">
                    {showVariableInput && (
                      <Input
                        value={newVariableName}
                        onChange={(e) => setNewVariableName(e.target.value)}
                        onKeyPress={handleKeyPress}
                        placeholder="Add variable..."
                        className="h-8 w-40 rounded-md border-neutral-300 bg-white px-3 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 dark:placeholder:text-neutral-500"
                        autoFocus
                      />
                    )}
                    <Button
                      type="button"
                      onClick={showVariableInput ? handleAddVariable : handlePlusClick}
                      disabled={showVariableInput && !newVariableName.trim()}
                      className="h-7 w-7 rounded-md bg-neutral-300 p-0 text-neutral-600 hover:enabled:bg-neutral-400 hover:enabled:text-neutral-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-neutral-700 dark:text-neutral-400 dark:hover:enabled:bg-neutral-600 dark:hover:enabled:text-neutral-200"
                      aria-label="Add variable"
                    >
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                {errors.variable && <p className="text-sm text-red-500 mt-2">{errors.variable}</p>}

                {variables.length > 0 && (
                  <div className="space-y-2 mt-3">
                  {variables.map((variable) => (
                    <div
                      key={variable.name}
                      className="flex items-center gap-3 rounded-md px-3 py-2"
                    >
                      <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-neutral-300 dark:bg-neutral-700">
                        <span className="text-[10px] font-medium text-neutral-600 dark:text-neutral-400">
                          abc
                        </span>
                      </div>
                      <span className="flex-1 text-sm font-medium text-neutral-900 dark:text-neutral-100">
                        {variable.name}
                      </span>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-5 w-5 shrink-0 rounded p-0 hover:bg-neutral-300 dark:hover:bg-neutral-700"
                            aria-label={`Options for ${variable.name}`}
                          >
                            <MoreVertical className="h-3.5 w-3.5 text-neutral-600 dark:text-neutral-400" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-32">
                          <DropdownMenuItem
                            onClick={() => {
                              // TODO: Implement edit functionality
                            }}
                          >
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => deleteVariable(variable.name)}
                          >
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  ))}
                  </div>
                )}
              </div>
            </div>

            {errors.submit && (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/50 dark:bg-red-950/50">
                <p className="text-sm text-red-600 dark:text-red-400">{errors.submit}</p>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-6">
              <Button
                type="button"
                variant="ghost"
                onClick={handleCancel}
                className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!isValid || isSubmitting}
                className="h-10 rounded-md bg-white px-4 text-sm font-medium text-neutral-950 hover:enabled:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-neutral-950 dark:hover:enabled:bg-neutral-100"
              >
                {"Add"}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
