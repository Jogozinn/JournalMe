import { ImageResponse } from "next/og";

import { brand } from "@/config/brand";

export const size = { width: 512, height: 512 };
export const contentType = "image/png";

export default function Icon() {
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
          borderRadius: 112,
        }}
      >
        <div
          style={{
            width: 302,
            height: 326,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `18px solid ${brand.colors.accent}`,
            borderRadius: "40px 84px 40px 40px",
            background: "#151c17",
            color: brand.colors.positive,
            fontSize: 156,
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

