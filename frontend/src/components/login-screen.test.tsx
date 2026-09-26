import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginScreen } from "@/components/login-screen";

const replace = vi.fn();
const signIn = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh: vi.fn() }),
}));

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ error: null, signIn }),
}));

describe("JournalMe login screen", () => {
  beforeEach(() => {
    replace.mockReset();
    signIn.mockReset().mockResolvedValue(undefined);
  });

  it("submits email/password through the auth session boundary", async () => {
    render(<LoginScreen />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "trader@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => {
      expect(signIn).toHaveBeenCalledWith("trader@example.com", "secret");
      expect(replace).toHaveBeenCalledWith("/");
    });
  });
});
