export interface HistoryDetailProps {
  recordId: string;
}

/** Placeholder — Task 8 replaces this with the full detail view. */
export default function HistoryDetail({ recordId }: HistoryDetailProps) {
  return (
    <div className="min-h-screen bg-gray-50 p-6 text-sm text-gray-600">
      Loading record {recordId}…
    </div>
  );
}
