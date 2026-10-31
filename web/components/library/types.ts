/**
 * The shapes the engine's /library endpoints return.
 *
 * Every field here is read from the engine's payload and rendered as text by
 * React, which escapes it. Nothing on these pages uses dangerouslySetInnerHTML:
 * a title, an authority and a filename are all typed by a user, and a paragraph
 * body is a file a user uploaded.
 */
import type { DocumentStage, SourceKind } from "@/lib/contract";

export interface LibraryDocument {
  readonly user_document_id: string;
  readonly title: string;
  readonly authority: string;
  readonly document_stage: DocumentStage;
  readonly source_filename: string | null;
  readonly media_type: string | null;
  readonly content_sha256: string | null;
  readonly source_bytes: number | null;
  readonly uploaded_at: string | null;
  readonly paragraph_count: number | null;
  readonly rules_extracted: boolean;
  readonly unparsed_reason: string | null;
  readonly source_kind: SourceKind;
  readonly establishes_obligation: boolean;
  readonly in_default_retrieval_scope: boolean;
  readonly characters: number;
}

export interface LibraryStatus {
  readonly documents: number;
  readonly paragraphs: number;
  readonly retrievable: boolean;
  readonly in_default_retrieval_scope: boolean;
  readonly can_establish_obligation: boolean;
  readonly notes: readonly string[];
  readonly error: string | null;
}

export interface LibraryLimits {
  readonly max_bytes: number;
  readonly media_types: readonly string[];
  readonly document_stages: readonly DocumentStage[];
}

export interface LibraryListing {
  readonly reachable?: boolean;
  readonly documents?: readonly LibraryDocument[];
  readonly status?: LibraryStatus;
  readonly limits?: LibraryLimits;
  readonly error?: string;
}

export interface UserHumanReference {
  readonly citation_id: string;
  readonly handle: string;
  readonly document_stage: DocumentStage;
  readonly display: string;
  readonly not_recorded: readonly string[];
  readonly obligation_refusal?: string;
  readonly is_user_document?: boolean;
  readonly authority?: string;
  readonly source_filename?: string | null;
}

export interface LibraryHit {
  readonly paragraph_id: string;
  readonly label: string;
  readonly role: string;
  readonly heading: string;
  readonly text: string;
  readonly score: number;
  readonly dense_cosine: number | null;
  readonly source_kind: SourceKind;
  readonly document_stage: DocumentStage;
  readonly establishes_obligation: boolean;
  readonly obligation_refusal: string | null;
  readonly human_reference: UserHumanReference;
}

export interface LibrarySearchResult {
  readonly hits?: readonly LibraryHit[];
  readonly documents?: number;
  readonly limitation?: string;
  readonly note?: string;
  readonly error?: string;
}

/** Bytes as a short human string. Sizes here are KiB to low MiB. */
export function humanBytes(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return "size not recorded";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}
