import Image from "next/image";

import { brand } from "@/config/brand";

import styles from "./brand-mark.module.css";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`brand-mark ${styles.brandMark} ${compact ? styles.compact : ""}`}
      aria-label={brand.name}
    >
      <Image
        className={styles.fullLogo}
        src="/brand/journalme-logo.png"
        alt=""
        width={1200}
        height={417}
        priority
      />
      <Image
        className={styles.iconLogo}
        src="/brand/journalme-app-icon-192.png"
        alt=""
        width={192}
        height={192}
        priority
      />
    </div>
  );
}
