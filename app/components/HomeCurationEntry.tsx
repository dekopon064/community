import CurationCard, { type CurationCardProps } from "@/app/components/CurationCard";

export default function HomeCurationEntry(props: Omit<CurationCardProps, "summaryLabel">) {
  return <CurationCard {...props} />;
}
