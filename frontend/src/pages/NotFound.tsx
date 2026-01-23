export default function NotFound() {
  return (
    <div className="p-8">
      <h1 className="text-xl font-semibold text-gray-900">Not Found</h1>
      <p className="text-gray-600 mt-2">The page you are looking for does not exist.</p>
      <a className="inline-block mt-3 text-blue-600 hover:text-blue-700 underline" href="/">
        Back to Home
      </a>
    </div>
  );
}

