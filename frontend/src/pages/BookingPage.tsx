import { useState, useEffect } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Header } from "../components/layout/Header.tsx";
import { getConfig, getSession, createCheckoutSession, verifyPayment } from "../lib/api";
import type { AppConfig, PaymentVerification } from "../lib/api";

export function BookingPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [prospectName, setProspectName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [paymentVerification, setPaymentVerification] = useState<PaymentVerification | null>(null);
  const [paymentCancelled, setPaymentCancelled] = useState(false);

  // Check for payment return via URL params
  const paymentStatus = searchParams.get("payment");
  const checkoutSessionId = searchParams.get("checkout_session_id");

  // Load TidyCal embed script
  useEffect(() => {
    if (!config?.tidycal_path) return;
    // Only load once
    if (document.getElementById("tidycal-script")) return;
    const script = document.createElement("script");
    script.id = "tidycal-script";
    script.src = "https://asset-tidycal.b-cdn.net/js/embed.js";
    script.async = true;
    document.head.appendChild(script);
  }, [config?.tidycal_path]);

  // Load config and session data
  useEffect(() => {
    async function load() {
      try {
        const [cfg, session] = await Promise.all([
          getConfig(),
          sessionId && sessionId !== "direct" ? getSession(sessionId) : Promise.resolve(null),
        ]);
        setConfig(cfg);

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

  // Verify payment if returning from Stripe
  useEffect(() => {
    if (paymentStatus === "success" && checkoutSessionId) {
      verifyPayment(checkoutSessionId)
        .then((result) => setPaymentVerification(result))
        .catch((err) => console.error("Payment verification failed:", err));
    } else if (paymentStatus === "cancelled") {
      setPaymentCancelled(true);
    }
  }, [paymentStatus, checkoutSessionId]);

  const handleCheckout = async () => {
    setCheckoutLoading(true);
    try {
      const result = await createCheckoutSession(sessionId);
      // Redirect to Stripe Checkout
      window.location.href = result.checkout_url;
    } catch (err) {
      console.error("Failed to create checkout session:", err);
      alert("Failed to start checkout. Please try again.");
      setCheckoutLoading(false);
    }
  };

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

  // Payment success view
  if (paymentVerification?.payment_status === "paid") {
    return (
      <div className="h-screen flex flex-col bg-zinc-950 text-white">
        <Header />
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-2xl mx-auto px-4 py-16">
            <div className="text-center mb-10">
              <div className="w-20 h-20 rounded-full bg-emerald-600/20 flex items-center justify-center mx-auto mb-6">
                <svg className="w-10 h-10 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h1 className="text-3xl font-bold mb-3">Payment Confirmed!</h1>
              <p className="text-zinc-400 text-lg">
                {prospectName
                  ? `Thank you, ${prospectName}. Your AI Discovery Workshop is booked.`
                  : "Your AI Discovery Workshop is booked."}
              </p>
            </div>

            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 mb-8">
              <h2 className="text-lg font-semibold mb-4">Payment Details</h2>
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Amount</span>
                  <span className="font-medium">
                    ${((paymentVerification.amount_total || 0) / 100).toLocaleString()} {paymentVerification.currency?.toUpperCase()}
                  </span>
                </div>
                {paymentVerification.customer_email && (
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Receipt sent to</span>
                    <span className="font-medium">{paymentVerification.customer_email}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-zinc-400">Status</span>
                  <span className="font-medium text-emerald-400">Paid</span>
                </div>
              </div>
            </div>

            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 mb-8">
              <h2 className="text-lg font-semibold mb-4">What Happens Next</h2>
              <ol className="space-y-4 text-sm">
                <li className="flex gap-3">
                  <span className="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold shrink-0">1</span>
                  <div>
                    <p className="font-medium">Confirmation email</p>
                    <p className="text-zinc-400">You'll receive a payment receipt and booking confirmation shortly.</p>
                  </div>
                </li>
                <li className="flex gap-3">
                  <span className="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold shrink-0">2</span>
                  <div>
                    <p className="font-medium">Pre-workshop prep</p>
                    <p className="text-zinc-400">Our team will reach out to schedule and prepare a customized agenda for your organization.</p>
                  </div>
                </li>
                <li className="flex gap-3">
                  <span className="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold shrink-0">3</span>
                  <div>
                    <p className="font-medium">Onsite workshop</p>
                    <p className="text-zinc-400">Nik Shah, CEO of 100x, comes onsite to build your customized AI transformation plan targeting $5M+ in annual savings.</p>
                  </div>
                </li>
              </ol>
            </div>

            {config?.tidycal_path && (
              <div className="text-center mb-8">
                <p className="text-zinc-400 text-sm mb-4">Haven't picked a date yet? Schedule your workshop now:</p>
                <a
                  href={`https://tidycal.com/${config.tidycal_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 h-10 px-5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-500 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  Book Free Workshop
                </a>
              </div>
            )}

            <div className="text-center">
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

  return (
    <div className="h-screen flex flex-col bg-zinc-950 text-white">
      <Header />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-8">
          {/* Payment cancelled banner */}
          {paymentCancelled && (
            <div className="mb-6 bg-amber-900/20 border border-amber-800 rounded-lg p-4 text-center">
              <p className="text-amber-300 text-sm">
                Payment was cancelled. No worries — you can try again whenever you're ready.
              </p>
            </div>
          )}

          {/* Hero section */}
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
              {config?.tidycal_path && (
                <a
                  href={`https://tidycal.com/${config.tidycal_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 h-10 px-5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-500 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  Book Free Workshop
                </a>
              )}
            </div>

            {/* Step 2: Pay via Stripe Checkout */}
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
              <button
                onClick={handleCheckout}
                disabled={checkoutLoading}
                className="inline-flex items-center gap-2 h-10 px-5 rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {checkoutLoading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Redirecting...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
                    </svg>
                    Pay $10,000 via Stripe
                  </>
                )}
              </button>
            </div>
          </div>

          {/* TidyCal Embed */}
          {config?.tidycal_path && (
            <div className="mb-8">
              <h3 className="text-lg font-semibold mb-4 text-center">
                Or book directly here:
              </h3>
              <div
                id="tidycal-embed"
                data-path={config.tidycal_path}
                style={{ minWidth: "320px", minHeight: "700px" }}
              />
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
