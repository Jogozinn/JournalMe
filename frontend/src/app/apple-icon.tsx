import { ImageResponse } from "next/og";

import { brand } from "@/config/brand";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: brand.colors.background,
        }}
      >
        <div
          style={{
            width: 112,
            height: 120,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `7px solid ${brand.colors.accent}`,
            borderRadius: "15px 30px 15px 15px",
            background: "#151c17",
            color: brand.colors.positive,
            fontSize: 58,
            fontWeight: 700,
          }}
        >
          ↗
        </div>
      </div>
    ),
    size,
  );
}

