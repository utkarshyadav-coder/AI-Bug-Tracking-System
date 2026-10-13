import Link from "next/link";
import { ArrowLeft } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000";

export default function BugSightPage() {
  return (
    <main className="min-h-screen bg-white text-gray-900">
      <header className="flex h-16 items-center gap-4 border-b border-gray-200 px-4 sm:px-6">
        <Link
          href="/"
          aria-label="Back to AI-Powered Bug Tracker"
          title="Back to AI-Powered Bug Tracker"
          className="grid size-10 shrink-0 place-items-center rounded-md text-gray-700 transition-colors hover:bg-gray-100"
        >
          <ArrowLeft aria-hidden="true" size={20} />
        </Link>
        <div className="min-w-0">
          <p className="text-xs font-medium text-gray-500">AI-POWERED BUG TRACKER</p>
          <h1 className="truncate text-lg font-semibold">BugSight AI</h1>
        </div>
      </header>
      <iframe
        title="BugSight AI dashboard"
        src={`${API_URL}/bugsight`}
        className="block h-[calc(100vh-4rem)] w-full border-0"
      />
    </main>
  );
}