/**
 * /library - the documents the user loaded into the engine.
 *
 * The engine ships with 2,117 adopted FAA airworthiness directives. This page
 * is how that stops being the whole world: load another regulation, a CFR part,
 * a service bulletin, a foreign AD, your own notes, and the engine indexes and
 * cites them.
 *
 * The page's first section is the trust boundary, not the upload form, and that
 * ordering is the argument. A library screen that leads with "add a document"
 * and lists titles beside a stage implies the engine now treats them as law. It
 * does not, it cannot, and saying so is the first thing on screen.
 */
import Link from "next/link";
import { LibraryPanel } from "@/components/library/LibraryPanel";

export const metadata = {
  title: "Library — documents you loaded",
  description:
    "Add your own source documents to the airworthiness directive engine: searchable and citable, never a basis for a compliance obligation.",
};

export default function LibraryPage() {
  return (
    <main className="mx-auto w-full max-w-[72rem] px-4 py-10 sm:px-8">
      <header className="mb-8">
        <p className="t-label mb-2">
          <Link href="/" className="underline decoration-line underline-offset-4">
            poopie
          </Link>{" "}
          / library
        </p>
        <h1 className="t-display mb-3">Your documents</h1>
        <p className="t-answer text-ink-2">
          The engine answers from 2,117 adopted FAA airworthiness directives. Add your own material
          here and it becomes searchable and citable beside them &mdash; clearly attributed to you,
          and never mistaken for a rule.
        </p>
      </header>
      <LibraryPanel />
    </main>
  );
}
