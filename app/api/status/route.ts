import { getIdentity } from "../../../cursor/identity";
import { MODEL } from "../../../lib/schema";
import { anthropicApiKey, json } from "../../../lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const identity = await getIdentity(request);
  const hasKey = Boolean(anthropicApiKey());
  const viewer = identity.verified
    ? identity.kind === "person"
      ? identity.name || "사용자"
      : identity.name || "API 키"
    : "";
  return json({
    model: MODEL,
    mock: !hasKey,
    viewer,
    simulated: identity.verified && identity.simulated === true,
  });
}
