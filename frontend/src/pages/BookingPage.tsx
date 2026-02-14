import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Header } from "../components/layout/Header.tsx";
import { getConfig, getSession } from "../lib/api";
import type { AppConfig } from "../lib/api";

declare global {
  interface Window {
    Calendly?: {
      initInlineWidget: (opts: {
        url: string;
        parentElement: HTMLElement;
        prefill?: Record<string, string>;
      }) => void;
    };
  }
}

// Load Calendly script once, return a promise that resolves when ready
let calendlyScriptPromise: Promise<void> | null = null;

function loadCalendlyScript(): Promise<void> {
  if (calendlyScriptPromise) return calendlyScriptPromise;

  calendlyScriptPromise = new Promise((resolve, reject) => {
    // Check if already loaded (e.g. from preload + previous page visit)
    if (window.Calendly) {
      resolve();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://assets.calendly.com/assets/external/widget.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Calendly script"));
    document.head.appendChild(script);
  });

  return calendlyScriptPromise;
}

export function BookingPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [prospectName, setProspectName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [embedReady, setEmbedReady] = useState(false);
  const calendlyContainerRef = useRef<HTMLDivElement>(null);

  // Start loading Calendly script immediately on mount (don't wait for config)
  useEffect(() => {
    loadCalendlyScript().catch((err) =>
      console.error("Calendly script load error:", err)
    );
  }, []);

  useEffect(() => {
    async function load() {
      try {
        const [cfg, session] = await Promise.all([
          getConfig(),
          sessionId ? getSession(sessionId) : Promise.resolve(null),
        ]);
        setConfig(cfg);

        // Try to get prospect name from session profile
        if (session && (session as any).prospect_profile) {
          const profile = (session as any).prospect_profile;
          if (profile.name) setProspectName(profile.name);
        }
      } catch (err) {
        console.error("Failed to load booking page:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [sessionId]);

  // Initialize Calendly inline widget once we have config + script + container
  const initCalendly = useCallback(async () => {
    if (!config?.calendly_url || !calendlyContainerRef.current) return;

    try {
      await loadCalendlyScript();

      if (window.Calendly && calendlyContainerRef.current) {
        // Clear any previous widget content
        calendlyContainerRef.current.innerHTML = "";

        window.Calendly.initInlineWidget({
          url: config.calendly_url,
          parentElement: calendlyContainerRef.current,
          prefill: prospectName ? { name: prospectName } : {},
        });

        setEmbedReady(true);
      }
    } catch (err) {
      console.error("Failed to init Calendly widget:", err);
    }
  }, [config?.calendly_url, prospectName]);

  useEffect(() => {
    initCalendly();
  }, [initCalendly]);

  if (loading) {
    return (
      <div className="h-screen flex flex-col bg-zinc-950 text-white">
        <Header />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-zinc-500">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-white">
      <Header />

      <div className="flex-1 overflow-y-auto">
        {/* Hero section */}
        <div className="max-w-3xl mx-auto px-4 py-8">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold mb-2">
              {prospectName
                ? `${prospectName}, You're Almost There!`
                : "You're Almost There!"}
            </h1>
            <p className="text-zinc-400 text-sm">
              Complete these two steps to lock in your AI Discovery Workshop
            </p>
          </div>

          {/* Two-step cards */}
          <div className="grid gap-6 md:grid-cols-2 mb-10">
            {/* Step 1: Book */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm font-bold">
                  1
                </div>
                <h2 className="text-lg font-semibold">Book Your Workshop</h2>
              </div>
              <p className="text-zinc-400 text-sm mb-4">
                Pick a time that works for you and your team. Nik Shah, CEO of
                100x, will come onsite to build your customized AI
                transformation plan.
              </p>
              {config?.calendly_url && (
                <a
                  href={config.calendly_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 h-10 px-5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-500 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  Schedule on Calendly
                </a>
              )}
            </div>

            {/* Step 2: Pay */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center text-sm font-bold">
                  2
                </div>
                <h2 className="text-lg font-semibold">Complete Payment</h2>
              </div>
              <p className="text-zinc-400 text-sm mb-4">
                Secure your spot with a one-time $10,000 payment. You'll be
                redirected to Stripe's secure checkout.
              </p>
              {config?.stripe_payment_link && (
                <a
                  href={config.stripe_payment_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 h-10 px-5 rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
                  </svg>
                  Pay $10,000 via Stripe
                </a>
              )}
            </div>
          </div>

          {/* Calendly Embed */}
          {config?.calendly_url && (
            <div className="mb-8">
              <h3 className="text-lg font-semibold mb-4 text-center">
                Or book directly here:
              </h3>
              <div className="relative">
                {/* Loading spinner overlay — shows until Calendly iframe renders */}
                {!embedReady && (
                  <div className="absolute inset-0 flex items-center justify-center bg-zinc-900 rounded-xl z-10">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                      <p className="text-zinc-500 text-sm">Loading calendar...</p>
                    </div>
                  </div>
                )}
                <div
                  ref={calendlyContainerRef}
                  className="rounded-xl overflow-hidden"
                  style={{ minWidth: "320px", height: "700px" }}
                />
              </div>
            </div>
          )}

          {/* Back button */}
          <div className="text-center pb-8">
            <button
              onClick={() => navigate("/")}
              className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              ← Back to Sally
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
