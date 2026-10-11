import { useId, useState } from "react";
import { login, signup } from "../lib/auth";
import { Button } from "./ui";

/**
 * Sign in / create account.
 *
 * One form, two modes. Inline checks mirror the server's rules (email shape,
 * 8+ characters, passwords match) so most mistakes are caught before a round
 * trip, but the server stays the authority: its message is shown verbatim
 * above the form.
 */

const MIN_PASSWORD = 8;
const MAX_PASSWORD_BYTES = 72;   // bcrypt reads no further
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const focusRing =
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-core/70 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-void";

function validate(mode, f) {
  const e = {};
  if (mode === "signup" && !f.displayName.trim()) e.displayName = "Enter your name.";
  if (!EMAIL_SHAPE.test(f.email.trim())) e.email = "Enter a valid email address.";
  if (mode === "signup") {
    if (f.password.length < MIN_PASSWORD) {
      e.password = `Use at least ${MIN_PASSWORD} characters.`;
    } else if (new TextEncoder().encode(f.password).length > MAX_PASSWORD_BYTES) {
      e.password = `Use at most ${MAX_PASSWORD_BYTES} bytes.`;
    }
    if (f.confirm !== f.password) e.confirm = "Passwords don't match.";
  } else if (!f.password) {
    e.password = "Enter your password.";
  }
  return e;
}

function Field({ id, label, hint, error, optional, ...input }) {
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div>
      <label htmlFor={id} className="flex items-baseline justify-between text-sm text-ink-dim">
        <span>{label}</span>
        {optional && <span className="text-[11px] text-ink-mute">Optional</span>}
      </label>
      <input
        id={id}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={describedBy}
        className={`mt-1.5 w-full rounded-lg border bg-void/80 px-4 py-3 text-sm text-ink placeholder:text-ink-mute transition-colors ${
          error ? "border-alert/60" : "border-line hover:border-ink-mute/60 focus:border-cyan-core"
        } ${focusRing}`}
        {...input}
      />
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-xs text-alert">{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-ink-mute">{hint}</p>
      ) : null}
    </div>
  );
}

export default function AuthScreen({ onAuthed }) {
  const uid = useId();
  const [mode, setMode] = useState("login");          // login | signup
  const [form, setForm] = useState({
    displayName: "", email: "", institution: "", password: "", confirm: "",
  });
  const [touched, setTouched] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverError, setServerError] = useState(null);

  const errors = validate(mode, form);
  // Show a field's problem once it has been left, or after a submit attempt —
  // not while the person is still typing their first character.
  const shown = (k) => ((touched[k] || submitted) ? errors[k] : undefined);

  const bind = (k) => ({
    value: form[k],
    onChange: (e) => setForm((f) => ({ ...f, [k]: e.target.value })),
    onBlur: () => setTouched((t) => ({ ...t, [k]: true })),
  });

  function switchMode(next) {
    if (next === mode || pending) return;
    setMode(next);
    setForm((f) => ({ ...f, password: "", confirm: "" }));
    setTouched({});
    setSubmitted(false);
    setServerError(null);
  }

  async function onSubmit(e) {
    e.preventDefault();
    setSubmitted(true);
    setServerError(null);
    if (Object.keys(errors).length) return;

    setPending(true);
    try {
      const researcher =
        mode === "login"
          ? await login({ email: form.email.trim(), password: form.password })
          : await signup({
              email: form.email.trim(),
              displayName: form.displayName.trim(),
              institution: form.institution.trim(),
              password: form.password,
            });
      onAuthed(researcher);
    } catch (err) {
      setServerError(err.message);
      setPending(false);
    }
  }

  const isSignup = mode === "signup";
  const tab = (m, label) => (
    <button
      type="button"
      onClick={() => switchMode(m)}
      aria-pressed={mode === m}
      className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${focusRing} ${
        mode === m
          ? "bg-cyan-core/14 text-cyan-glow"
          : "text-ink-mute hover:text-ink"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto flex max-w-md flex-col px-6 py-14 cs-fade-up">
      <span className="cs-eyebrow">Researcher access</span>
      <h2 className="mt-4 font-display text-3xl font-semibold">
        {isSignup ? "Create your account" : "Sign in to the studio"}
      </h2>
      <p className="mt-2 text-ink-dim">
        {isSignup
          ? "An account keeps your analyses together. It takes a few seconds."
          : "The studio is for registered researchers. Sign in to run an analysis."}
      </p>

      <div className="cs-panel mt-8 p-6">
        <div className="flex gap-1 rounded-xl border border-line bg-void/60 p-1" role="group" aria-label="Account">
          {tab("login", "Sign in")}
          {tab("signup", "Create account")}
        </div>

        {serverError && (
          <div role="alert" className="mt-5 rounded-lg border border-alert/40 bg-alert/8 p-4">
            <p className="text-sm font-medium text-alert">
              {isSignup ? "Couldn't create the account" : "Couldn't sign you in"}
            </p>
            <p className="mt-1 text-sm text-ink-dim">{serverError}</p>
          </div>
        )}

        <form onSubmit={onSubmit} noValidate className="mt-5 space-y-4" aria-busy={pending}>
          {isSignup && (
            <Field
              id={`${uid}-name`} label="Display name" type="text"
              autoComplete="name" maxLength={100} required
              error={shown("displayName")} {...bind("displayName")}
            />
          )}
          <Field
            id={`${uid}-email`} label="Email" type="email" inputMode="email"
            autoComplete="email" maxLength={255} required
            error={shown("email")} {...bind("email")}
          />
          {isSignup && (
            <Field
              id={`${uid}-inst`} label="Institution" type="text" optional
              autoComplete="organization" maxLength={150}
              {...bind("institution")}
            />
          )}
          <Field
            id={`${uid}-pw`} label="Password" type="password" required
            autoComplete={isSignup ? "new-password" : "current-password"}
            hint={isSignup ? `At least ${MIN_PASSWORD} characters. A long phrase is best.` : undefined}
            error={shown("password")} {...bind("password")}
          />
          {isSignup && (
            <Field
              id={`${uid}-confirm`} label="Confirm password" type="password"
              autoComplete="new-password" required
              error={shown("confirm")} {...bind("confirm")}
            />
          )}

          <Button type="submit" disabled={pending} className={`w-full ${focusRing}`}>
            {pending && (
              <span
                aria-hidden="true"
                className="size-4 animate-spin rounded-full border-2 border-void/30 border-t-void"
              />
            )}
            {pending
              ? isSignup ? "Creating account…" : "Signing in…"
              : isSignup ? "Create account" : "Sign in"}
          </Button>
        </form>
      </div>

      <p className="mt-5 text-center text-sm text-ink-mute">
        {isSignup ? "Already registered? " : "New to CellSpark? "}
        <button
          type="button"
          onClick={() => switchMode(isSignup ? "login" : "signup")}
          className={`rounded text-cyan-glow underline decoration-cyan-core/30 underline-offset-2 hover:decoration-cyan-core ${focusRing}`}
        >
          {isSignup ? "Sign in" : "Create an account"}
        </button>
      </p>
    </div>
  );
}
