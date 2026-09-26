"use client";

import { type MouseEvent, useEffect, useState } from "react";

import { apiBlob } from "@/lib/api";

export function AuthenticatedImage({
  path,
  alt,
}: {
  path: string;
  alt: string;
}) {
  const [source, setSource] = useState<string>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | undefined;
    setSource(undefined);
    setFailed(false);
    void apiBlob(path)
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setSource(objectUrl);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (failed) return <div className="screenshot-loading muted">Image unavailable</div>;
  if (!source) return <div className="screenshot-loading muted">Loading image…</div>;
  // Blob URLs are created from bytes returned by the authenticated FastAPI API.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={source} alt={alt} />;
}

export function AuthenticatedDownloadLink({
  path,
  filename,
  children,
  className = "button",
  disabled = false,
}: {
  path: string;
  filename: string;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  const [downloading, setDownloading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function download(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    if (disabled || downloading) return;
    setDownloading(true);
    setFailed(false);
    try {
      const objectUrl = URL.createObjectURL(await apiBlob(path));
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch {
      setFailed(true);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <a
      className={`${className}${disabled ? " disabled" : ""}`}
      href="#"
      aria-disabled={disabled}
      onClick={(event) => void download(event)}
    >
      {downloading ? "Preparing…" : failed ? "Download failed" : children}
    </a>
  );
}
