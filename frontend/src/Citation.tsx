import React, { useState } from 'react';
import type { Citation } from './models/Citation';

interface CitationProps {
  citation: Citation;
  index?: number;
  className?: string;
  onOpenDocument?: (docId: string, pageNumber: number) => void;
}

export const CitationCard: React.FC<CitationProps> = ({
  citation,
  index,
  className = '',
  onOpenDocument,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const formattedScore =
    citation.relevance_score !== undefined
      ? Math.round(citation.relevance_score <= 1 ? citation.relevance_score * 100 : citation.relevance_score)
      : null;

  const handleCopyQuote = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(citation.quote_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard write failed
    }
  };

  const handleDocumentClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onOpenDocument?.(citation.document_id, citation.page_number);
  };

  return (
    <div
      className={`border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 rounded-lg shadow-sm text-sm transition-all overflow-hidden ${className}`}
    >
      {/* Header bar / Summary */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setIsOpen((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsOpen((prev) => !prev);
          }
        }}
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800/60 select-none gap-3"
      >
        <div className="flex items-center space-x-2.5 min-w-0">
          {index !== undefined && (
            <span className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300 font-semibold text-xs">
              {index}
            </span>
          )}

          <div className="min-w-0">
            <p className="font-medium text-neutral-800 dark:text-neutral-100 truncate">
              {citation.document_name}
            </p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              Page {citation.page_number}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          {formattedScore !== null && (
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                formattedScore >= 80
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
                  : formattedScore >= 60
                  ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                  : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400'
              }`}
            >
              {formattedScore}% match
            </span>
          )}

          <svg
            className={`w-4 h-4 text-neutral-400 transition-transform duration-200 ${
              isOpen ? 'transform rotate-180' : ''
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>

      {/* Expanded Content */}
      {isOpen && (
        <div className="border-t border-neutral-100 dark:border-neutral-800/80 p-3 bg-neutral-50/50 dark:bg-neutral-900/50 space-y-3">
          {/* Quote Block */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-semibold text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
                Extracted Snippet
              </span>
              <button
                type="button"
                onClick={handleCopyQuote}
                className="text-xs text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200 flex items-center gap-1 transition-colors"
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <blockquote className="p-2.5 rounded bg-white dark:bg-neutral-950 border border-neutral-200/80 dark:border-neutral-800 text-xs italic text-neutral-700 dark:text-neutral-300 leading-relaxed max-h-40 overflow-y-auto">
              "{citation.quote_text}"
            </blockquote>
          </div>

          {/* Action Footer */}
          <div className="flex items-center justify-between pt-1 text-xs">
            <span className="text-neutral-400 dark:text-neutral-500 font-mono text-[11px] truncate max-w-[180px]">
              ID: {citation.citation_chunk_id}
            </span>

            {onOpenDocument && (
              <button
                type="button"
                onClick={handleDocumentClick}
                className="text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 font-medium inline-flex items-center gap-1"
              >
                Jump to Source
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};