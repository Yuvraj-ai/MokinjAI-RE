import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import LoginForm from '../components/auth/LoginForm'
import AdminOTPLogin from '../components/auth/AdminOTPLogin'

export default function LoginPage() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />
  }

  return (
    <div className="min-h-screen bg-canvas flex items-center justify-center p-3 sm:p-5 lg:p-8">
      {/* Centered card window matching the reference layout */}
      <div className="w-full max-w-5xl bg-surface border border-line rounded-3xl shadow-2xl p-2 sm:p-2.5 flex flex-col lg:flex-row overflow-hidden min-h-[580px] lg:min-h-[620px]">
        {/* Left: Compact Login form (taking ~42% of space) */}
        <div className="w-full lg:w-[42%] flex flex-col justify-between p-6 sm:p-8 lg:p-10">
          {/* Top Brand Logo */}
          <div className="flex items-center gap-2.5 mb-6 lg:mb-0">
            <div className="w-8 h-8 rounded-lg bg-primary text-primary-fg flex items-center justify-center shadow-sm">
              <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
                <path d="M12 2L7 8h3v6h4V8h3l-5-6z" />
              </svg>
            </div>
            <span className="text-sm font-semibold text-ink tracking-tight">Mokinjay</span>
          </div>

          {/* Form */}
          <div className="my-auto py-3">
            <LoginForm />
            <AdminOTPLogin />
          </div>

          {/* Bottom subtle access request matching reference layout */}
          <p className="mt-6 text-center text-xs text-ink-subtle">
            Don&apos;t have an account?{' '}
            <a
              href={`mailto:yuvrajsingh.tech@protonmail.com?subject=${encodeURIComponent(
                '[Mokinjay] Account Access Request'
              )}&body=${encodeURIComponent(
                'Hello Admin,\n\nI would like to request an account to access the Mokinjay workspace.\n\nDetails:\n- Full Name: \n- Requested Email: \n- Organization / Team: \n- Reason / Use Case: \n\nThank you!'
              )}`}
              className="text-ink-muted hover:text-ink underline underline-offset-2 transition-colors"
            >
              Contact an admin
            </a>
          </p>
        </div>

        {/* Right: Picture window with slim border (taking ~58% of space) */}
        <div className="hidden lg:flex lg:w-[58%] relative rounded-2xl overflow-hidden bg-[#262334] border border-white/10 flex-col justify-between p-8 xl:p-10 min-h-[560px]">
          {/* Top Headline inside picture window */}
          <div className="relative z-10 text-center pt-2">
            <p className="text-[#A8A49C] text-xs font-mono tracking-[0.25em] uppercase mb-2 animate-fade-in">
              Intelligent Automation
            </p>
            <h2 className="text-2xl xl:text-3xl font-semibold text-white tracking-tight leading-snug animate-fade-in-up stagger-1">
              Build, orchestrate, and deploy AI agents.
            </h2>
          </div>

          {/* Mokinjay Dither Illustration fitting nicely without giant borders */}
          <div className="absolute inset-0 flex items-center justify-center select-none pointer-events-none">
            <img
              src="/ditther-1794604960622.png"
              alt="Mokinjay Illustration"
              className="w-full h-full object-contain"
              style={{
                maskImage:
                  'linear-gradient(to right, transparent 0%, black 2%, black 98%, transparent 100%), linear-gradient(to bottom, transparent 0%, black 2%, black 98%, transparent 100%)',
                WebkitMaskImage:
                  'linear-gradient(to right, transparent 0%, black 2%, black 98%, transparent 100%), linear-gradient(to bottom, transparent 0%, black 2%, black 98%, transparent 100%)',
                maskComposite: 'intersect',
                WebkitMaskComposite: 'destination-in',
              }}
            />
          </div>

          {/* Bottom Footer inside picture window */}
          <div className="relative z-10 flex items-center justify-between pt-2">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/10 backdrop-blur-md border border-white/10 text-white/90 text-xs font-mono shadow-sm">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>v1.0 Ready</span>
            </div>
            <span className="text-xs text-white/60">
              Mokinjay Studio
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
