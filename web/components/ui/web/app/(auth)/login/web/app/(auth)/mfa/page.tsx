"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { apiPost, ApiException, tokenStore } from "@/lib/api-client";
import type { TokenOut } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardBody } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";

export default function MfaPage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const sessionToken = sessionStorage.getItem("mfa_session") ?? "";
      const email = sessionStorage.getItem("mfa_email") ?? "";
      const tokens = await apiPost<TokenOut>(
        "/api/v1/auth/mfa/verify",
        { email, code, session_token: sessionToken },
        { skipAuth: true },
      );
      tokenStore.set(tokens);
      document.cookie = `mtech_access_token=${tokens.access_token}; path=/; max-age=${tokens.expires_in}; SameSite=Lax`;
      sessionStorage.removeItem("mfa_session");
      sessionStorage.removeItem("mfa_email");
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiException) setError(err.message);
      else setError("Code invalide");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardBody className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Vérification en 2 étapes</h2>
          <p className="text-sm text-slate-500">
            Saisissez le code à 6 chiffres généré par votre application d'authentification.
          </p>
        </div>

        {error && <Alert variant="danger">{error}</Alert>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            id="code"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            placeholder="000000"
            required
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="text-center font-mono text-2xl tracking-widest"
          />
          <Button type="submit" loading={loading} className="w-full" size="lg">
            Vérifier
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
