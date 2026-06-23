import { describe, it, expect } from "vitest";
import { renderWithProviders } from "@/test/test-utils";
import { Agents } from "./Agents";
import { ChangePassword } from "./ChangePassword";
import { ForgotPassword } from "./ForgotPassword";
import { Grpc } from "./Grpc";
import { LLMModels } from "./LLMModels";
import { LLMProviders } from "./LLMProviders";
import { Maintenance } from "./Maintenance";
import { Metrics } from "./Metrics";
import { Observability } from "./Observability";
import { Performance } from "./Performance";
import { Plugins } from "./Plugins";
import { Prompts } from "./Prompts";
import { ResetPassword } from "./ResetPassword";
import { Resources } from "./Resources";
import { RestApi } from "./RestApi";
import { ServerCatalog } from "./ServerCatalog";
import { Settings } from "./Settings";
import { Teams } from "./Teams";
import { Tokens } from "./Tokens";
describe("Simple Page Components", () => {
  it("renders Agents page", () => {
    renderWithProviders(<Agents />);
    expect(document.body).toBeTruthy();
  });

  it("renders ChangePassword page", () => {
    renderWithProviders(<ChangePassword />);
    expect(document.body).toBeTruthy();
  });

  it("renders ForgotPassword page", () => {
    renderWithProviders(<ForgotPassword />);
    expect(document.body).toBeTruthy();
  });

  it("renders Grpc page", () => {
    renderWithProviders(<Grpc />);
    expect(document.body).toBeTruthy();
  });

  it("renders LLMModels page", () => {
    renderWithProviders(<LLMModels />);
    expect(document.body).toBeTruthy();
  });

  it("renders LLMProviders page", () => {
    renderWithProviders(<LLMProviders />);
    expect(document.body).toBeTruthy();
  });

  it("renders Maintenance page", () => {
    renderWithProviders(<Maintenance />);
    expect(document.body).toBeTruthy();
  });

  it("renders Metrics page", () => {
    renderWithProviders(<Metrics />);
    expect(document.body).toBeTruthy();
  });

  it("renders Observability page", () => {
    renderWithProviders(<Observability />);
    expect(document.body).toBeTruthy();
  });

  it("renders Performance page", () => {
    renderWithProviders(<Performance />);
    expect(document.body).toBeTruthy();
  });

  it("renders Plugins page", () => {
    renderWithProviders(<Plugins />);
    expect(document.body).toBeTruthy();
  });

  it("renders Prompts page", () => {
    renderWithProviders(<Prompts />);
    expect(document.body).toBeTruthy();
  });

  it("renders ResetPassword page", () => {
    renderWithProviders(<ResetPassword />);
    expect(document.body).toBeTruthy();
  });

  it("renders Resources page", () => {
    renderWithProviders(<Resources />);
    expect(document.body).toBeTruthy();
  });

  it("renders RestApi page", () => {
    renderWithProviders(<RestApi />);
    expect(document.body).toBeTruthy();
  });

  it("renders ServerCatalog page", () => {
    renderWithProviders(<ServerCatalog />);
    expect(document.body).toBeTruthy();
  });

  it("renders Settings page", () => {
    renderWithProviders(<Settings />);
    expect(document.body).toBeTruthy();
  });

  it("renders Teams page", () => {
    renderWithProviders(<Teams />);
    expect(document.body).toBeTruthy();
  });

  it("renders Tokens page", () => {
    renderWithProviders(<Tokens />);
    expect(document.body).toBeTruthy();
  });
});
