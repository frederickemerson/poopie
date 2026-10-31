"use client";

/**
 * The library: what is loaded, how to load more, and what it is searchable for.
 *
 * One client component because the three parts share one piece of state -- the
 * listing -- and an upload has to refresh it. The pieces are small and are
 * composed below rather than split across files that would only ever be used
 * together here.
 *
 * The screen states the trust boundary twice, by design. Once at the top, as
 * the standing rule, and once per result, as the reason that result cannot
 * answer a compliance question. A list of titles and stages with no such line
 * would invite precisely the reading the engine refuses to make.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { DocumentStage } from "@/lib/contract";
import {
  humanBytes,
  type LibraryDocument,
  type LibraryHit,
  type LibraryLimits,
  type LibraryListing,
  type LibrarySearchResult,
  type LibraryStatus,
} from "./types";

const DEFAULT_STAGE: DocumentStage = "UNKNOWN";

const STAGE_HELP: Readonly<Record<DocumentStage, string>> = {
  PROPOSED: "a draft or proposal, imposing nothing",
  ADOPTED_NOT_YET_EFFECTIVE: "issued, with a future effective date",
  EFFECTIVE: "in force, in its own jurisdiction",
  SUPERSEDED: "replaced by a later issue",
  UNKNOWN: "you cannot tell, or it does not apply",
};

interface FormState {
  readonly title: string;
  readonly authority: string;
  readonly stage: DocumentStage;
  readonly filename: string;
  readonly content: string;
}

const EMPTY_FORM: FormState = {
  title: "",
  authority: "",
  stage: DEFAULT_STAGE,
  filename: "",
  content: "",
};

export function LibraryPanel() {
  const [listing, setListing] = useState<LibraryListing | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/library", { cache: "no-store" });
      setListing((await response.json()) as LibraryListing);
    } catch (error: unknown) {
      setListing({
        documents: [],
        error: error instanceof Error ? error.message : "could not reach /api/library",
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const pickFile = useCallback(async (file: File | undefined) => {
    if (file === undefined) return;
    const text = await file.text();
    setForm((previous) => ({
      ...previous,
      filename: file.name,
      content: text,
      title: previous.title === "" ? file.name.replace(/\.[^.]+$/, "") : previous.title,
    }));
  }, []);

  const submit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setBusy(true);
      setNotice(null);
      try {
        const response = await fetch("/api/library", {
          method: "POST",
          headers: { "content-type": "application/json" },
          // media_type is deliberately not sent: the engine resolves the type
          // from the filename extension, and a browser's own guess for .md
          // varies by platform. One authority, no disagreement to resolve.
          body: JSON.stringify({
            title: form.title,
            authority: form.authority,
            document_stage: form.stage,
            filename: form.filename,
            content: form.content,
          }),
        });
        const payload = (await response.json()) as Record<string, unknown>;
        if (!response.ok) {
          setNotice({ kind: "bad", text: String(payload.error ?? `engine returned ${response.status}`) });
          return;
        }
        const status = String(payload.status ?? "loaded");
        setNotice({
          kind: "ok",
          text:
            status === "already_loaded"
              ? String(payload.detail ?? "these exact bytes are already loaded")
              : `loaded as ${String(payload.user_document_id)} (${String(payload.paragraphs)} paragraphs). It is searchable now, and it cannot establish an obligation.`,
        });
        setForm(EMPTY_FORM);
        if (fileInput.current !== null) fileInput.current.value = "";
        await refresh();
      } catch (error: unknown) {
        setNotice({ kind: "bad", text: error instanceof Error ? error.message : "upload failed" });
      } finally {
        setBusy(false);
      }
    },
    [form, refresh],
  );

  const documents = listing?.documents ?? [];
  const limits = listing?.limits;
  const ready = form.content.trim() !== "" && form.title.trim() !== "" && form.authority.trim() !== "";

  return (
    <div className="flex flex-col gap-8">
      <Boundary status={listing?.status} error={listing?.error} />

      <section aria-labelledby="add-heading" className="rounded border border-line bg-raised p-5">
        <h2 id="add-heading" className="t-subhead mb-1">
          Add a document
        </h2>
        <p className="t-caption mb-5 max-w-[68ch]">
          Plain text, Markdown or XML, up to {humanBytes(limits?.max_bytes ?? 2 * 1024 * 1024)}. No
          PDF: pulling text out of one needs a layout engine, and a citation whose offsets came from
          a guessed reading order is not a citation.
        </p>

        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          <Field label="Title" hint="How you want it cited.">
            <input
              required
              value={form.title}
              maxLength={200}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="Boeing SB 737-54A1111 Revision 2"
              className="w-full rounded border border-line bg-bg px-3 py-2 text-ink outline-none focus-visible:border-ink-3"
            />
          </Field>

          <Field label="Issuing authority" hint="Whoever published it. Your words; nothing is derived from them.">
            <input
              required
              value={form.authority}
              maxLength={120}
              onChange={(event) => setForm({ ...form, authority: event.target.value })}
              placeholder="Boeing Commercial Airplanes"
              className="w-full rounded border border-line bg-bg px-3 py-2 text-ink outline-none focus-visible:border-ink-3"
            />
          </Field>

          <Field label="Stage" hint={`Your claim about it: ${STAGE_HELP[form.stage]}. It is recorded, and it grants nothing.`}>
            <select
              value={form.stage}
              onChange={(event) => setForm({ ...form, stage: event.target.value as DocumentStage })}
              className="w-full rounded border border-line bg-bg px-3 py-2 text-ink outline-none focus-visible:border-ink-3"
            >
              {(limits?.document_stages ?? [DEFAULT_STAGE]).map((stage) => (
                <option key={stage} value={stage}>
                  {stage}
                </option>
              ))}
            </select>
          </Field>

          <Field label="File" hint={form.content === "" ? "Read in your browser, sent as text." : `${form.content.length.toLocaleString()} characters ready`}>
            <input
              ref={fileInput}
              type="file"
              accept=".txt,.text,.md,.markdown,.xml"
              onChange={(event) => void pickFile(event.target.files?.[0])}
              className="t-caption w-full rounded border border-line bg-bg px-3 py-2 text-ink-2 outline-none file:mr-3 file:rounded file:border-0 file:bg-sunken file:px-2 file:py-1 file:text-ink-2 focus-visible:border-ink-3"
            />
          </Field>

          <div className="sm:col-span-2 flex flex-wrap items-center gap-4">
            <button
              type="submit"
              disabled={busy || !ready}
              className="rounded border border-line-strong px-4 py-2 text-ink disabled:opacity-40"
            >
              {busy ? "parsing, embedding, indexing…" : "Load into the engine"}
            </button>
            {busy ? (
              <span className="t-caption">
                The first upload after a restart loads the embedding model; it takes about ten
                seconds.
              </span>
            ) : null}
          </div>
        </form>

        {notice !== null ? (
          <p
            role="status"
            className={`t-body mt-4 rounded border px-3 py-2 ${
              notice.kind === "ok" ? "border-line bg-sunken text-ink-2" : "border-no text-no"
            }`}
          >
            {notice.text}
          </p>
        ) : null}
      </section>

      <DocumentList documents={documents} />
      <LibrarySearch documentCount={documents.length} />
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="t-label">{label}</span>
      {children}
      <span className="t-caption">{hint}</span>
    </label>
  );
}

function Boundary({ status, error }: { status?: LibraryStatus; error?: string }) {
  return (
    <section className="rounded border border-line bg-sunken p-5" aria-labelledby="boundary">
      <h2 id="boundary" className="t-label mb-2">
        What a loaded document can and cannot do
      </h2>
      <ul className="t-body flex max-w-[72ch] list-disc flex-col gap-1 pl-5">
        <li>
          It is indexed and searchable here, and a citation to it names your title, your authority
          and the file it came from.
        </li>
        <li>
          It carries <strong>no Federal Register citation and no page range</strong>. Those are
          reported <span className="t-mono">not recorded</span> rather than filled in with something
          plausible.
        </li>
        <li>
          It <strong>cannot establish a compliance obligation or an applicability verdict</strong>,
          whatever stage you declare. The engine admits only an adopted FAA airworthiness directive
          for that, and the answer writer is never shown your document.
        </li>
        <li>
          It is <strong>not in the default search scope</strong> for /ask, so a question about what
          an operator must do is still answered from adopted ADs alone.
        </li>
      </ul>
      {status !== undefined ? (
        <p className="t-mono mt-4 text-ink-3">
          {status.documents} document(s) · {status.paragraphs} paragraph(s) ·{" "}
          {status.retrievable ? "retrievable" : "NOT retrievable"}
          {status.error !== null ? ` · ${status.error}` : ""}
        </p>
      ) : null}
      {status?.notes.map((note) => (
        <p key={note} className="t-caption mt-1">
          {note}
        </p>
      ))}
      {error !== undefined ? <p className="t-body mt-4 text-no">{error}</p> : null}
    </section>
  );
}

function DocumentList({ documents }: { documents: readonly LibraryDocument[] }) {
  return (
    <section aria-labelledby="loaded-heading">
      <h2 id="loaded-heading" className="t-subhead mb-3">
        Loaded documents <span className="t-figure text-ink-3">({documents.length})</span>
      </h2>
      {documents.length === 0 ? (
        <p className="t-body text-ink-2">
          Nothing loaded yet. The engine is answering from its 2,117 shipped FAA airworthiness
          directives alone.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {documents.map((document) => (
            <li
              key={document.user_document_id}
              data-stage={document.document_stage}
              className="rounded border border-line bg-raised p-4"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="t-body font-semibold text-ink">{document.title}</h3>
                <span className="t-mono text-ink-3">{document.user_document_id}</span>
              </div>
              <p className="t-caption mt-1">
                {document.authority} · declared {document.document_stage} (not verified) ·{" "}
                {document.paragraph_count ?? 0} paragraphs · {humanBytes(document.source_bytes)} ·{" "}
                {document.source_filename ?? "upload"}
              </p>
              <p className="t-mono mt-2 break-all text-ink-3">
                sha256 {document.content_sha256 ?? "not recorded"}
              </p>
              <p className="t-caption mt-2 max-w-[70ch]">
                No applicability rule was extracted from this document.{" "}
                {document.unparsed_reason ?? ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LibrarySearch({ documentCount }: { documentCount: number }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<LibrarySearchResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (query.trim() === "") return;
      setBusy(true);
      try {
        const response = await fetch("/api/library/search", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ q: query, k: 8 }),
        });
        setResult((await response.json()) as LibrarySearchResult);
      } catch (error: unknown) {
        setResult({ error: error instanceof Error ? error.message : "search failed" });
      } finally {
        setBusy(false);
      }
    },
    [query],
  );

  const hits = result?.hits ?? [];

  return (
    <section aria-labelledby="search-heading">
      <h2 id="search-heading" className="t-subhead mb-1">
        Search your documents
      </h2>
      <p className="t-caption mb-4 max-w-[68ch]">
        This searches what you loaded and nothing else. It is a different question from /ask, which
        answers what an operator must do, from adopted ADs.
      </p>
      <form onSubmit={run} className="flex flex-wrap gap-3">
        <input
          value={query}
          maxLength={500}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="attach fitting crack inspection"
          disabled={documentCount === 0}
          className="min-w-[18rem] flex-1 rounded border border-line bg-bg px-3 py-2 text-ink outline-none focus-visible:border-ink-3 disabled:opacity-40"
        />
        <button
          type="submit"
          disabled={busy || documentCount === 0 || query.trim() === ""}
          className="rounded border border-line-strong px-4 py-2 text-ink disabled:opacity-40"
        >
          {busy ? "searching…" : "Search"}
        </button>
      </form>

      {result?.error !== undefined ? <p className="t-body mt-4 text-no">{result.error}</p> : null}
      {result?.note !== undefined ? <p className="t-body mt-4 text-ink-2">{result.note}</p> : null}
      {result?.limitation !== undefined ? (
        <p className="t-caption mt-4 border-l-2 border-maybe bg-accent-dim px-3 py-2">
          {result.limitation}
        </p>
      ) : null}

      {hits.length > 0 ? (
        <ol className="mt-4 flex flex-col gap-3">
          {hits.map((hit) => (
            <Hit key={hit.paragraph_id} hit={hit} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function Hit({ hit }: { hit: LibraryHit }) {
  return (
    <li data-stage={hit.document_stage} className="rounded border border-line bg-raised p-4">
      <p className="t-mono text-ink-3">{hit.human_reference.display}</p>
      {hit.heading !== "" ? (
        <h3 className="t-body mt-2 font-semibold text-ink">{hit.heading}</h3>
      ) : null}
      <p className="t-answer mt-1 whitespace-pre-wrap text-ink">{hit.text}</p>
      <p className="t-caption mt-3">
        Cannot establish an obligation: {hit.obligation_refusal ?? "user-supplied document"}.{" "}
        {hit.human_reference.not_recorded.length > 0
          ? `Not recorded for this document: ${hit.human_reference.not_recorded.join(", ")}.`
          : ""}
      </p>
    </li>
  );
}
