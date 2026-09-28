import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrandMark } from "@/components/brand-mark";

describe("BrandMark", () => {
  it("uses the JournalMe product name", () => {
    render(<BrandMark />);
    expect(screen.getByLabelText("JournalMe")).toBeInTheDocument();
  });
});
