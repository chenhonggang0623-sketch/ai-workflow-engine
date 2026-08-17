export function TabNav({
  tabs,
  active,
  onTabChange,
}: {
  tabs: { key: string; label: string }[];
  active: string;
  onTabChange: (key: string) => void;
}) {
  return (
    <div className="border-b border-gray-700 mb-4">
      <nav className="flex gap-0 -mb-px">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              active === tab.key
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-500"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
