/**
 * MetadataBar — the row above the prompt input that mirrors Claude
 * Code's "6m 8s · ↓ 9.6k tokens" + branch indicator + diff stats +
 * Create-PR button.
 *
 * Forge equivalents:
 *   - Wall-clock duration of the active session
 *   - Token total across all sprints (in + out)
 *   - Active branch (from the project scanner) + worktree counter
 *   - Aggregate diff stats across all open worktrees
 *   - "Create PR" only available when:
 *       * the project is a git repo with a remote
 *       * `gh` CLI is detected
 *       * at least one sprint has been merged
 */

import React from "react";

export type MetadataBarProps = {
  durationSec: number;
  totalTokens: number;
  branch?: string;
  worktreeCount: number;
  diffAdded: number;
  diffRemoved: number;
  prAvailable: boolean;
  onCreatePR: () => void;
};

export function MetadataBar(props: MetadataBarProps) {
  const {
    durationSec,
    totalTokens,
    branch,
    worktreeCount,
    diffAdded,
    diffRemoved,
    prAvailable,
    onCreatePR,
  } = props;

  return (
    <div className="space-y-2">
      {/* Top row: duration + tokens */}
      <div className="flex items-center gap-3 text-xs text-gray-500">
        <span className="text-amber-500">✻</span>
        <span>{formatDuration(durationSec)}</span>
        <span className="text-gray-700">·</span>
        <span>↓ {formatTokens(totalTokens)} tokens</span>
      </div>

      {/* Branch + diff + PR row (only when there's something to show) */}
      {(branch || worktreeCount > 0) && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#12121a] border border-[#1e1e2e]">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-gray-500">
            <path
              d="M5 3a2 2 0 110 4 2 2 0 010-4zM11 9a2 2 0 110 4 2 2 0 010-4zM5 7v6M11 3a2 2 0 100 4 2 2 0 000-4zM11 7v2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
          <span className="font-mono text-sm text-gray-200">{branch ?? "—"}</span>
          {worktreeCount > 0 && (
            <>
              <span className="text-gray-600">←</span>
              <span className="font-mono text-sm text-gray-400">
                {worktreeCount} worktree{worktreeCount === 1 ? "" : "s"}
              </span>
            </>
          )}
          <div className="flex-1" />
          {(diffAdded > 0 || diffRemoved > 0) && (
            <span className="text-xs px-2 py-0.5 rounded bg-[#0a0a0f] border border-[#1e1e2e]">
              <span className="text-green-400">+{diffAdded}</span>
              {" "}
              <span className="text-red-400">-{diffRemoved}</span>
            </span>
          )}
          <button
            onClick={onCreatePR}
            disabled={!prAvailable}
            className={`text-xs px-3 py-1 rounded ${
              prAvailable
                ? "bg-[#1e1e2e] text-gray-200 hover:bg-[#252535]"
                : "bg-[#0d0d14] text-gray-600 cursor-not-allowed"
            }`}
          >
            Create PR
          </button>
        </div>
      )}
    </div>
  );
}

function formatDuration(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s}s`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
