"use client";

interface Props {
  worktrees: string[];
  onApprove: (name: string) => void;
  onReject: (name: string) => void;
  onApproveAll: () => void;
}

export function MergeGate({ worktrees, onApprove, onReject, onApproveAll }: Props) {
  if (worktrees.length === 0) return null;

  return (
    <div className="p-4 rounded-lg bg-[#12121a] border border-green-800/30">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-400">Merge Gate</h3>
        <button
          onClick={onApproveAll}
          className="px-3 py-1 text-xs rounded bg-green-600 text-white hover:bg-green-500"
        >
          Approve All
        </button>
      </div>
      <div className="space-y-2">
        {worktrees.map((wt) => (
          <div key={wt} className="flex items-center justify-between p-2 rounded bg-[#0a0a0f]">
            <span className="font-mono text-xs text-gray-400">{wt}</span>
            <div className="flex gap-1">
              <button onClick={() => onApprove(wt)} className="px-2 py-0.5 text-xs rounded bg-green-800/40 text-green-400 hover:bg-green-800/60">
                Approve
              </button>
              <button onClick={() => onReject(wt)} className="px-2 py-0.5 text-xs rounded bg-red-800/40 text-red-400 hover:bg-red-800/60">
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
