import { Link } from "@/i18n/navigation";

type HomeFeedbackCtaProps = {
  title: string;
  hint: string;
};

export default function HomeFeedbackCta({ title, hint }: HomeFeedbackCtaProps) {
  return (
    <div>
      <Link
        href="/feedback"
        className="inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-2"
      >
        {title}
      </Link>
      <p className="mt-2 max-w-sm text-sm leading-6 text-ink-sub">{hint}</p>
    </div>
  );
}
