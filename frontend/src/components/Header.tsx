export default function Header() {
  return (
    <div className="absolute top-0 right-0 p-4 z-20">
      <button className="flex items-center gap-2 text-gray-700 hover:text-gray-900 font-medium transition-colors" type="button">
        <span>Log Out</span>
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </button>
    </div>
  );
}


