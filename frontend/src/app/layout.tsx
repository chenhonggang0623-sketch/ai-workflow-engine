import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Agent Workflow Console",
  description: "Internal testing console for AI Agent Workflow Engine",
};

function Sidebar() {
  return (
    <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div className="p-4 border-b border-gray-800">
        <h1 className="text-base font-bold text-white">AI Workflow</h1>
        <p className="text-xs text-gray-500 mt-0.5">Internal Console</p>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        <Link
          href="/"
          className="block px-3 py-2 text-sm text-gray-300 rounded-md hover:bg-gray-800 hover:text-white transition-colors"
        >
          Projects
        </Link>
        <Link
          href="/workflows/create"
          className="block px-3 py-2 text-sm text-gray-300 rounded-md hover:bg-gray-800 hover:text-white transition-colors"
        >
          + New Project
        </Link>
        <Link
          href="/executions"
          className="block px-3 py-2 text-sm text-gray-300 rounded-md hover:bg-gray-800 hover:text-white transition-colors"
        >
          Executions
        </Link>
        <div className="pt-3 mt-3 border-t border-gray-800">
          <Link
            href="/config"
            className="block px-3 py-2 text-sm text-gray-300 rounded-md hover:bg-gray-800 hover:text-white transition-colors"
          >
            ⚙ Config
          </Link>
        </div>
      </nav>
      <div className="p-3 border-t border-gray-800">
        <div className="text-xs text-gray-600">v0.1.0</div>
      </div>
    </aside>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full flex bg-gray-950 text-gray-100">
        <Sidebar />
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </body>
    </html>
  );
}
