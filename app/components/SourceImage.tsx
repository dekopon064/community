"use client";

import Image from "next/image";
import { useState } from "react";
import { sourceImageUrl } from "@/app/lib/sourceImages";
import styles from "./SourceImage.module.css";

interface Props {
  url?: string | null;
  title: string;
  locale: string;
  variant?: "thumbnail" | "detail";
}

export default function SourceImage({ url, title, locale, variant = "thumbnail" }: Props) {
  const src = sourceImageUrl(url);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  if (!src || failedSrc === src) return null;
  const japanese = locale === "ja";
  const image = (
    <Image
      key={src}
      src={src}
      alt={variant === "detail" ? `${japanese ? "提供元の画像" : "수집원 제공 이미지"}: ${title}` : ""}
      fill
      unoptimized
      referrerPolicy="no-referrer"
      loading="lazy"
      className={styles.image}
      onError={() => setFailedSrc(src)}
    />
  );
  if (variant === "thumbnail") return <span className={styles.thumbnail}>{image}</span>;
  return (
    <figure className={styles.detail}>
      <a className={styles.frame} href={src} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
        {image}
        <span className="sr-only">{japanese ? "提供元の画像を別のタブで開く" : "수집원 이미지를 새 탭에서 열기"}</span>
      </a>
      <figcaption className={styles.caption}>{japanese ? "提供元の画像 · 原文の言語" : "수집원 제공 이미지 · 원문 언어"}</figcaption>
    </figure>
  );
}
