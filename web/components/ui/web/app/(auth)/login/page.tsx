"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiPost, ApiException, tokenStore } from "@/lib/api-client";
import type { TokenOut } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardBody } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const tokens = await apiPost<TokenOut>("/api/v1/auth/login", { email, password }, { skipAuth: true });

      if (tokens.mfa_required) {
        sessionStorage.setItem("mfa_session", tokens.session_token ?? "");
        sessionStorage.setItem("mfa_email", email);
        router.push("/mfa");
        return;
      }

      tokenStore.set(tokens);
      document.cookie = `mtech_access_token=${tokens.access_token}; path=/; max-age=${tokens.expires_in}; SameSite=Lax`;
      router.push(next);
    } catch (err) {
      if (err instanceof ApiException) setError(err.message);
      else setError("Impossible de se connecter. Réessayez.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardBody className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Connexion</h2>
          <p className="text-sm text-slate-500">Accédez à votre espace entreprise</p>
        </div>

        {error && <Alert variant="danger">{error}</Alert>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            id="email"
            type="email"
            label="Adresse e-mail"
            placeholder="vous@entreprise.ci"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            id="password"
            type="password"
            label="Mot de passe"
            placeholder="••••••••••"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" loading={loading} className="w-full" size="lg">
            Se connecter
          </Button>
        </form>

        <p className="text-center text-xs text-slate-500">
          Mot de passe oublié ? Contactez votre administrateur.
        </p>
      </CardBody>
    </Card>
  );
}
