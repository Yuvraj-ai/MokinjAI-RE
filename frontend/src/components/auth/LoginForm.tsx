import { useState, FormEvent } from 'react'
import { useAuth } from '../../hooks/useAuth'
import { AlertCircle, ArrowRight } from 'lucide-react'
import Button from '../ui/Button'
import { Callout } from '../ui/Feedback'
import LabelInput from '../ui/LabelInput'

export default function LoginForm() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(email, password)
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          err?.message ||
          'Login failed. Please check your credentials.'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="w-full max-w-[340px] mx-auto">
      <div className="mb-6">
        <h2 className="text-2xl font-semibold text-ink tracking-tight animate-fade-in-up">
          Sign into your account
        </h2>
        <p className="mt-1 text-sm text-ink-muted animate-fade-in-up stagger-1">
          Enter your credentials to access your workspace
        </p>
      </div>

      {error && (
        <div className="mb-5 animate-fade-in">
          <Callout tone="danger">
            <span className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />
              {error}
            </span>
          </Callout>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="animate-fade-in-up stagger-2">
          <LabelInput
            field="Email"
            id="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            corner={12}
          />
        </div>

        <div className="animate-fade-in-up stagger-3">
          <LabelInput
            field="Password"
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            corner={12}
          />
        </div>

        <div className="pt-2 animate-fade-in-up stagger-4">
          <Button type="submit" loading={loading} className="group w-full h-10 px-4 py-2 rounded-xl text-sm font-medium">
            {loading ? (
              'Signing in…'
            ) : (
              <>
                Sign in
                <ArrowRight className="w-4 h-4 transition-transform duration-300 group-hover:translate-x-0.5" aria-hidden />
              </>
            )}
          </Button>
        </div>
      </form>
    </div>
  )
}
