/**
 * Who is at the keyboard.
 *
 * The whole of identity on this project: the worker types the id code they were
 * issued, and every row they write is recorded to them
 * (docs/decision-workstation-auth.md). No password, no account, no roles — the
 * code *is* the identifier.
 *
 * The code is checked against the server before the workstation opens, so a
 * mistyped code fails here rather than after an hour of transcription.
 */
import { useState } from "react";
import { NotIdentified, rememberIdCode, whoami, type Worker } from "../api";

interface Props {
  onIdentified: (worker: Worker) => void;
  /** Set when a stored code stopped working, e.g. after it was rotated. */
  notice?: string | null;
}

export function IdentityGate({ onIdentified, notice }: Props) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const typed = code.trim();
    if (!typed) return;
    setChecking(true);
    setError(null);
    try {
      const worker = await whoami(typed);
      rememberIdCode(typed);
      onIdentified(worker);
    } catch (err) {
      setError(
        err instanceof NotIdentified
          ? "That code is not recognized. Check it against the one you were issued."
          : `Could not reach the workstation API: ${err}`,
      );
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="gate">
      <form className="gate__card" onSubmit={submit}>
        <h1>停年名簿 transcription</h1>
        <p className="gate__lede">
          Enter your id code. Everything you record is attributed to it.
        </p>
        {notice && <p className="gate__notice">{notice}</p>}
        <label htmlFor="id-code">id code</label>
        <input
          id="id-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="JP-XXXX-XXXX-XXXX"
          autoComplete="off"
          spellCheck={false}
          autoFocus
          // Latin-only, so an IME left on from the last session does not turn
          // the code into half-converted kana on the way in.
          inputMode="text"
          className="gate__input"
        />
        <button type="submit" disabled={checking || !code.trim()}>
          {checking ? "checking…" : "start"}
        </button>
        {error && <p className="gate__error">{error}</p>}
        <p className="gate__foot">
          Don’t have one? Ask the project lead to issue you a code —{" "}
          <code>scripts/issue_access_code.py</code>.
        </p>
      </form>
    </div>
  );
}
