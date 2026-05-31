import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/test-utils";
import { CACertificateUpload } from "./CACertificateUpload";

const MockDataTransfer = class {
  files: File[] = [];
  items = {
    add: (file: File) => {
      this.files.push(file);
      return null;
    },
  } as const;
};

(globalThis as unknown as { DataTransfer: typeof MockDataTransfer }).DataTransfer =
  MockDataTransfer;

describe("CACertificateUpload", () => {
  const onFilesSelected = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens the hidden file input when the Upload button is clicked", async () => {
    renderWithProviders(<CACertificateUpload onFilesSelected={onFilesSelected} />);

    const input = document.querySelector("input[type=file]") as HTMLInputElement;
    const clickSpy = vi.spyOn(input, "click");

    await userEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect(clickSpy).toHaveBeenCalled();
  });

  it("shows an error message when the selected file type is invalid", async () => {
    renderWithProviders(<CACertificateUpload onFilesSelected={onFilesSelected} />);

    const file = new File(["bad content"], "bad.txt", { type: "text/plain" });
    const input = document.querySelector("input[type=file]") as HTMLInputElement;

    await userEvent.upload(input, file);

    expect(onFilesSelected).not.toHaveBeenCalled();
  });

  it("accepts a valid certificate file and calls onFilesSelected", async () => {
    renderWithProviders(<CACertificateUpload onFilesSelected={onFilesSelected} />);

    const file = new File(["certificate-content"], "certificate.pem", {
      type: "application/x-pem-file",
    });
    const input = document.querySelector("input[type=file]") as HTMLInputElement;

    await userEvent.upload(input, file);

    expect(screen.getByText(/1 file\(s\) selected successfully\./)).toBeInTheDocument();
    expect(screen.getByText(/certificate.pem/)).toBeInTheDocument();
    expect(onFilesSelected).toHaveBeenCalledWith([file]);
  });

  it("toggles drag styling while dragging and accepts dropped files", async () => {
    renderWithProviders(<CACertificateUpload onFilesSelected={onFilesSelected} />);

    const dropZoneLabel = screen.getByText(/Public certificate files only/i);
    const dropZone = dropZoneLabel.parentElement as HTMLElement;
    const file = new File(["certificate-content"], "certificate.crt", {
      type: "application/x-x509-ca-certificate",
    });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);

    fireEvent.dragOver(dropZone, { dataTransfer });
    expect(dropZone.className).toContain("border-neutral-400");

    fireEvent.drop(dropZone, { dataTransfer });

    expect(onFilesSelected).toHaveBeenCalledWith([file]);
    expect(screen.getByText(/certificate\.crt/)).toBeInTheDocument();
  });

  it("shows an error when a dropped file is invalid", () => {
    renderWithProviders(<CACertificateUpload onFilesSelected={onFilesSelected} />);

    const dropZoneLabel = screen.getByText(/Public certificate files only/i);
    const dropZone = dropZoneLabel.parentElement as HTMLElement;
    const invalidFile = new File(["text"], "image.png", { type: "image/png" });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(invalidFile);

    fireEvent.drop(dropZone, { dataTransfer });

    expect(screen.getByText(/Invalid file type/i)).toBeInTheDocument();
    expect(onFilesSelected).not.toHaveBeenCalled();
  });
});
