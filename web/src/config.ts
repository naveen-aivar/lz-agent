export interface Config {
  apiUrl: string;
  clientId: string;
  cognitoDomain: string;
}

/** The classic UI's config.json, written by scripts/deploy.sh at the site root. */
export async function loadConfig(fetchImpl: typeof fetch = fetch): Promise<Config> {
  const r = await fetchImpl("/config.json", { cache: "no-store" });
  if (!r.ok) throw new Error(`config.json could not be loaded (HTTP ${r.status})`);
  const c = (await r.json()) as Partial<Config>;
  for (const k of ["apiUrl", "clientId", "cognitoDomain"] as const) {
    if (typeof c[k] !== "string" || !c[k]) throw new Error(`config.json has no ${k}`);
  }
  return c as Config;
}
