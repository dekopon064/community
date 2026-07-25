import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

// locale을 자동으로 처리하는 네비게이션 래퍼 (Link, useRouter, usePathname 등)
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
