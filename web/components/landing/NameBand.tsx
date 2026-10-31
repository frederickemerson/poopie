import { Otto } from "./Otto";

/**
 * What the name stands for, and what each part of it promises.
 *
 * The expansion is not decoration: each of the three glossed terms is a claim
 * the engine actually keeps, and the gloss says how. Read together they are the
 * shortest honest description of the product.
 */
const GLOSS: readonly { readonly term: string; readonly body: string }[] = [
  {
    term: "Plane operations",
    body: "Built for the operating fleet rather than the library. Every verdict is decided for one tail number, because two aircraft of the same model routinely land on opposite sides of the same directive.",
  },
  {
    term: "Original parts",
    body: "Applicability turns on what is actually fitted — serial ranges, part numbers, modification state — not just the model on the certificate. Each of those conditions is evaluated on its own and shown with its outcome.",
  },
  {
    term: "Indexing engine",
    body: "The directives themselves, indexed and searched in about a tenth of a second. Every sentence in an answer is held to the paragraph it cites, word for word, or deleted before it reaches you.",
  },
];

export function NameBand() {
  return (
    <div className="grid items-center gap-x-12 gap-y-8 lg:grid-cols-[auto_minmax(0,1fr)]">
      <Otto size={132} className="mx-auto lg:mx-0" />

      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <span className="t-label text-ink-2">poopie stands for</span>
          <p className="t-heading text-ink">
            <Initial>P</Initial>lane <Initial>O</Initial>perations &amp;{" "}
            <Initial>O</Initial>riginal <Initial>P</Initial>arts{" "}
            <Initial>I</Initial>ndexing <Initial>E</Initial>ngine
          </p>
        </div>

        <dl className="grid gap-px border border-line-strong bg-line-strong">
          {GLOSS.map((g) => (
            <div key={g.term} className="flex flex-col gap-1 bg-raised px-4 py-3.5">
              <dt className="t-label text-accent">{g.term}</dt>
              <dd className="t-body max-w-[62ch] text-ink-2">{g.body}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

/** The letter the name is built from, marked without being shouted. */
function Initial({ children }: { children: string }) {
  return <span className="text-accent">{children}</span>;
}
