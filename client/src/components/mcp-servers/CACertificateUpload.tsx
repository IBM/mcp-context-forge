import { useState, useRef, type DragEvent, type ChangeEvent } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";

interface CACertificateUploadProps {
  onFilesSelected?: (files: File[]) => void;
}

export function CACertificateUpload({ onFilesSelected }: CACertificateUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [feedback, setFeedback] = useState<{ type: "error" | "success"; message: string } | null>(
    null,
  );
  const fileInputRef = useRef<HTMLInputElement>(null);

  const acceptedExtensions = [".pem", ".crt", ".cer", ".cert"];
  const acceptedMimeTypes = ["application/x-x509-ca-certificate", "application/x-pem-file"];

  const validateFiles = (files: FileList | null): File[] => {
    if (!files || files.length === 0) {
      return [];
    }

    const validFiles: File[] = [];
    const invalidFiles: string[] = [];

    Array.from(files).forEach((file) => {
      const extension = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
      const isValidExtension = acceptedExtensions.includes(extension);
      const isValidMimeType = acceptedMimeTypes.includes(file.type) || file.type === "";

      if (isValidExtension || isValidMimeType) {
        validFiles.push(file);
      } else {
        invalidFiles.push(file.name);
      }
    });

    if (invalidFiles.length > 0) {
      setFeedback({
        type: "error",
        message: `Invalid file type(s): ${invalidFiles.join(", ")}. Only .pem, .crt, .cer, .cert files are allowed.`,
      });
    } else if (validFiles.length > 0) {
      setFeedback({
        type: "success",
        message: `${validFiles.length} file(s) selected successfully.`,
      });
    } else {
      setFeedback(null);
    }

    return validFiles;
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    // Clear previous state
    setFeedback(null);
    setSelectedFiles([]);

    const files = event.target.files;
    const validFiles = validateFiles(files);

    if (validFiles.length > 0) {
      setSelectedFiles(validFiles);
      onFilesSelected?.(validFiles);
    }

    // Reset the input value so the same file can be selected again
    event.target.value = "";
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);

    // Clear previous state
    setFeedback(null);
    setSelectedFiles([]);

    const files = event.dataTransfer.files;
    const validFiles = validateFiles(files);

    if (validFiles.length > 0) {
      setSelectedFiles(validFiles);
      onFilesSelected?.(validFiles);
    }
  };

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-neutral-950 dark:text-white">CA certificate</label>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleFileChange}
        accept={acceptedExtensions.join(",")}
        multiple
      />

      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`flex h-24 w-full cursor-pointer flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed transition ${
          isDragging
            ? "border-neutral-400 bg-neutral-100 dark:border-neutral-500 dark:bg-neutral-800/60"
            : "border-neutral-300 bg-transparent hover:border-neutral-400 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:border-neutral-600 dark:hover:bg-neutral-800/40"
        }`}
      >
        <Button
          type="button"
          onClick={handleClick}
          variant="default"
          size="sm"
          className="h-7 gap-2 border border-neutral-700 bg-neutral-800 text-white hover:bg-neutral-700 dark:border-neutral-800 dark:bg-neutral-950 dark:hover:bg-neutral-800"
        >
          <Upload className="h-3 w-3" />
          Upload
        </Button>
        <p className="pt-1 text-xs text-neutral-500 dark:text-neutral-400">
          Public certificate files only (.pem, .crt, .cer, .cert)
        </p>
      </div>

      {feedback && (
        <div
          className={`text-sm ${
            feedback.type === "error"
              ? "text-red-600 dark:text-red-400"
              : "text-green-600 dark:text-green-400"
          }`}
        >
          {feedback.message}
        </div>
      )}

      {selectedFiles.length > 0 && (
        <div className="text-xs text-neutral-600 dark:text-neutral-400">
          Selected: {selectedFiles.map((f) => f.name).join(", ")}
        </div>
      )}
    </div>
  );
}
