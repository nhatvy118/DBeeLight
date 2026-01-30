import { useState } from 'react';

export default function SignUp() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSignUpWithGoogle = () => {
    const next = '/chat';
    window.location.href = `/api/auth/google/login?next=${encodeURIComponent(next)}`;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) return;
    window.alert('Đăng ký bằng email chưa được hỗ trợ. Vui lòng dùng "Sign up with Google".');
  };

  const navigateTo = (path: string) => {
    window.history.pushState({}, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  return (
    <div className="flex flex-col min-h-full bg-white">
      <div className="flex-1 flex flex-col items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <h1 className="text-4xl md:text-5xl font-bold text-gray-900 mb-8 text-center">Sign up</h1>

          <form onSubmit={handleSubmit} className="space-y-5">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              className="w-full px-5 py-4 text-lg rounded-xl border border-gray-200 bg-gray-50 text-gray-900 placeholder-gray-500 outline-none focus:border-gray-400 transition-colors"
              autoComplete="email"
            />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              className="w-full px-5 py-4 text-lg rounded-xl border border-gray-200 bg-gray-50 text-gray-900 placeholder-gray-500 outline-none focus:border-gray-400 transition-colors"
              autoComplete="new-password"
            />
            <button
              type="submit"
              className="w-full py-4 text-lg rounded-xl bg-black text-white font-medium hover:bg-gray-800 transition-colors"
            >
              Sign up
            </button>
          </form>

          <div className="flex items-center justify-center gap-5 mt-5 flex-wrap">
            <button
              type="button"
              onClick={() => navigateTo('/login')}
              className="text-base text-purple-600 hover:text-purple-700"
            >
              Log in
            </button>
            <button
              type="button"
              onClick={() => navigateTo('/')}
              className="text-base text-purple-600 hover:text-purple-700"
            >
              Home
            </button>
          </div>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200" />
            </div>
            <div className="relative flex justify-center">
              <span className="bg-white px-2 text-base text-gray-500">or</span>
            </div>
          </div>

          <button
            type="button"
            onClick={handleSignUpWithGoogle}
            className="w-full flex items-center justify-center gap-3 py-4 text-xl rounded-xl border border-gray-200 bg-white text-gray-900 font-medium hover:bg-gray-50 transition-colors"
          >
            <svg className="w-6 h-6" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
            Sign up with Google
          </button>

          <div className="flex items-center justify-center gap-2 mt-8 text-base text-gray-400">
            <button type="button" className="hover:text-gray-600">
              Terms of Use
            </button>
            <span>|</span>
            <button type="button" className="hover:text-gray-600">
              Privacy Policy
            </button>
          </div>
        </div>
      </div>

      <footer className="py-6 text-center text-base text-gray-400">
        2026 LightDBee
      </footer>
    </div>
  );
}
