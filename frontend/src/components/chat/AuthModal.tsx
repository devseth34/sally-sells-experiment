import { useState } from "react";
import { login, register, identifyByNamePhone } from "../../lib/api";

interface AuthModalProps {
  onComplete: () => void;
  onSkip: () => void;
}

type AuthMode = "choice" | "login" | "register" | "identify";

export function AuthModal({ onComplete, onSkip }: AuthModalProps) {
  const [mode, setMode] = useState<AuthMode>("choice");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      onComplete();
    } catch (err: any) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    setError("");
    if (password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    setLoading(true);
    try {
      await register(email, password, name || undefined, phone || undefined);
      onComplete();
    } catch (err: any) {
      setError(err.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  const handleIdentify = async () => {
    setError("");
    if (!name.trim() || !phone.trim()) {
      setError("Both name and phone number are required");
      return;
    }
    setLoading(true);
    try {
      await identifyByNamePhone(name, phone);
      onComplete();
    } catch (err: any) {
      setError(err.message || "Identification failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-full max-w-md mx-4">

        {mode === "choice" && (
          <>
            <h2 className="text-lg font-semibold text-white mb-2">Welcome</h2>
            <p className="text-sm text-zinc-400 mb-6">
              Sign in to keep your conversation history across sessions and devices.
            </p>

            <div className="space-y-2 mb-4">
              <button
                onClick={() => setMode("login")}
                className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 transition-colors"
              >
                Sign In
              </button>
              <button
                onClick={() => setMode("register")}
                className="w-full h-10 rounded-md text-sm font-medium bg-zinc-800 text-zinc-200 hover:bg-zinc-700 transition-colors"
              >
                Create Account
              </button>
              <button
                onClick={() => setMode("identify")}
                className="w-full h-10 rounded-md text-sm font-medium bg-zinc-800 text-zinc-400 hover:bg-zinc-700 transition-colors"
              >
                Use Name & Phone Instead
              </button>
            </div>

            <button
              onClick={onSkip}
              className="w-full text-xs text-zinc-600 hover:text-zinc-400 transition-colors py-2"
            >
              Continue without signing in
            </button>
          </>
        )}

        {mode === "login" && (
          <>
            <h2 className="text-lg font-semibold text-white mb-4">Sign In</h2>
            {error && <p className="text-xs text-red-400 mb-3">{error}</p>}

            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-3 focus:outline-none focus:border-zinc-500"
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-4 focus:outline-none focus:border-zinc-500"
            />

            <button
              onClick={handleLogin}
              disabled={loading || !email || !password}
              className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 disabled:opacity-30 transition-colors mb-3"
            >
              {loading ? "Signing in..." : "Sign In"}
            </button>
            <button
              onClick={() => { setMode("choice"); setError(""); }}
              className="w-full text-xs text-zinc-500 hover:text-zinc-300 py-1"
            >
              Back
            </button>
          </>
        )}

        {mode === "register" && (
          <>
            <h2 className="text-lg font-semibold text-white mb-4">Create Account</h2>
            {error && <p className="text-xs text-red-400 mb-3">{error}</p>}

            <input
              type="text"
              placeholder="Full name (optional)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-3 focus:outline-none focus:border-zinc-500"
            />
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-3 focus:outline-none focus:border-zinc-500"
            />
            <input
              type="password"
              placeholder="Password (min 6 characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-3 focus:outline-none focus:border-zinc-500"
            />
            <input
              type="tel"
              placeholder="Phone number (optional)"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleRegister()}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-4 focus:outline-none focus:border-zinc-500"
            />

            <button
              onClick={handleRegister}
              disabled={loading || !email || !password}
              className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 disabled:opacity-30 transition-colors mb-3"
            >
              {loading ? "Creating account..." : "Create Account"}
            </button>
            <button
              onClick={() => { setMode("choice"); setError(""); }}
              className="w-full text-xs text-zinc-500 hover:text-zinc-300 py-1"
            >
              Back
            </button>
          </>
        )}

        {mode === "identify" && (
          <>
            <h2 className="text-lg font-semibold text-white mb-2">Identify Yourself</h2>
            <p className="text-sm text-zinc-500 mb-4">
              We'll use your name and phone to find your previous conversations.
            </p>
            {error && <p className="text-xs text-red-400 mb-3">{error}</p>}

            <input
              type="text"
              placeholder="Full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-3 focus:outline-none focus:border-zinc-500"
            />
            <input
              type="tel"
              placeholder="Phone number"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleIdentify()}
              className="w-full h-10 px-3 rounded-md text-sm bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 mb-4 focus:outline-none focus:border-zinc-500"
            />

            <button
              onClick={handleIdentify}
              disabled={loading || !name.trim() || !phone.trim()}
              className="w-full h-10 rounded-md text-sm font-medium bg-white text-black hover:bg-zinc-200 disabled:opacity-30 transition-colors mb-3"
            >
              {loading ? "Looking you up..." : "Continue"}
            </button>
            <button
              onClick={() => { setMode("choice"); setError(""); }}
              className="w-full text-xs text-zinc-500 hover:text-zinc-300 py-1"
            >
              Back
            </button>
          </>
        )}
      </div>
    </div>
  );
}
