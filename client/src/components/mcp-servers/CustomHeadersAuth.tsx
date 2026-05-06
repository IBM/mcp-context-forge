import { Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export interface CustomHeader {
  id: string;
  key: string;
  value: string;
}

interface CustomHeadersAuthProps {
  headers: CustomHeader[];
  onHeadersChange: (headers: CustomHeader[]) => void;
}

export function CustomHeadersAuth({ headers, onHeadersChange }: CustomHeadersAuthProps) {
  const addHeader = () => {
    onHeadersChange([...headers, { id: crypto.randomUUID(), key: "", value: "" }]);
  };

  const removeHeader = (index: number) => {
    onHeadersChange(headers.filter((_, i) => i !== index));
  };

  const updateHeader = (index: number, field: "key" | "value", value: string) => {
    const newHeaders = [...headers];
    newHeaders[index] = { ...newHeaders[index], [field]: value };
    onHeadersChange(newHeaders);
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Send one or more custom headers with every request.
      </p>

      <div className="space-y-3">
        {headers.map((header, index) => (
          <div key={header.id} className="flex items-end gap-3">
            <div className="flex-1 space-y-1">
              <label
                htmlFor={`header-key-${index}`}
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                Header key<span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <Input
                id={`header-key-${index}`}
                type="text"
                value={header.key}
                onChange={(e) => updateHeader(index, "key", e.target.value)}
                placeholder={
                  index === 0 && headers.length === 1 ? "e.g. X-API-Key..." : "Add header key..."
                }
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
              />
            </div>

            <div className="flex-1 space-y-1">
              <label
                htmlFor={`header-value-${index}`}
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                Value<span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <Input
                id={`header-value-${index}`}
                type="text"
                value={header.value}
                onChange={(e) => updateHeader(index, "value", e.target.value)}
                placeholder={"Add header value..."}
                className="rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
              />
            </div>

            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removeHeader(index)}
              className="h-10 gap-2 text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-950/50 dark:hover:text-red-300"
            >
              <Trash2 className="h-4 w-4" />
              Remove
            </Button>
          </div>
        ))}
      </div>

      <Button
        type="button"
        variant="default"
        size="sm"
        onClick={addHeader}
        className="h-7 gap-2 border border-neutral-700 bg-neutral-800 text-white hover:bg-neutral-700 dark:border-neutral-800 dark:bg-neutral-950 dark:hover:bg-neutral-800"
      >
        <span className="text-lg leading-none">+</span>
        Add header
      </Button>
    </div>
  );
}
