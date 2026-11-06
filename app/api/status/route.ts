import { requireIdentity } from "../../../cursor/identity";
import { MODEL } from "../../../lib/schema";
import { json } from "../../../lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const identity = await requireIdentity(request);
  if (identity instanceof Response) return identity;
  const hasKey = Boolean(process.env.ANTHROPIC_API_KEY);
  return json({
    model: MODEL,
    mock: !hasKey,
    viewer: identity.kind === "person" ? identity.name || "사용자" : identity.name || "API 키",
    simulated: identity.simulated === true,
  });
}
